import math
import pprint
from typing import Any, Literal

import seutil as su
from etestgen.macros import Macros
from etestgen.utils import aggregate_metrics, summarize_metrics
from jsonargparse import CLI
from throwgen.eval.eval_set import pad_missing_as_failed
from throwgen.macros import Macros as ThrowgenMacros
import numpy as np

logger = su.log.get_logger(__name__, su.log.INFO)
K_LIST = [1, 5, 10]

def pass_at_k(n: int, c: int, k: int) -> float:
    if k > n:
        raise ValueError("k cannot be greater than n")
    if c > n:
        raise ValueError("c cannot be greater than n")
    if k <= 0 or n <= 0:
        raise ValueError("k and n must be positive")

    if n - c < k:
        return 1.0
    if k == 1:
        return c / n
    numerator = np.arange(n - c + 1 - k, n - k + 1, dtype=np.float64)
    denominator = np.arange(n - c + 1, n + 1, dtype=np.float64)
    return 1.0 - np.exp(np.sum(np.log(numerator) - np.log(denominator)))

def get_pass_at_k_metrics(
    dataset_name: str,
    llm_type: str,
    model_name: str,
    setup: str,
    prompt_gen_type: str,
    metrics_type: Literal["run-ebts", "run-all", "run-all-with-tools"],
):
    logger.info(f"Doing pass@k on {dataset_name} {model_name} {prompt_gen_type}")
    all_metrics: list[dict[str, Any]] = su.io.load(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"{metrics_type}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )  # type: ignore
    all_metrics = pad_missing_as_failed(all_metrics, dataset_name)

    all_pass_at_k_metrics: list[dict[str, float]] = []
    for metric in all_metrics:
        result_list: list[dict[str, dict[str, Any]]] = metric["result"]
        compiled_cnt = 0
        all_pass_cnt = 0
        for r in result_list:
            compiled_cnt += r["summary"]["compiled"]
            all_pass_cnt += r["summary"]["all-pass"]
        task_metrics = {"id": metric["id"]}
        for k in K_LIST:
            task_metrics[f"compiled-at-{k}"] = pass_at_k(len(result_list), compiled_cnt, k)
            task_metrics[f"pass-at-{k}"] = pass_at_k(len(result_list), all_pass_cnt, k)
        all_pass_at_k_metrics.append(task_metrics)
    su.io.dump(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"{metrics_type}-pass-at-k-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl",
        all_pass_at_k_metrics,
    )

    aggregated_results = aggregate_metrics(all_pass_at_k_metrics)  # type: ignore
    del aggregated_results["id"]
    summary_pass_at_k = summarize_metrics(aggregated_results)  # type: ignore
    logger.info(f"{metrics_type} summary:\n" + pprint.pformat(summary_pass_at_k))
    su.io.dump(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"{metrics_type}-pass-at-k-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-summary.json",
        summary_pass_at_k,
        su.io.Fmt.jsonPretty,
    )


if __name__ == "__main__":
    su.log.setup(Macros.log_file)
    CLI(get_pass_at_k_metrics, as_positional=False)
