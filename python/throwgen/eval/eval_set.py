"""The full set of \\tarmethods an evaluation is supposed to cover.

A project that fails to clone, check out, or compile is dropped by
`runtime_metrics._secure_proj_runtime_metrics`, which logs a warning and
returns no rows. Its \\tarmethods then vanish from the metrics files
entirely, so every rate computed from those files silently uses a smaller
denominator than the dataset. This module restores the dataset as the
denominator and counts an unevaluated \\tarmethod as a failure.
"""

from typing import Any

import seutil as su

from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__, su.log.INFO)


def load_eval_ids(dataset_name: str) -> list[str]:
    """Every \\tarmethod id in the dataset, in dataset order."""
    ids: list[Any] = su.io.load(
        ThrowgenMacros.mebt_data_dir / dataset_name / "id.jsonl"
    )  # type: ignore
    return [str(i) for i in ids]


def failed_result(num_samples: int) -> list[dict[str, Any]]:
    """`result` entries standing in for samples that were never evaluated."""
    return [
        {"summary": {"compiled": 0, "pass-ratio": 0.0, "all-pass": False}}
        for _ in range(num_samples)
    ]


def pad_missing_as_failed(
    rows: list[dict[str, Any]],
    dataset_name: str,
    id_key: str = "id",
) -> list[dict[str, Any]]:
    """Append an all-failed row for each dataset id absent from `rows`.

    The stand-in rows carry as many samples as the rows that were evaluated,
    so pass@k sees the same n for every \\tarmethod.
    """
    present = {str(r[id_key]) for r in rows}
    missing = [i for i in load_eval_ids(dataset_name) if i not in present]
    if not missing:
        return rows

    sample_counts = {len(r["result"]) for r in rows if "result" in r}
    if len(sample_counts) != 1:
        raise ValueError(
            f"cannot pad {len(missing)} unevaluated \\tarmethods: the evaluated "
            f"rows carry differing sample counts {sorted(sample_counts)}"
        )
    num_samples = sample_counts.pop()

    logger.warning(
        f"{len(missing)} \\tarmethods have no evaluation result and are counted "
        f"as failures: {missing}"
    )
    return rows + [
        {id_key: i, "result": failed_result(num_samples)} for i in missing
    ]
