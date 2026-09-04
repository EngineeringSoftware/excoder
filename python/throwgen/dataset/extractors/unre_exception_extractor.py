import os
import re
from collections.abc import Iterator
from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_extractor import BaseExtractor
# from throwgen.eval.runtime import RuntimeMetrics
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override

logger = su.log.get_logger(__name__)


class UnreExceptionExtractor(BaseExtractor):
    @override
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        super().__init__(all_data, meta_data)
        self._dataset_name = meta_data["dataset_name"]
        self._dummy_result_path = (
            ThrowgenMacros.metrics_dir
            / self._dataset_name
            / "run-ebts-base-dummy-mut_no_throw-dummy-each-sample.jsonl"
        )
        if os.path.isfile(self._dummy_result_path):
            dummy_result: list[dict[str, Any]] = su.io.load(self._dummy_result_path)  # type: ignore
            self._id2dummy = {
                d["id"]: d["result"][0]["module_result"] for d in dummy_result
            }
        else:
            self._id2dummy = None

    @property
    @override
    def field_name(self) -> str:
        return "unreported_exception"

    @override
    def setup(self):
        logger.info(f"Setting up for {self.field_name} extractor")

        # dummy experiment
        # from throwgen.llm.base_experiment import BaseExperiment

        # dummy_exp = BaseExperiment("dummy")
        # dummy_exp.do_dummy_experiment(
        #     self._dataset_name, "nebts", data_attr="mut_no_throw"
        # )

        # eval dummy results
        # runtime_metrics = RuntimeMetrics(
        #     "base", "dummy", "dummy", self._dataset_name, "nebts"
        # )
        # runtime_metrics.run_eval()
        pass

    @override
    def extract_field(self, data: DataMultiEBT) -> list[tuple[int, str]]:
        assert self._id2dummy is not None
        if self._id2dummy[data.id]["success"]:
            return []

        unre_exc_matches = set(
            re.findall(
                r"\[(\d+),\d+\]\s*(?:error:)?\s*unreported\sexception\s*(.*);",
                self._id2dummy[data.id]["stdout"],
            )
        )
        out = [
            (int(line_n) - data.start_line - 2, exception)
            for line_n, exception in unre_exc_matches
        ]
        return out
