import pprint
from collections import defaultdict
from typing import Any, Literal

import seutil as su
from etestgen.macros import Macros
from etestgen.utils import (aggregate_metrics, summarize_metrics,
                            summarize_topk_metrics)
from jsonargparse import CLI
from throwgen.dataset.multi_ebt_data import MultiEBTDataset
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__, su.log.INFO)


def get_partial_output(
    original_dataset_name: str,
    new_dataset_name: str,
    llm_type: str,
    model_name: str,
    setup: str,
    prompt_gen_type: str,
):
    original_output: list[dict[str, Any]] = su.io.load(
        ThrowgenMacros.llm_output_dir
        / original_dataset_name
        / f"{llm_type}-{model_name}-{prompt_gen_type}-{setup}.jsonl"
    )  # type: ignore
    new_dataset = MultiEBTDataset.from_saved(
        ThrowgenMacros.mebt_data_dir / new_dataset_name
    )

    # check if new dataset is a subset of old dataset
    new_dataset_ids = set([data.id for data in new_dataset])
    old_dataset_ids = set([metric["id"] for metric in original_output])
    # assert new_dataset_ids.issubset(old_dataset_ids)

    new_output = [
        metric for metric in original_output if metric["id"] in new_dataset_ids
    ]

    su.io.dump(
        ThrowgenMacros.llm_output_dir
        / new_dataset_name
        / (f"{llm_type}-{model_name}-{prompt_gen_type}-{setup}.jsonl"),
        new_output,
    )


def get_partial_metrics(
    original_dataset_name: str,
    new_dataset_name: str,
    llm_type: str,
    model_name: str,
    setup: str,
    prompt_gen_type: str,
    metrics_type: Literal["sim", "run-ebts", "run-nebts", "coverage"],
):
    original_metrics: list[dict[str, Any]] = su.io.load(
        ThrowgenMacros.metrics_dir
        / original_dataset_name
        / f"{metrics_type}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )  # type: ignore
    new_dataset = MultiEBTDataset.from_saved(
        ThrowgenMacros.mebt_data_dir / new_dataset_name
    )

    # check if new dataset is a subset of old dataset
    new_dataset_ids = set([data.id for data in new_dataset])
    old_dataset_ids = set([metric["id"] for metric in original_metrics])
    # assert new_dataset_ids.issubset(old_dataset_ids)

    new_metrics_each_sample = [
        metric for metric in original_metrics if metric["id"] in new_dataset_ids
    ]
    new_meterics_values = []
    for metric_item in new_metrics_each_sample:
        match metrics_type:
            case "sim":
                new_meterics_values.append(metric_item["result"])
            case "run-ebts" | "run-nebts" | "coverage":
                top_k_metrics = defaultdict(list)
                for result in metric_item["result"]:
                    for k, v in result["summary"].items():
                        top_k_metrics[k].append(v)
                new_meterics_values.append(summarize_topk_metrics(top_k_metrics))
            case _:
                raise ValueError(f"{metrics_type} is not a vaild metrics type")

    new_metrics_summary = summarize_metrics(aggregate_metrics(new_meterics_values))  # type: ignore
    su.io.dump(
        ThrowgenMacros.metrics_dir
        / new_dataset_name
        / (
            f"{metrics_type}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-summary.json"
        ),
        new_metrics_summary,
        su.io.Fmt.jsonPretty,
    )
    su.io.dump(
        ThrowgenMacros.metrics_dir
        / new_dataset_name
        / (
            f"{metrics_type}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
        ),
        new_metrics_each_sample,
    )
    logger.info(f"{metrics_type} summary:\n" + pprint.pformat(new_metrics_summary))


if __name__ == "__main__":
    su.log.setup(Macros.log_file)
    CLI([get_partial_metrics, get_partial_output], as_positional=False)
