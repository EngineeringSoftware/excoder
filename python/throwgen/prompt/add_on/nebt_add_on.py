from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.append_add_on import AppendAddOn
from throwgen.utils import markdown
from typing_extensions import override


class NebtAddOn(AppendAddOn):
    FIELD_NAME = "nebt"

    @override
    def _get_arg(self, data: DataMultiEBT, curr_args: dict[str, str]) -> str:
        nebt_prompt = ""
        if len(data.nebts) > 0:
            nebt_prompt += self._desc
            for i, item in enumerate(data.nebts):
                nebt_prompt += f"- NEBT #{i}\n"
                nebt_prompt += markdown.code_block(item.raw_code, "java") + "\n\n"
        return nebt_prompt
