import math
import pprint
from collections import defaultdict
from typing import Any, Literal

import seutil as su
from etestgen.macros import Macros
from etestgen.utils import (aggregate_metrics, summarize_metrics,
                            summarize_topk_metrics)
from jsonargparse import CLI
from throwgen.eval.transform_results.pass_at_k_metrics import pass_at_k
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__, su.log.INFO)


def get_combined_test_metrics(
    dataset_name: str,
    llm_type: str,
    model_name: str,
    setup: str,
    prompt_gen_type: str,
):
    logger.info(
        f"combining ebt & nebt for {dataset_name} {model_name} {prompt_gen_type}"
    )
    ebts_metrics: list[dict[str, Any]] = su.io.load(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"run-ebts-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )  # type: ignore
    nebts_metrics: list[dict[str, Any]] = su.io.load(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"run-nebts-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )  # type: ignore
    nebts_dict = {r["id"]: r for r in nebts_metrics}
    combined_results = []
    new_meterics_values = []
    for em in ebts_metrics:
        if em["id"] in nebts_dict:
            nm = nebts_dict[em["id"]]
            all_metrics = []
            top_k_metrics = defaultdict(list)
            for e_result, n_result in zip(em["result"], nm["result"], strict=True):
                if e_result["module_result"]["success"]:
                    each_test = e_result["each_test"] + n_result["each_test"]
                    pass_cnt = sum([t["passed"] for t in each_test])
                    summary = {
                        "compiled": 1,
                        "pass-ratio": pass_cnt / len(each_test),
                        "all-pass": pass_cnt == len(each_test),
                    }
                    for k, v in summary.items():
                        top_k_metrics[k].append(v)
                    all_metrics.append(
                        {
                            "summary": summary,
                            "module_result": e_result["module_result"],
                            "each_test": each_test,
                        }
                    )
                else:
                    all_metrics.append(e_result)

            combined_results.append({"id": em["id"], "result": all_metrics})
            new_meterics_values.append(summarize_topk_metrics(top_k_metrics))
        else:
            top_k_metrics = defaultdict(list)
            for result in em["result"]:
                for k, v in result["summary"].items():
                    top_k_metrics[k].append(v)
            new_meterics_values.append(summarize_topk_metrics(top_k_metrics))
            combined_results.append(em)
    new_metrics_summary = summarize_metrics(aggregate_metrics(new_meterics_values))  # type: ignore
    logger.info(f"summary:\n" + pprint.pformat(new_metrics_summary))

    su.io.dump(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / (
            f"run-all-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-summary.json"
        ),
        new_metrics_summary,
        su.io.Fmt.jsonPretty,
    )
    su.io.dump(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / (
            f"run-all-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
        ),
        combined_results,
    )

def get_combined_with_tools_metrics(
    dataset_name: str,
    llm_type: str,
    model_name: str,
    setup: str,
    prompt_gen_type: str,
):
    """
    Combine ``run-all-*`` (EBTs + NEBTs) with ``run-tools-*`` (Randoop +
    EvoSuite) per-sample results to produce ``run-all-with-tools-*``.

    For samples where tool tests exist and the module compiled, the tool test
    results are appended to the EBT/NEBT test list before re-aggregating pass
    metrics.  Samples without tool tests are kept as-is from ``run-all``.
    """
    logger.info(
        f"combining run-all & run-tools for {dataset_name} {model_name} {prompt_gen_type}"
    )
    run_all_path = (
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"run-all-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )
    run_tools_path = (
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"run-tools-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )
    run_all_each: list[dict[str, Any]] = su.io.load(run_all_path)  # type: ignore

    if run_tools_path.exists():
        run_tools_each: list[dict[str, Any]] = su.io.load(run_tools_path)  # type: ignore
        tools_dict: dict[str, dict[str, Any]] = {r["id"]: r for r in run_tools_each}
    else:
        logger.warning(
            f"run-tools missing for {model_name} {prompt_gen_type}; "
            f"run-all-with-tools will mirror run-all."
        )
        tools_dict = {}

    combined_results = []
    new_metrics_values = []

    for am in run_all_each:
        top_k_metrics: dict[str, list] = defaultdict(list)

        if am["id"] not in tools_dict:
            # No tool tests for this sample — propagate run-all unchanged.
            for result in am["result"]:
                for k, v in result["summary"].items():
                    top_k_metrics[k].append(v)
            new_metrics_values.append(summarize_topk_metrics(top_k_metrics))
            combined_results.append(am)
            continue

        tm = tools_dict[am["id"]]
        all_results = []
        for a_result, t_result in zip(am["result"], tm["result"], strict=True):
            if a_result["module_result"]["success"]:
                each_test = a_result["each_test"] + t_result["each_test"]
                pass_cnt = sum(t["passed"] for t in each_test)
                total = len(each_test)
                summary = {
                    "compiled": 1,
                    "pass-ratio": pass_cnt / total if total > 0 else 0.0,
                    "all-pass": int(pass_cnt == total),
                }
                for k, v in summary.items():
                    top_k_metrics[k].append(v)
                all_results.append(
                    {
                        "summary": summary,
                        "module_result": a_result["module_result"],
                        "each_test": each_test,
                    }
                )
            else:
                for k, v in a_result["summary"].items():
                    top_k_metrics[k].append(v)
                all_results.append(a_result)

        combined_results.append({"id": am["id"], "result": all_results})
        new_metrics_values.append(summarize_topk_metrics(top_k_metrics))

    new_metrics_summary = summarize_metrics(aggregate_metrics(new_metrics_values))  # type: ignore
    logger.info(f"summary:\n" + pprint.pformat(new_metrics_summary))

    prefix = f"run-all-with-tools-{llm_type}-{model_name}-{prompt_gen_type}-{setup}"
    su.io.dump(
        ThrowgenMacros.metrics_dir / dataset_name / f"{prefix}-summary.json",
        new_metrics_summary,
        su.io.Fmt.jsonPretty,
    )
    su.io.dump(
        ThrowgenMacros.metrics_dir / dataset_name / f"{prefix}-each-sample.jsonl",
        combined_results,
    )


if __name__ == "__main__":
    su.log.setup(Macros.log_file)
    CLI([get_combined_test_metrics, get_combined_with_tools_metrics], as_positional=False)
