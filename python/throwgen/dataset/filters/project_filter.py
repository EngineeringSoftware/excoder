from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override


class ProjectFilter(BaseDataFilter):
    """Restrict a dataset to the 161 projects the paper evaluates on.

    Two groups are tossed: the projects held out for validation, and every
    project past the first 161 in collection order.  Both lists are fixed
    inputs -- `held-out-val-projects/project.jsonl` is the project column of
    the validation set the split was drawn from -- so that every funnel stage
    is restricted to exactly the same projects and the counts in Table I line
    up across stages.
    """

    def __init__(self, meta_data: dict[str, Any]):
        super().__init__(meta_data)
        val_project_file_path = (
            ThrowgenMacros.mebt_data_dir / "held-out-val-projects" / "project.jsonl"
        )
        all_project_file_path = (
            ThrowgenMacros.mebt_data_dir / "non-direct-mega-test-data" / "project.jsonl"
        )
        val_projects: set[str] = set()
        with open(val_project_file_path) as val_project_file:
            for p in val_project_file.readlines():
                val_projects.add(p.strip()[1:-1])

        all_projects: list[str] = []
        with open(all_project_file_path) as all_project_file:
            for p in all_project_file.readlines():
                if p not in val_projects and p.strip()[1:-1] not in all_projects:
                    all_projects.append(p.strip()[1:-1])
        self._toss_projects = set(all_projects[161:]).union(val_projects)

    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        return data.project in self._toss_projects
