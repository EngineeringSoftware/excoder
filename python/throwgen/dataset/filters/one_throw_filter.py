import re
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from typing_extensions import override


class OneThrowFilter(BaseDataFilter):
    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        mut_content_match = re.search(r"{([\S\s]*)}", data.mut)
        assert mut_content_match is not None
        mut_content = mut_content_match.group(1).strip()
        return mut_content.startswith("throw")
