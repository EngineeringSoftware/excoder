from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override

class GenericExceptionFilter(BaseDataFilter):
    GENERIC_EXCEPTIONS = ["java.lang.Exception", "java.lang.Throwable"]
    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        is_generic = []
        for ebt in data.ebts:
            is_generic.append(ebt.exception in self.GENERIC_EXCEPTIONS)
        return any(is_generic)
