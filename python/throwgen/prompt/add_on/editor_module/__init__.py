from throwgen.prompt.add_on.editor_module.base_editor_module import \
    BaseEditorModule
from throwgen.prompt.add_on.editor_module.coverage_editor_module import \
    CoverageEditorModule
from throwgen.prompt.add_on.editor_module.thrown_exception_editor_module import \
    ThrownExceptionEditorModule
from throwgen.prompt.add_on.editor_module.unre_editor_module import \
    UnreEditorModule


def get_editor_module(name: str) -> BaseEditorModule:
    coverage_editor = CoverageEditorModule("coverage-postfix")
    unre_editor = UnreEditorModule("unre-postfix")
    thrown_exception_editor = ThrownExceptionEditorModule("thrown-exception-postfix")

    match name:
        case coverage_editor.edit_name:
            return coverage_editor
        case unre_editor.edit_name:
            return unre_editor
        case thrown_exception_editor.edit_name:
            return thrown_exception_editor
        case _:
            raise ValueError(f"{name} is not a valid editor module name")
