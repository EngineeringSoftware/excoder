from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.class_info_add_on import ClassInfoAddOn
from throwgen.utils import markdown
from typing_extensions import override


class MethodInfoAddOn(ClassInfoAddOn):
    FIELD_NAME = "method-info"

    @override
    def _get_arg(self, data: DataMultiEBT, curr_args: dict[str, str]) -> str:
        method_info_prompt_dict = {}
        for type_info in data.method_info["type_list"]:
            if len(type_info) > 1:
                for k, v in type_info.items():
                    formated_info = {}
                    if len(v) != 0 and k != "_debug" and k != "class_name":
                        items_list = [self.PROCESSOR_MAP[k](item) for item in v]
                        formated_info[self.NAME_MAP[k]] = items_list
                        method_info_prompt_dict[type_info["class_name"]] = formated_info
        method_info_prompt = ""
        if len(method_info_prompt_dict) > 0:
            method_info_prompt += self._desc
            method_info_prompt += markdown.unordered_list(method_info_prompt_dict) + "\n"
        return method_info_prompt
