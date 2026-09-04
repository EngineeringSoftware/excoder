import re

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on import get_add_on, is_editor_add_on
from throwgen.prompt.add_on.base_add_on import BaseAddOn
from throwgen.prompt.multi_ebt_prompt_gen import MultiEBTPrompt
from typing_extensions import override


class AddOnPrompt(MultiEBTPrompt):
    @override
    def __init__(self, system_file_name: str, user_file_name: str, **kwargs):
        super().__init__(system_file_name, user_file_name)
        self._add_ons: list[BaseAddOn] = []
        # non editor add on (append add on)
        for field_name in re.findall(r"~`([^~]*)`~", self._user):
            if not is_editor_add_on(field_name):
                add_on = get_add_on(field_name)
                if add_on is not None:
                    self._add_ons.append(add_on)
        # editor add ons later since it could be depend on append add on
        for field_name in re.findall(r"~`([^~]*)`~", self._user):
            if is_editor_add_on(field_name):
                add_on = get_add_on(field_name)
                if add_on is not None:
                    self._add_ons.append(add_on)

    def data_availability(self, data: DataMultiEBT) -> list[bool]:
        out = super()._get_multi_ebt_args(data)
        return [ao.data_available(data, out) for ao in self._add_ons]

    @override
    def _get_multi_ebt_args(self, data: DataMultiEBT) -> dict[str, str]:
        out = super()._get_multi_ebt_args(data)
        for ao in self._add_ons:
            ao.add_on_arg(data, out)
        return out
