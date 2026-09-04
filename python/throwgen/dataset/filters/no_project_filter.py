from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from throwgen.repos import load_all_projects
from typing_extensions import override


class NoProjectFilter(BaseDataFilter):
    def __init__(self, meta_data: dict[str, Any]):
        super().__init__(meta_data)
        self._proj_names = set()
        for proj in load_all_projects():
            self._proj_names.add(proj.full_name)

    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        return data.project not in self._proj_names
