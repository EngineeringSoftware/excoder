import re
from textwrap import indent
from typing import Optional, Self, Union

NestedStrDict = list[str] | dict[str, "NestedStrDict"]


def unordered_list(x: NestedStrDict) -> str:
    out = ""
    if isinstance(x, dict):
        for k, v in x.items():
            out += f"- {k}\n"
            out += indent(unordered_list(v), prefix="  ")
    elif isinstance(x, list):
        for item in x:
            out += f"- {item}\n"
    else:
        raise ValueError("input must be list or dict")
    return out


def title(content: str, level: int) -> str:
    if level < 0:
        raise ValueError(f"Level {level} is invalid")
    return "#" * level + f" {content}"


def inline_code(code: str) -> str:
    return f"`{code}`"


def extract_code_block(text: str) -> Optional[str]:
    code_match = re.search(
        r"```(\w*)\n([\s\S]*?)```",
        text,
        flags=re.MULTILINE,
    )
    if code_match is None:
        return None
    else:
        return code_match.group(2)


def code_block(code: str, lang: str) -> str:
    return f"```{lang}\n{code}\n```\n"


class MarkdownNode:
    def __init__(self, title_content: str, level: int, body: str, children: list[Self]):
        if level <= 0:
            raise ValueError(f"Level {level} is invalid")
        self._title = title_content
        self._level = level
        self._body = body
        self._children = children

    @classmethod
    def new_empty_node(cls, title_content: str, level: int) -> Self:
        return cls(title_content, level, "", [])

    def promote(self):
        self._level -= 1
        if self._level <= 0:
            raise ValueError(f"Node cannot be promoted to {self._level}")
        for child in self._children:
            child.promote()

    def demote(self):
        self._level += 1
        for child in self._children:
            child.demote()

    def append_child(self, content: Self):
        self._children.append(content)

    def append_body(self, content: str):
        self._body += content

    def replace_body(self, content: str):
        self._body = content

    def get_new_subsection(self, title_content) -> Self:
        new_subsection = self.new_empty_node(title_content, self._level + 1)
        self._children.append(new_subsection)
        return new_subsection

    def __str__(self) -> str:
        out = title(self._title, self._level) + "\n\n"
        out += self._body + "\n\n"
        out += "\n\n".join([str(node) for node in self._children])
        return out
