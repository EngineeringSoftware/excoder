from typing import Any

import seutil as su
from etestgen.macros import Macros
from seutil.project import Project
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from typing_extensions import override


class SingleEBTFilter(BaseDataFilter):
    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        return len(data.ebts) == 1
