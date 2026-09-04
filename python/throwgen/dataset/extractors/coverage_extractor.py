import re

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_catched_info_extractor import \
    BaseCatchedInfoExtractor
from typing_extensions import override

logger = su.log.get_logger(__name__)


class CoverageExtractor(BaseCatchedInfoExtractor):
    @property
    @override
    def field_name(self) -> str:
        return "coverage"

    @override
    def extract_field(self, data: DataMultiEBT) -> list[list[int]]:
        assert self._id2dummy is not None
        if not self._id2dummy[data.id]["module_result"]["success"]:
            return []

        out: list[list[int]] = []
        for res in self._id2dummy[data.id]["each_test"]:
            if "coverage" not in res:
                out.append([])
            else:
                coverage_data = res["coverage"] if "coverage" in res else ""
                coverage_list_str = re.findall(r"LineNum:\[(\d+)\]", coverage_data)
                coverage_set_int: set[int] = set()
                for s in coverage_list_str:
                    c_line = int(s) - data.start_line - 3
                    if c_line >= 0 and c_line < len(data.mut_no_throw.splitlines()) - 3:
                        coverage_set_int.add(c_line)
                out.append(list(coverage_set_int))
        return out
