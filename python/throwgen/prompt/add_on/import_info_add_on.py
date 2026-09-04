from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.append_add_on import AppendAddOn
from throwgen.utils import markdown
from typing_extensions import override


class ImportInfoAddOn(AppendAddOn):
    FIELD_NAME = "import-info"

    @override
    def _get_arg(self, data: DataMultiEBT, curr_args: dict[str, str]) -> str:
        import_info_prompt = self._desc + "\n"
        import_info_prompt += markdown.unordered_list(
            [markdown.inline_code(iinfo) for iinfo in data.import_info]
        )
        return import_info_prompt
