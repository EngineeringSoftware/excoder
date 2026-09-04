from throwgen.prompt.add_on.base_add_on import BaseAddOn
from throwgen.prompt.add_on.class_info_add_on import ClassInfoAddOn
from throwgen.prompt.add_on.editor_add_on import EditorAddOn
from throwgen.prompt.add_on.method_info_add_on import MethodInfoAddOn
from throwgen.prompt.add_on.local_vars_add_on import LocalVarsAddOn
from throwgen.prompt.add_on.throw_info_add_on import ThrowInfoAddOn
from throwgen.prompt.add_on.import_info_add_on import ImportInfoAddOn
from throwgen.prompt.add_on.nebt_add_on import NebtAddOn


def is_editor_add_on(add_on_name: str) -> bool:
    return add_on_name.startswith(EditorAddOn.EDITOR_FNAME_PREFIX)


def get_add_on(add_on_name: str) -> BaseAddOn | None:
    if add_on_name.startswith(EditorAddOn.EDITOR_FNAME_PREFIX):
        editor_add_on = EditorAddOn("dummy")
        editor_add_on.setup_editor_from_field_str(add_on_name)
        return editor_add_on
    else:
        match add_on_name:
            case ClassInfoAddOn.FIELD_NAME:
                return ClassInfoAddOn("class-info-prefix")
            case MethodInfoAddOn.FIELD_NAME:
                return MethodInfoAddOn("method-info-prefix")
            case ThrowInfoAddOn.FIELD_NAME:
                return ThrowInfoAddOn("throw-info-prefix")
            case ImportInfoAddOn.FIELD_NAME:
                return ImportInfoAddOn("import-info-prefix")
            case NebtAddOn.FIELD_NAME:
                return NebtAddOn("nebt-prefix")
            case LocalVarsAddOn.FIELD_NAME:
                return LocalVarsAddOn("local-vars-prefix")
            case _:
                return None
