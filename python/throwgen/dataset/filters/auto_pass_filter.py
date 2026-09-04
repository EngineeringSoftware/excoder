from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override


class AutoPassFilter(BaseDataFilter):
    def __init__(self, meta_data: dict[str, Any]):
        super().__init__(meta_data)
        self._dataset_name = meta_data["dataset_name"]
        dummy_run_results: list[dict[str, Any]] = su.io.load(
            ThrowgenMacros.metrics_dir
            / self._dataset_name
            / "run-ebts-base-dummy-mut_no_throw-dummy-each-sample.jsonl"
        ) # type: ignore
        self._id2dummy_result: dict[str, dict[str, Any]] = {
            res["id"]: res for res in dummy_run_results
        }

    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        if data.id not in self._id2dummy_result:
            print(data.id)
            return True
        return self._id2dummy_result[data.id]["result"][0]["summary"]["all-pass"]
