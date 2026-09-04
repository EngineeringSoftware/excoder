from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from typing_extensions import override

class OnlySystemExceptionFilter(BaseDataFilter):
    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        system_exceptions = [not k.startswith("java") for k in data.throw_info]
        return all(system_exceptions)

class OnlyUserExceptionFilter(BaseDataFilter):
    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        system_exceptions = [not k.startswith("java") for k in data.throw_info]
        return not all(system_exceptions)
