from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.append_add_on import AppendAddOn
from throwgen.utils import markdown
from typing_extensions import override


class ThrowInfoAddOn(AppendAddOn):
    FIELD_NAME = "throw-info"

    def _info_to_list_str(self, info: dict[str, Any]) -> str:
        throw_info_prompt_dict = {}
        throw_info_prompt = ""
        for k, v in info.items():
            if len(v) != 0 and k != "_debug":
                items_list = [
                    markdown.inline_code(item) for item in v["public_constructors"]
                ]
                throw_info_prompt_dict[markdown.inline_code(k)] = items_list

        if len(throw_info_prompt_dict) > 0:
            throw_info_prompt += self._desc
            throw_info_prompt += markdown.unordered_list(throw_info_prompt_dict)

        return throw_info_prompt

    
    @override
    def _get_arg(self, data: DataMultiEBT, curr_args: dict[str, str]) -> str:
        return self._info_to_list_str(data.throw_info)
