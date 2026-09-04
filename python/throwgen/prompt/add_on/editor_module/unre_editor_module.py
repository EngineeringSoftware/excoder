import copy
from collections import defaultdict

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.editor_module.base_editor_module import \
    BaseEditorModule
from throwgen.utils import code, markdown
from typing_extensions import override


class UnreEditorModule(BaseEditorModule):
    @property
    @override
    def edit_name(self) -> str:
        return "unre"

    @property
    @override
    def base_name(self) -> str:
        return "mut_no_throw"

    @override
    def _make_edit(self, base_field: str, data: DataMultiEBT) -> str:
        if len(data.unreported_exception) > 0:
            original_mut = markdown.extract_code_block(base_field)
            assert original_mut is not None
            commented_mut = copy.copy(original_mut)

            loc2exception = defaultdict(list)
            for loc, exception in data.unreported_exception:
                loc2exception[loc].append(exception)
            for loc, e_list in loc2exception.items():
                for exc in e_list:
                    if self._check_imported(exc, data):
                        commented_mut = code.add_comment(
                            commented_mut,
                            loc,
                            f"unreported {exc} here, it needs to be catched",
                        )
                    else:
                        commented_mut = code.add_comment(
                            commented_mut,
                            loc,
                            "unreported exception here but class not imported, so catch it as `Exception`",
                        )

            edited_field = base_field.replace(original_mut, commented_mut)
            return edited_field + "\n" + self._desc + "\n"
        else:
            return base_field

    @staticmethod
    def _check_imported(unre_class: str, data: DataMultiEBT) -> bool:
        class_name = unre_class[unre_class.rfind(".") :]
        return any(class_name in imported_class for imported_class in data.import_info)
