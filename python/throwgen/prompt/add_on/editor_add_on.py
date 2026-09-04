from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.base_add_on import BaseAddOn
from throwgen.prompt.add_on.editor_module import get_editor_module
from throwgen.prompt.add_on.editor_module.base_editor_module import \
    BaseEditorModule
from typing_extensions import override


class EditorAddOn(BaseAddOn):
    EDITOR_FNAME_PREFIX = "editor@"

    def __init__(self, desc_file_name: str):
        self._field_name = "editor"
        super().__init__(desc_file_name)
        self._base_field_name = None
        self._editor_modules: list[BaseEditorModule] = []

    def setup_editor_from_field_str(self, field_str: str):
        assert field_str.startswith(self.EDITOR_FNAME_PREFIX)
        self._field_name = field_str
        base_field_name, editor_module_str = field_str[
            len(self.EDITOR_FNAME_PREFIX) :
        ].split(":")
        self._base_field_name = base_field_name
        editor_module_names = editor_module_str.split(",")
        self._editor_modules = [get_editor_module(name) for name in editor_module_names]
        for em in self._editor_modules:
            assert em.base_name == self._base_field_name

    @property
    @override
    def field_name(self) -> str:
        return self._field_name

    @override
    def data_available(self, data: DataMultiEBT, curr_args: dict[str, str]) -> bool:
        available_list = []
        assert self._base_field_name is not None
        for em in self._editor_modules:
            available_list.append(em.data_available(curr_args[self._base_field_name], data))
        return all(available_list)

    @override
    def add_on_arg(self, data: DataMultiEBT, curr_args: dict[str, str]):
        assert self._base_field_name is not None
        arg_str = self._get_arg(data, curr_args)
        curr_args[self.field_name] = arg_str
        del curr_args[self._base_field_name]

    def _get_arg(
        self, data: DataMultiEBT, curr_args: dict[str, str]
    ) -> str:
        assert self._base_field_name is not None
        assert len(self._editor_modules) != 0
        original_field: str = curr_args[self._base_field_name]
        current_field = original_field
        edited_list = []
        for em in self._editor_modules:
            updated_field = em(current_field, data)
            edited_list.append(updated_field == current_field)
            current_field = updated_field
        return current_field
