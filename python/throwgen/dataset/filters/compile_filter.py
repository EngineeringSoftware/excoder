import json
from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.filters.base_data_filter import BaseDataFilter
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override


class CompileFilter(BaseDataFilter):
    def __init__(self, meta_data: dict[str, Any]):
        super().__init__(meta_data)
        self._dataset_name = meta_data["dataset_name"]
        dummy_run_results: list[dict[str, Any]] = su.io.load(
            ThrowgenMacros.metrics_dir
            / self._dataset_name
            / "run-ebts-base-dummy-mut_no_throw-dummy-each-sample.jsonl"
        )  # type: ignore
        self._id2dummy_result: dict[str, dict[str, Any]] = {
            res["id"]: res for res in dummy_run_results
        }
        # One record per dropped method, with the compiler error that dropped
        # it; count_data_perks tallies these into the funnel percentages.
        self._rcf_path = (
            ThrowgenMacros.mebt_data_dir
            / self._dataset_name
            / "removed-compile-fail-samples.jsonl"
        )
        su.io.mkdir(self._rcf_path.parent)
        open(self._rcf_path, "w").close()

    @override
    def toss_data(self, data: DataMultiEBT) -> bool:
        test_result = self._id2dummy_result[data.id]["result"][0]
        toss = test_result["summary"]["compiled"] == 0
        comp_message = test_result["module_result"]["stdout"]
        missing_return_fail = "missing return statement" not in comp_message
        if not missing_return_fail:
            with open(self._rcf_path, "a") as rcf_file:
                rcf_file.write(
                    json.dumps(
                        {
                            "id": data.id,
                            "mut": f"```java\n{data.mut}\n```",
                            "mut_no_throw": f"```java\n{data.mut_no_throw}\n```",
                            "failure": "missing return",
                            "error_message": comp_message,
                        }
                    )
                )
                rcf_file.write("\n")

        type_fail = "incompatible types" not in comp_message
        if not type_fail:
            with open(self._rcf_path, "a") as rcf_file:
                rcf_file.write(
                    json.dumps(
                        {
                            "id": data.id,
                            "mut": f"```java\n{data.mut}\n```",
                            "mut_no_throw": f"```java\n{data.mut_no_throw}\n```",
                            "failure": "incompatible types",
                            "error_message": comp_message,
                        }
                    )
                )
                rcf_file.write("\n")

        toss = toss and missing_return_fail and type_fail

        return toss
