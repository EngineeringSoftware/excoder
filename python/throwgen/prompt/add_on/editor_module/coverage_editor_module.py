import copy
from collections import defaultdict

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.add_on.editor_module.base_editor_module import \
    BaseEditorModule
from throwgen.utils import code, markdown
from typing_extensions import override


class CoverageEditorModule(BaseEditorModule):
    @property
    @override
    def edit_name(self) -> str:
        return "coverage"

    @property
    @override
    def base_name(self) -> str:
        return "mut_no_throw"

    @override
    def _make_edit(self, base_field: str, data: DataMultiEBT) -> str:
        original_mut = markdown.extract_code_block(base_field)
        assert original_mut is not None
        commented_mut = copy.copy(original_mut)

        if sum([len(c) for c in data.coverage]) > 0:
            for i, cov in enumerate(data.coverage):
                for c_line in cov:
                    commented_mut = (
                        code.add_comment(commented_mut, c_line, f"EBT #{i}")
                    )
            edited_field = base_field.replace(original_mut, commented_mut)
            return edited_field + "\n" + self._desc + "\n"
        else:
            return base_field
