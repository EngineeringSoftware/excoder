from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.append_add_on import AppendAddOn
from throwgen.prompt.add_on.class_info_add_on import ClassInfoAddOn
from throwgen.utils import markdown
from typing_extensions import override


class LocalVarsAddOn(ClassInfoAddOn):
    FIELD_NAME = "local-vars"

    @override
    def _get_arg(self, data: DataMultiEBT, curr_args: dict[str, str]) -> str:
        local_var_prompt_dict = {}
        for type_name, info in data.local_variable_type.items():
            if len(info) > 0:
                type_info_dict = {}
                for k, v in info.items():
                    if len(v) > 0:
                        type_info_dict[self.NAME_MAP[k]] = [
                            self.PROCESSOR_MAP[k](item) for item in v
                        ]
                local_var_prompt_dict[type_name] = type_info_dict
        local_var_prompt = ""
        if len(local_var_prompt_dict) > 0:
            local_var_prompt += self._desc
            local_var_prompt += markdown.unordered_list(local_var_prompt_dict)  # type: ignore
        return local_var_prompt
