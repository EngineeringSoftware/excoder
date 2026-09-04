import os
from collections.abc import Iterator
from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_extractor import BaseExtractor
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__)


class BaseCatchedInfoExtractor(BaseExtractor):
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        super().__init__(all_data, meta_data)
        self._base_dataset_name = meta_data["dataset_name"]
        self._try_catch_dataset_name = "try-catch-" + self._base_dataset_name
        self._try_catch_dummy_result_path = (
            ThrowgenMacros.metrics_dir
            / self._try_catch_dataset_name
            / "coverage-base-dummy-mut_no_throw-dummy-each-sample.jsonl"
        )
        if os.path.isfile(self._try_catch_dummy_result_path):
            dummy_result: list[dict[str, Any]] = su.io.load(  # type: ignore
                self._try_catch_dummy_result_path
            )
            self._id2dummy = {d["id"]: d["result"][0] for d in dummy_result}
        else:
            self._id2dummy = None
