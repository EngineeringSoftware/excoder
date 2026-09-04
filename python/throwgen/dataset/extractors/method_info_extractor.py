import os
import re
from typing import Any, cast

from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.class_info_extractor import ClassInfoExtractor
from typing_extensions import override


class MethodInfoExtractor(ClassInfoExtractor):
    @property
    @override
    def field_name(self) -> str:
        return "method_info"

    @override
    def extract_field(self, data: DataMultiEBT) -> dict[str, Any]:
        maven_module = self._name2proj[data.project].modules[data.module_i]
        type_strings: list[str] = re.findall(r"L([0-9a-zA-Z/_]*);", data.mut_key)
        type_list = []
        for ts in type_strings:
            if not ts.startswith("java/"):
                # if it's not in java standard lib
                class_code_file_path = os.path.join(
                    maven_module.main_srcpath, ts + ".java"
                )
                if os.path.isfile(class_code_file_path):
                    class_info_dict = self._get_all_class_info(
                        maven_module.main_srcpath, data.id, ts.replace("/", "."), False
                    )
                    if class_info_dict is not None:
                        class_info_dict = cast(dict[str, Any], class_info_dict)
                        class_info_dict["class_name"] = ts.replace("/", ".")
                    type_list.append(class_info_dict)
        return {"type_list": type_list}
