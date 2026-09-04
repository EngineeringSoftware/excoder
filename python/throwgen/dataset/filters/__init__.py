from throwgen.dataset.filters.auto_pass_filter import AutoPassFilter
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from throwgen.dataset.filters.compile_filter import CompileFilter
# from throwgen.dataset.filters.evict_filter import EvictFilter
from throwgen.dataset.filters.exception_type_filter import (
    OnlySystemExceptionFilter,
    OnlyUserExceptionFilter,
)
from throwgen.dataset.filters.generic_exception_filter import GenericExceptionFilter
from throwgen.dataset.filters.no_gold_filter import NoGoldFilter
from throwgen.dataset.filters.no_project_filter import NoProjectFilter
from throwgen.dataset.filters.one_throw_filter import OneThrowFilter
from throwgen.dataset.filters.project_filter import ProjectFilter
# from throwgen.dataset.filters.exception_type_filter import OnlySystemExceptionFilter, OnlyUserExceptionFilter
from throwgen.dataset.filters.single_ebt_filter import SingleEBTFilter
NAME2FILTERS: dict[str, type[BaseDataFilter]] = {
    NoGoldFilter.__name__: NoGoldFilter,
    AutoPassFilter.__name__: AutoPassFilter,
    GenericExceptionFilter.__name__: GenericExceptionFilter,
    OneThrowFilter.__name__: OneThrowFilter,
    NoProjectFilter.__name__: NoProjectFilter,
    # UnreFilter.__name__: UnreFilter,
    CompileFilter.__name__: CompileFilter,
    OnlySystemExceptionFilter.__name__: OnlySystemExceptionFilter,
    OnlyUserExceptionFilter.__name__: OnlyUserExceptionFilter,
    ProjectFilter.__name__: ProjectFilter,
    SingleEBTFilter.__name__: SingleEBTFilter,
}
