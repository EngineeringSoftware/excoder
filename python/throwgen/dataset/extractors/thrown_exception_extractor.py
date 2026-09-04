import re

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_catched_info_extractor import (
    BaseCatchedInfoExtractor,
)
from typing_extensions import override

logger = su.log.get_logger(__name__)


class ThrownExceptionExtractor(BaseCatchedInfoExtractor):
    @property
    @override
    def field_name(self) -> str:
        return "thrown_exception"

    def extract_field(self, data: DataMultiEBT) -> list[list[str | int]]:
        assert self._id2dummy is not None
        if not self._id2dummy[data.id]["module_result"]["success"]:
            return []

        out: list[list[str | int]] = []
        for res in self._id2dummy[data.id]["each_test"]:
            coverage_data = res["coverage"] if "coverage" in res else ""
            exception_type_match = re.search(r"ExceptionType:\[(.*)\]", coverage_data)
            if exception_type_match is not None:
                exception_type = exception_type_match.group(1)
                exception_stack_info = re.findall(
                    r"ExceptionST:\[(.*;.*;\d+)\]", coverage_data
                )
                exception_loc = -1
                target_class_name = data.mut_key.split("#")[0]
                target_method_name = data.mut_key.split("#")[1]
                for e_stack in exception_stack_info:
                    stack_class_name, stack_method_name, stack_line_num = e_stack.split(
                        ";"
                    )
                    if (
                        target_class_name == stack_class_name
                        and target_method_name == stack_method_name
                    ):
                        exception_loc = int(stack_line_num) - data.start_line - 3
                        break
                    elif (
                        target_class_name == stack_class_name
                        and stack_method_name in data.mut_no_throw
                    ):
                        for i, line in enumerate(data.mut_no_throw.splitlines()):
                            if stack_method_name in line:
                                exception_loc = i
                                break
                        break
                if exception_loc > 0:
                    out.append([exception_loc, exception_type])
                else:
                    out.append([])
            else:
                out.append([])

        return out
