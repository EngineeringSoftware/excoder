import copy
from typing import cast

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.editor_module.unre_editor_module import \
    UnreEditorModule
from throwgen.utils import code, markdown
from typing_extensions import override


class ThrownExceptionEditorModule(UnreEditorModule):
    @property
    @override
    def edit_name(self) -> str:
        return "thrown-exception"

    @override
    def _make_edit(self, base_field: str, data: DataMultiEBT) -> str:
        if sum([len(e) for e in data.thrown_exception]) > 0 :
            original_mut = markdown.extract_code_block(base_field)
            assert original_mut is not None
            commented_mut = copy.copy(original_mut)

            for i, e_info in enumerate(data.thrown_exception):
                if len(e_info) > 0:
                    exception = cast(str, e_info[1])
                    loc = cast(int, e_info[0])
                    loc = min(loc, len(commented_mut.splitlines())-2)
                    if self._check_imported(exception, data):
                        commented_mut = code.add_comment(
                            commented_mut,
                            loc,
                            f"{exception} thrown here when running EBT #{i}",
                        )
                    else:
                        commented_mut = code.add_comment(
                            commented_mut,
                            loc,
                            f"Exception thrown here when running EBT #{i} you can handle it with `Exception`",
                        )



            edited_field = base_field.replace(original_mut, commented_mut)
            return edited_field + "\n" + self._desc + "\n"
        else:
            return base_field
