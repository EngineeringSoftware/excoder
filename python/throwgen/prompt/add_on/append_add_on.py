from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.base_add_on import BaseAddOn
from typing_extensions import override


class AppendAddOn(BaseAddOn):
    FIELD_NAME = "append_place_holder"

    @property
    @override
    def field_name(self) -> str:
        return self.FIELD_NAME

    @override
    def data_available(self, data: DataMultiEBT, curr_args: dict[str, str]) -> bool:
        return len(self._get_arg(data, curr_args)) != 0

    @override
    def add_on_arg(self, data: DataMultiEBT, curr_args: dict[str, str]):
        arg_str = self._get_arg(data, curr_args)
        curr_args[self.field_name] = arg_str
