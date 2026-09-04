import re
from functools import lru_cache

import tree_sitter_java
from tree_sitter import Language, Node, Parser

# McCabe decision points counted by cyclomatic_complexity.
DECISION_NODES = {
    "if_statement",
    "for_statement",
    "enhanced_for_statement",
    "while_statement",
    "do_statement",
    "catch_clause",
    "ternary_expression",
}
# Comment node types in tree-sitter-java. The grammar has no plain "comment"
# node; it distinguishes the two forms.
COMMENT_NODES = {"line_comment", "block_comment"}
# Control flow inside these is attributed to the nested callable, not the method.
EXCLUDED_NESTED_NODES = {
    "lambda_expression",
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "annotation_type_declaration",
}


def _count_decisions(node: Node, source: bytes) -> int:
    count = 0
    for child in node.children:
        if child.type in EXCLUDED_NESTED_NODES or child.type == "class_body":
            continue
        if child.type in DECISION_NODES:
            count += 1
        elif child.type == "switch_label":
            if source[child.start_byte : child.end_byte].lstrip().startswith(b"case"):
                count += 1
        elif child.type == "binary_expression":
            if any(token.type in {"&&", "||"} for token in child.children):
                count += 1
        count += _count_decisions(child, source)
    return count


# Prefix prepended to a bare method before parsing; byte offsets in the parsed
# source are shifted by its length relative to the original code.
_WRAPPER_PREFIX = "class Wrapper {\n"


@lru_cache(maxsize=1)
def _java_parser() -> Parser:
    return Parser(Language(tree_sitter_java.language()))


def _parse_callable(code: str) -> tuple[Node, bytes]:
    """Parse a single Java method/constructor, returning its node and the source.

    The source is `code` wrapped in a class declaration; subtract
    ``len(_WRAPPER_PREFIX)`` from a node's byte offsets to index into `code`.

    Raises ValueError for anything that is not exactly one method, including
    code mangled badly enough that the wrapper class does not parse.
    """
    wrapped = f"{_WRAPPER_PREFIX}{code}\n}}\n".encode()
    root = _java_parser().parse(wrapped).root_node
    # tree-sitter recovers from broken input by dropping nodes, so the wrapper
    # class and its body are not guaranteed to be there to walk into.
    body = next(
        (
            child
            for node in root.children
            for child in node.children
            if child.type == "class_body"
        ),
        None,
    )
    if body is None:
        raise ValueError("expected one method, found no parsable class body")
    callables = [
        node
        for node in body.children
        if node.type in {"method_declaration", "constructor_declaration"}
    ]
    if len(callables) != 1:
        raise ValueError(f"expected one method, found {len(callables)}")
    return callables[0], wrapped


def cyclomatic_complexity(code: str) -> int:
    """McCabe complexity of a single Java method or constructor.

    Counts 1 + if + loops + catch + ternary + non-default case labels +
    short-circuit && / ||. Control flow inside nested lambdas and classes is
    excluded, so the value describes the method itself.
    """
    callable_node, wrapped = _parse_callable(code)
    return 1 + _count_decisions(callable_node, wrapped)


def body_statements(code: str) -> list[Node] | None:
    """Top-level statements of a single Java method's body.

    Returns None when the method has no body (abstract / interface method).
    """
    callable_node, _ = _parse_callable(code)
    body = callable_node.child_by_field_name("body")
    if body is None:
        return None
    return [c for c in body.named_children if c.type not in COMMENT_NODES]


def is_only_throw(code: str) -> bool:
    """Whether the method body is a single throw statement and nothing else."""
    stmts = body_statements(code)
    return stmts is not None and len(stmts) == 1 and stmts[0].type == "throw_statement"


def strip_lone_return_null(code: str) -> str | None:
    """Drop a body consisting solely of ``return null;``, leaving an empty body.

    This undoes the placeholder that throw removal used to inject into
    non-void methods whose whole body was exception-raising code. Returns None
    when the body is anything else.
    """
    stmts = body_statements(code)
    if stmts is None or len(stmts) != 1 or stmts[0].type != "return_statement":
        return None
    offset = len(_WRAPPER_PREFIX)
    start, end = stmts[0].start_byte - offset, stmts[0].end_byte - offset
    encoded = code.encode()
    if encoded[start:end].split() != [b"return", b"null;"]:
        return None
    # Drop the whole line when the statement is alone on it, so the remaining
    # body reads as "{\n    }" like a void method's.
    line_start = encoded.rfind(b"\n", 0, start) + 1
    line_end = encoded.find(b"\n", end)
    if not encoded[line_start:start].strip() and (
        line_end == -1 or not encoded[end:line_end].strip()
    ):
        start, end = line_start, len(encoded) if line_end == -1 else line_end + 1
    return (encoded[:start] + encoded[end:]).decode()


@lru_cache(maxsize=8192)
def token_signature(code: str) -> str:
    """The code's tokens, with comments and all formatting dropped.

    Two methods that differ only in indentation, line breaks, spacing around
    operators, or comments have the same signature, so comparing signatures
    says whether one is the other rewritten. Built from the parse tree rather
    than by deleting text, so a ``//`` inside a string literal is not mistaken
    for a comment and the spacing inside a string literal is kept.

    Tokens are joined by a single space instead of being run together, so that
    ``a b`` and ``ab`` stay distinguishable.

    tree-sitter recovers from input it cannot parse rather than failing, so a
    snippet that is not valid Java still yields the tokens it does contain, and
    two such snippets still compare equal when they hold the same tokens.
    """
    source = (_WRAPPER_PREFIX + code + "\n}").encode()
    root = _java_parser().parse(source).root_node

    tokens: list[str] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in COMMENT_NODES:
            continue
        if node.child_count == 0:
            text = source[node.start_byte : node.end_byte].decode(errors="replace")
            if text:
                tokens.append((node.start_byte, text))
            continue
        stack.extend(node.children)

    return " ".join(text for _, text in sorted(tokens))


def same_code(left: str, right: str) -> bool:
    """Whether two snippets are the same code up to comments and formatting."""
    return token_signature(left) == token_signature(right)


def add_comment(code: str, line: int, content: str) -> str:

    code_lines = code.splitlines()
    code_lines[line] += f" // {content}"
    out = "\n".join(code_lines)
    if code[-1] == "\n":
        out += code[-1]
    return out

def remove_comment(code: str, comment_pattern: str) -> str:
    out = re.sub(r'\/\/\s*'+comment_pattern, r"", code)
    # print(out)
    return out
