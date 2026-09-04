from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import seutil as su
from etestgen.macros import Macros as ExlongMacros
from throwgen.dataset.data import DataMultiEBT, ToolTest
from throwgen.dataset.extractors.base_extractor import BaseExtractor
from typing_extensions import override

logger = su.log.get_logger(__name__)


class BaseToolTestExtractor(BaseExtractor):
    """
    Base extractor for tool-generated tests (Randoop/EvoSuite).

    Loads a pre-computed exceptions JSON file (list of dicts with keys:
    etest_method, exception, mut_key, project, stack_trace, rel_path) and
    indexes entries by (project, class_name, method_name) so they can be
    looked up per data point.

    Tool mut_key format: class#method#line
    DataMultiEBT mut_key format: class#method#descriptor
    Matching is done on the first two segments (class and method).

    Returns list[ToolTest] deduplicated by etest_method.
    """

    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        super().__init__(all_data, meta_data)
        exceptions_file = self._exceptions_file()
        if exceptions_file.exists():
            raw: list[dict[str, str]] = su.io.load(exceptions_file)  # type: ignore[assignment]
            # index: (project, class, method) → list of entries with rel_path
            self._index: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
            for entry in raw:
                rel_path = entry.get("rel_path", "")
                if not rel_path:
                    continue  # no backing file, skip
                parts = entry["mut_key"].split("#")
                if len(parts) < 2:
                    continue
                key = (entry["project"], parts[0], parts[1])
                self._index[key].append(entry)
        else:
            logger.warning(
                f"Tool exceptions file not found: {exceptions_file}; "
                f"{self.field_name} will be empty for all data points."
            )
            self._index = defaultdict(list)

    def _exceptions_file(self) -> Path:
        raise NotImplementedError

    @override
    def extract_field(self, data: DataMultiEBT) -> list[ToolTest]:
        parts = data.mut_key.split("#")
        key = (data.project, parts[0], parts[1])
        entries = self._index[key]
        # Deduplicate by etest_method; preserve order
        seen: set[str] = set()
        out: list[ToolTest] = []
        for entry in entries:
            em = entry["etest_method"]
            if em in seen:
                continue
            seen.add(em)
            out.append(ToolTest(etest_method=em, rel_path=entry["rel_path"]))
        return out


class RandoopTestExtractor(BaseToolTestExtractor):
    @property
    @override
    def field_name(self) -> str:
        return "randoop_tests"

    @override
    def _exceptions_file(self) -> Path:
        return ExlongMacros.exp_dir / "tool-results" / "randoop-exceptions.json"


class EvosuiteTestExtractor(BaseToolTestExtractor):
    @property
    @override
    def field_name(self) -> str:
        return "evosuite_tests"

    @override
    def _exceptions_file(self) -> Path:
        return ExlongMacros.exp_dir / "tool-results" / "evosuite-exceptions.json"
