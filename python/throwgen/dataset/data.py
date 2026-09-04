import dataclasses
import re
from pathlib import Path
from typing import Any, Self

from etestgen.data.data import DataNE2E
from etestgen.eval.compute_test_coverage import TestMethod


@dataclasses.dataclass
class ToolTest:
    """A single tool-generated test (Randoop / EvoSuite), stored as an
    etest_method identifier and a path to the backing Java file."""

    etest_method: str = ""  # "TestClass#testMethod"
    rel_path: str = ""      # path relative to ExlongMacros.exp_dir

    @property
    def test(self) -> str:
        """Read and return the content of the Java file."""
        from etestgen.macros import Macros as ExlongMacros
        return (ExlongMacros.exp_dir / self.rel_path).read_text(
            encoding="utf-8", errors="replace"
        )

    @property
    def fqcn(self) -> str:
        """Derive the fully qualified class name from the Java file."""
        content = self.test
        pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", content, re.MULTILINE)
        cls = re.search(r"public\s+class\s+(\w+)", content)
        class_name = cls.group(1) if cls else self.etest_method.split("#")[0]
        if pkg:
            return f"{pkg.group(1)}.{class_name}"
        return class_name


@dataclasses.dataclass
class DataMultiEBT:
    id: str = ""
    mut_key: str = ""
    mut: str = ""
    mut_no_throw: str = ""
    project: str = ""
    module_i: int = -1
    start_line: int = -1
    end_line: int = -1
    class_info: dict[str, Any] = dataclasses.field(default_factory=dict)
    throw_info: dict[str, Any] = dataclasses.field(default_factory=dict)
    method_info: dict[str, Any] = dataclasses.field(default_factory=dict)
    thrown_exception: list[list[str | int]] = dataclasses.field(default_factory=list)
    ebts: list[TestMethod] = dataclasses.field(default_factory=list)
    nebts: list[TestMethod] = dataclasses.field(default_factory=list)
    coverage: list[list[int]] = dataclasses.field(default_factory=list)
    unreported_exception: list[tuple[int, str]] = dataclasses.field(
        default_factory=list
    )
    local_variable_type: dict[str, dict[str, list[str]]] = dataclasses.field(
        default_factory=dict
    )
    import_info: list[str] = dataclasses.field(default_factory=list)
    randoop_tests: list[ToolTest] = dataclasses.field(default_factory=list)
    evosuite_tests: list[ToolTest] = dataclasses.field(default_factory=list)

    @classmethod
    def from_ne2e_list(cls, ne2e_list: list[DataNE2E]) -> Self:
        """
        Make sure all EBT(DataNoThrow) in the list have the same MUT
        Then create a DataMultiEBT with the id of the first item in the list
        """
        mut_key_set = set()
        for data in ne2e_list:
            mut_key_set.add(data.mut_key)
        if len(mut_key_set) != 1:
            raise ValueError(f"input have more than one mut {mut_key_set}")

        return cls(
            id=ne2e_list[0].id,
            mut_key=ne2e_list[0].mut_key,
            mut=ne2e_list[0].mut,
            project=ne2e_list[0].project,
            module_i=ne2e_list[0].module_i,
            start_line=ne2e_list[0].e_stack_trace[0][0]["startLine"],  # type: ignore
            end_line=ne2e_list[0].e_stack_trace[0][0]["endLine"],  # type: ignore
            ebts=[t.test_method for t in ne2e_list],
        )


@dataclasses.dataclass
class DataLLMOuput:
    id: str = ""
    preds: list[str] = dataclasses.field(default_factory=list)

    def extract_code(self) -> list[str]:
        out = []
        for pred in self.preds:
            code_match = re.search(
                r"```(\w*)\n([\s\S]*?)```",
                pred,
                flags=re.MULTILINE,
            )

            if code_match is not None:
                out.append(code_match.group(2))
            else:
                out.append("// No match")

        return out
