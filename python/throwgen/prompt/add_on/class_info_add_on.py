from collections import defaultdict
from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.append_add_on import AppendAddOn
from throwgen.utils import markdown
from typing_extensions import override


class ClassInfoAddOn(AppendAddOn):
    FIELD_NAME = "class-info"
    NAME_MAP = {
        "public_variables": "Variables",
        "public_methods": "Methods",
        "private_variables": "Variables",
        "private_methods": "Methods",
        "protected_variables": "Variables",
        "protected_methods": "Methods",
    }
    PROCESSOR_MAP = {
        "public_variables": lambda x: markdown.inline_code(x[: x.rfind("=")]),
        "public_methods": markdown.inline_code,
        "private_variables": lambda x: markdown.inline_code(x[: x.rfind("=")]),
        "private_methods": markdown.inline_code,
        "protected_variables": lambda x: markdown.inline_code(x[: x.rfind("")]),
        "protected_methods": markdown.inline_code,
    }

    @override
    def _get_arg(self, data: DataMultiEBT, curr_args: dict[str, str]) -> str:
        class_name = data.mut_key.split("#")[0]

        class_info_prompt_dict: markdown.NestedStrDict = defaultdict(list)
        for k, v in data.class_info.items():
            if len(v) != 0 and k != "_debug":
                items_list = [self.PROCESSOR_MAP[k](item) for item in v]
                class_info_prompt_dict[self.NAME_MAP[k]] += items_list # type: ignore
        class_info_prompt_dict = dict(class_info_prompt_dict)
        class_info_prompt = ""
        if len(class_info_prompt_dict) > 0:
            class_info_prompt += self._desc.format(class_name)
            class_info_prompt += markdown.unordered_list(class_info_prompt_dict) + "\n"

        return class_info_prompt
