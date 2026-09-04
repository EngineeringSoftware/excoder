"""Parse qualitative analysis markdown files, cross-reference with run-ebt metrics,
and compute summary statistics."""

import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import seutil as su
from jsonargparse import CLI

from throwgen.macros import Macros as ThrowgenMacros
from throwgen.utils import annotation_store
from etestgen.macros import Macros as ExlongMacros


logger = su.log.get_logger(__name__, su.log.INFO)

# Output directory for qualitative analysis results
QUALITATIVE_DIR: Path = ExlongMacros.work_dir / "results" / "qualitative"

# Annotation stores compared by ``run_agreement``, keyed by the annotator id
# that names each store's directory under annotations/. The key is also the
# name the agreement macros carry (``agree-<prompt>-<key>-...``), so renaming
# one renames the macros the paper reads.
# Agreement is between independent judgments, so the first inspector (a)
# enters as the store written before reconciliation, not
# `annotation_store.QUAL_COMMENTOR_ID`, which is the reconciled store the
# reported labels come from. Reading the reconciled store here would score a
# against labels that were revised to settle the very disagreements being
# measured.
AGREEMENT_STORES: dict[str, str] = {
    "a": "qual-false-positive-a",
    "b": "qual-false-positive-b",
    "agent": "qual-false-positive-agent",
}


def llm_output_rel_path(
    dataset_name: str,
    llm_type: str,
    model_name: str,
    prompt_gen_type: str,
    setup: str,
) -> str:
    """Path of an LLM output file relative to the project directory.

    This is the key the web viewer annotates under, so both sides of the
    annotation workflow name the same file the same way.
    """
    path = (
        ThrowgenMacros.llm_output_dir
        / dataset_name
        / f"{llm_type}-{model_name}-{prompt_gen_type}-{setup}.jsonl"
    )
    return str(path.relative_to(ExlongMacros.project_dir))


def load_samples(
    dataset_name: str,
    llm_type: str,
    model_name: str,
    prompt_gen_type: str,
    setup: str,
) -> list[dict]:
    """Load the manual inspection results for one experiment configuration.

    The labels come from the annotation store under ``annotations/`` that the
    web viewer writes, as ``{data_id, semantic_match, categories}`` records.
    """
    rel_path = llm_output_rel_path(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )
    store_file = annotation_store.store_path(
        annotation_store.QUAL_COMMENTOR_ID, rel_path
    )
    if not store_file.exists():
        logger.error(f"No annotations found at: {store_file}")
        return []
    samples = annotation_store.qual_samples(rel_path)
    logger.info(f"Loaded {len(samples)} annotations from {store_file}")
    return samples


def load_passing_ids(
    dataset_name: str,
    llm_type: str,
    model_name: str,
    prompt_gen_type: str,
    setup: str,
) -> set[str]:
    """Load run-ebt metrics and return IDs where at least one sample has pass-ratio == 1.0."""
    metrics_path = (
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"run-all-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )

    if not metrics_path.exists():
        logger.error(f"Metrics file not found: {metrics_path}")
        return set()

    all_metrics: list[dict[str, Any]] = su.io.load(metrics_path)  # type: ignore
    passing_ids: set[str] = set()

    for metric in all_metrics:
        data_id = metric["id"]
        result_list: list[dict[str, Any]] = metric["result"]
        if result_list[0]["summary"]["pass-ratio"] == 1.0:
            passing_ids.add(data_id)

    return passing_ids


def cohen_kappa(labels_a: list[bool], labels_b: list[bool]) -> Optional[float]:
    """Cohen's kappa for two raters on the same binary labels.

    ``kappa = (p_o - p_e) / (1 - p_e)``, with the chance agreement ``p_e``
    taken from each rater's own marginals. Returns ``None`` when either rater
    used a single label throughout: the coefficient is then either undefined
    (both constant, ``p_e == 1``) or pinned to 0 by construction rather than by
    the raters actually agreeing at chance, so reporting the number would
    mislead. An empty store is the common way to hit this.
    """
    n = len(labels_a)
    if n == 0 or n != len(labels_b):
        return None
    if len(set(labels_a)) < 2 or len(set(labels_b)) < 2:
        return None

    p_o = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    yes_a = sum(1 for a in labels_a if a) / n
    yes_b = sum(1 for b in labels_b if b) / n
    p_e = yes_a * yes_b + (1 - yes_a) * (1 - yes_b)
    if p_e >= 1:
        return None
    return (p_o - p_e) / (1 - p_e)


def store_verdicts(
    commentor_id: str, rel_path: str, passing_ids: set[str]
) -> tuple[dict[str, bool], list[str], list[str], set[str]]:
    """Score one annotation store the way ``run_analysis`` scores it.

    Returns the verdict of every passing \\ERC, the ids that were dropped, the
    ids that were defaulted, and the ids the store actually judged, so a caller
    can report how much of a store's score is judgment and how much is the
    default, and can compute agreement over judgment alone.

    Same two rules as ``run_analysis``: a record whose target method has no
    \\ERC with pass-ratio 1.0 is dropped, and a passing \\ERC the store does not
    mention is scored ``semantic_match = True``. The judged set additionally
    excludes the records decided by mechanical rule (note ending ``[auto]``).
    """
    labelled: dict[str, bool] = {}
    dropped: list[str] = []
    judged: set[str] = set()
    for sample in annotation_store.qual_samples(rel_path, commentor_id):
        data_id = sample["data_id"]
        if sample["semantic_match"] is None:
            continue
        if data_id not in passing_ids:
            dropped.append(data_id)
            continue
        labelled[data_id] = sample["semantic_match"]
        if not sample.get("auto"):
            judged.add(data_id)

    defaulted = sorted(passing_ids - set(labelled))
    verdicts = {d: labelled.get(d, True) for d in sorted(passing_ids)}
    return verdicts, sorted(dropped), defaulted, judged


def run_agreement(
    dataset_name: str,
    llm_type: str = "llama_cpp",
    model_name: str = "qwen2.5-coder:32b-instruct-q8_0",
    prompt_gen_type: str = "tuctn-all-info",
    setup: str = "multi_ebt",
):
    """Inter-annotator agreement between the qualitative annotation stores.

    Every pair of stores in ``AGREEMENT_STORES`` is compared over all \\ERCs with
    pass-ratio 1.0, scored exactly as ``run_analysis`` scores them, so the
    agreement describes the labels the paper's macros are actually built from
    rather than the subset two annotators happen to overlap on.

    Writes ``agreement_{prompt_gen_type}.json``, which
    ``table_gen.make_agreement_numbers`` turns into LaTeX macros.
    """
    passing_ids = load_passing_ids(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )
    if not passing_ids:
        logger.error("No passing IDs found; cannot compute agreement")
        return
    logger.info(f"Found {len(passing_ids)} IDs with pass-ratio=1.0 in metrics")

    rel_path = llm_output_rel_path(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )

    scored: dict[str, dict[str, bool]] = {}
    labelled_ids: dict[str, set[str]] = {}
    judged_ids: dict[str, set[str]] = {}
    stores: dict[str, dict[str, Any]] = {}
    for name, commentor_id in AGREEMENT_STORES.items():
        verdicts, dropped, defaulted, judged = store_verdicts(
            commentor_id, rel_path, passing_ids
        )
        scored[name] = verdicts
        labelled_ids[name] = passing_ids - set(defaulted)
        judged_ids[name] = judged
        stores[name] = {
            "commentor-id": commentor_id,
            "labelled": len(passing_ids) - len(defaulted),
            "defaulted": len(defaulted),
            "dropped-not-passing": len(dropped),
            "false-positives": sum(1 for v in verdicts.values() if not v),
        }
        logger.info(
            f"{name}: {stores[name]['labelled']} labelled, "
            f"{len(defaulted)} defaulted, {len(dropped)} dropped, "
            f"{stores[name]['false-positives']} false positives"
        )

    ids = sorted(passing_ids)
    names = list(AGREEMENT_STORES)
    pairs: dict[str, dict[str, Any]] = {}
    for i, name_a in enumerate(names):
        for name_b in names[i + 1 :]:
            a, b = scored[name_a], scored[name_b]
            # Agreement is over what the two annotators actually decided: the
            # \ERCs both judged, with the mechanically decided records excluded
            # from both sides. Counting a record neither opened -- both sides
            # take the same default -- would inflate the coefficient.
            pair_ids = sorted(judged_ids[name_a] & judged_ids[name_b])
            labels_a = [a[d] for d in pair_ids]
            labels_b = [b[d] for d in pair_ids]
            agree = sum(1 for x, y in zip(labels_a, labels_b) if x == y)
            kappa = cohen_kappa(labels_a, labels_b)
            pairs[f"{name_a}-{name_b}"] = {
                "total": len(pair_ids),
                "agree": agree,
                "disagree": len(pair_ids) - agree,
                "agreement-pct": (
                    round(agree / len(pair_ids) * 100, 2) if pair_ids else 0.0
                ),
                # Keep enough precision that the consumer's 2dp format rounds
                # the true value: at 4dp a kappa of 0.83501 stores as 0.835,
                # which formats to 0.83 rather than 0.84.
                "kappa": None if kappa is None else round(kappa, 6),
                "yes-yes": sum(1 for x, y in zip(labels_a, labels_b) if x and y),
                "yes-no": sum(1 for x, y in zip(labels_a, labels_b) if x and not y),
                "no-yes": sum(1 for x, y in zip(labels_a, labels_b) if not x and y),
                "no-no": sum(
                    1 for x, y in zip(labels_a, labels_b) if not x and not y
                ),
                # These two are over the whole passing population, not over the
                # agreement population above, so they do not sum to "disagree".
                # They describe the scored labels: how much of the difference
                # between two stores is a real difference of judgment, and how
                # much is one store not having reached the \\ERC.
                "disagree-both-labelled": sum(
                    1
                    for d in ids
                    if a[d] != b[d]
                    and d in labelled_ids[name_a]
                    and d in labelled_ids[name_b]
                ),
                "disagree-from-default": sum(
                    1
                    for d in ids
                    if a[d] != b[d]
                    and (
                        d not in labelled_ids[name_a]
                        or d not in labelled_ids[name_b]
                    )
                ),
            }
            if kappa is None:
                logger.warning(
                    f"{name_a} vs {name_b}: one store has no variance "
                    f"(is it empty?), kappa not reported"
                )
            else:
                logger.info(
                    f"{name_a} vs {name_b}: {agree}/{len(pair_ids)} = "
                    f"{agree / len(pair_ids) * 100:.1f}%, kappa = {kappa:.3f}"
                )

    result = {
        "prompt-gen-type": prompt_gen_type,
        "total-samples": len(ids),
        "stores": stores,
        "pairs": pairs,
    }
    su.io.mkdir(QUALITATIVE_DIR)
    out_path = QUALITATIVE_DIR / f"agreement_{prompt_gen_type}.json"
    su.io.dump(out_path, result, fmt=su.io.fmts.jsonPretty)
    logger.info(f"Wrote agreement to {out_path}")


def compute_summary(samples: list[dict]) -> dict:
    """Compute summary statistics from parsed samples.

    Returns:
        - total-samples: total count
        - semantic-match-yes: count and percentage of semantic match = yes
        - semantic-match-no: count and percentage of semantic match = no
        - semantic-match-unknown: count and percentage of semantic match = None
        - category-counts: for samples with semantic match = no,
          count and percentage of each category tag
    """
    total = len(samples)
    if total == 0:
        return {
            "total-samples": 0,
            "semantic-match-yes": {"count": 0, "percentage": 0.0},
            "semantic-match-no": {"count": 0, "percentage": 0.0},
            "semantic-match-unknown": {"count": 0, "percentage": 0.0},
            "category-counts": {},
        }

    sm_yes = sum(1 for s in samples if s["semantic_match"] is True)
    sm_no = sum(1 for s in samples if s["semantic_match"] is False)
    sm_unknown = sum(1 for s in samples if s["semantic_match"] is None)

    # Count categories among no-semantic-match samples
    no_sm_samples = [s for s in samples if s["semantic_match"] is False]
    category_counter: Counter = Counter()
    for s in no_sm_samples:
        for cat in s["categories"]:
            category_counter[cat] += 1

    num_no_sm = len(no_sm_samples)
    category_counts = {
        cat: {
            "count": count,
            "percentage": round(count / sm_no * 100, 2) if num_no_sm > 0 else 0.0,
        }
        for cat, count in category_counter.most_common()
    }

    return {
        "total-samples": total,
        "semantic-match-yes": {
            "count": sm_yes,
            "percentage": round(sm_yes / total * 100, 2),
        },
        "semantic-match-no": {
            "count": sm_no,
            "percentage": round(sm_no / sm_no * 100, 2),
        },
        "semantic-match-unknown": {
            "count": sm_unknown,
            "percentage": round(sm_unknown / total * 100, 2),
        },
        "category-counts": category_counts,
    }


def run_analysis(
    dataset_name: str,
    llm_type: str = "llama_cpp",
    model_name: str = "qwen2.5-coder:32b-instruct-q8_0",
    prompt_gen_type: str = "tuctn-all-info",
    setup: str = "multi_ebt",
):
    """Load manual inspection results, cross-reference with run-ebt metrics, and compute summary.

    Args:
        dataset_name: Name of the dataset to load metrics for.
        llm_type: LLM type (e.g., llama_cpp, azure).
        model_name: Model name.
        prompt_gen_type: Prompt generation type.
        setup: Experiment setup type.
    """
    # Load IDs that have at least one sample with pass-ratio == 1.0
    passing_ids = load_passing_ids(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )
    logger.info(f"Found {len(passing_ids)} IDs with pass-ratio=1.0 in metrics")

    annotated_samples = load_samples(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )
    if not annotated_samples:
        return

    # Deduplicate md entries by data_id (keep last occurrence)
    md_by_id: dict[str, dict] = {}
    for sample in annotated_samples:
        md_by_id[sample["data_id"]] = sample

    # Cross-reference
    final_samples: list[dict] = []

    # IDs in md that don't exist in metrics or don't have pass-ratio 1.0: throw out
    thrown_out_no_pass = []
    thrown_out_not_exist = []

    all_metrics_ids = _get_all_metrics_ids(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )

    for data_id, sample in md_by_id.items():
        if data_id not in all_metrics_ids:
            thrown_out_not_exist.append(data_id)
            continue
        if data_id not in passing_ids:
            thrown_out_no_pass.append(data_id)
            continue
        final_samples.append(sample)

    # IDs in metrics with pass-ratio 1.0 but NOT in md: default semantic_match=yes, categories=[]
    ids_in_md = set(md_by_id.keys())
    defaulted_ids = []
    for data_id in sorted(passing_ids):
        if data_id not in ids_in_md:
            final_samples.append({
                "data_id": data_id,
                "semantic_match": True,
                "categories": [],
            })
            defaulted_ids.append(data_id)

    # Print warnings
    if thrown_out_not_exist:
        logger.warning(
            f"IDs in md but not in metrics (thrown out): {sorted(thrown_out_not_exist)}"
        )
    if thrown_out_no_pass:
        logger.warning(
            f"IDs in md without pass-ratio=1.0 (thrown out): {sorted(thrown_out_no_pass)}"
        )
    if defaulted_ids:
        logger.info(
            f"IDs with pass-ratio=1.0 but not in md (defaulted to yes): "
            f"{len(defaulted_ids)} IDs"
        )

    # Sort by data_id for consistency
    final_samples.sort(key=lambda s: int(s["data_id"].split("-")[1]))

    logger.info(f"Final sample count: {len(final_samples)}")

    # Write each sample to JSONL
    su.io.mkdir(QUALITATIVE_DIR)
    each_sample_path = QUALITATIVE_DIR / f"qual_each_sample_{prompt_gen_type}.jsonl"
    su.io.dump(each_sample_path, final_samples)
    logger.info(f"Wrote samples to {each_sample_path}")

    # Compute and write summary
    summary = compute_summary(final_samples)
    summary_path = QUALITATIVE_DIR / f"qual_summary_{prompt_gen_type}.json"
    su.io.dump(summary_path, summary, fmt=su.io.fmts.jsonPretty)
    logger.info(f"Wrote summary to {summary_path}")

    # Print summary
    logger.info(f"Summary:")
    logger.info(f"  Total samples: {summary['total-samples']}")
    logger.info(
        f"  Semantic match yes: {summary['semantic-match-yes']['count']} "
        f"({summary['semantic-match-yes']['percentage']}%)"
    )
    logger.info(
        f"  Semantic match no: {summary['semantic-match-no']['count']} "
        f"({summary['semantic-match-no']['percentage']}%)"
    )
    if summary["semantic-match-unknown"]["count"] > 0:
        logger.info(
            f"  Semantic match unknown: {summary['semantic-match-unknown']['count']} "
            f"({summary['semantic-match-unknown']['percentage']}%)"
        )
    if summary["category-counts"]:
        logger.info(f"  Categories among no-semantic-match:")
        for cat, info in summary["category-counts"].items():
            logger.info(f"    {cat}: {info['count']} ({info['percentage']}%)")


def _get_all_metrics_ids(
    dataset_name: str,
    llm_type: str,
    model_name: str,
    prompt_gen_type: str,
    setup: str,
) -> set[str]:
    """Get all IDs present in the metrics file."""
    metrics_path = (
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"run-ebts-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
    )
    if not metrics_path.exists():
        return set()

    all_metrics: list[dict[str, Any]] = su.io.load(metrics_path)  # type: ignore
    return {m["id"] for m in all_metrics}


def find_missing_ids(
    dataset_name: str = "real-mega-test-data-with-exception-with-project-with-gold-with-throw",
    llm_type: str = "llama_cpp",
    model_name: str = "qwen2.5-coder:32b-instruct-q8_0",
    prompt_gen_type: str = "tuctn-all-info",
    setup: str = "multi_ebt",
):
    """Report which passing \\ERC still carry no manual label.

    A \\ERC counts as passing when at least one of its samples has
    pass-ratio == 1.0. Those are the ones the qualitative analysis has to
    judge, so any that the annotation store does not cover is outstanding work.
    The reverse direction is reported too: a labelled id that no longer passes
    means the labels are stale with respect to the metrics.

    Args:
        dataset_name: Name of the dataset to check against.
        llm_type: LLM type for loading metrics.
        model_name: Model name for loading metrics.
        prompt_gen_type: Prompt generation type, and the annotated result file.
        setup: Experiment setup type for loading metrics.
    """
    samples = load_samples(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )
    all_md_ids: set[str] = {s["data_id"] for s in samples}
    label = f"{prompt_gen_type} (annotations)"
    ids_by_file: dict[str, set[str]] = {label: all_md_ids}
    logger.info(f"Found {len(all_md_ids)} annotated ids for {label}")

    # Load passing IDs (IDs with at least one sample with pass-ratio == 1.0)
    passing_ids = load_passing_ids(
        dataset_name, llm_type, model_name, prompt_gen_type, setup
    )
    logger.info(f"Found {len(passing_ids)} IDs with pass-ratio=1.0 in metrics")

    # Find missing IDs (passing but not in any markdown file)
    missing_ids = passing_ids - all_md_ids
    missing_ids_sorted = sorted(missing_ids, key=lambda x: int(x.split("-")[1]))

    # Find extra IDs (in markdown but not passing)
    extra_ids = all_md_ids - passing_ids
    extra_ids_sorted = sorted(extra_ids, key=lambda x: int(x.split("-")[1]))

    # Report results
    logger.info(f"\n{'='*60}")
    logger.info(f"Passing but NOT annotated: {len(missing_ids)}")
    if missing_ids_sorted:
        for mid in missing_ids_sorted:
            logger.info(f"  - {mid}")

    logger.info(f"\n{'='*60}")
    logger.info(f"Annotated but NOT passing (pass-ratio != 1.0): {len(extra_ids)}")
    if extra_ids_sorted:
        for eid in extra_ids_sorted:
            logger.info(f"  - {eid}")

    return {
        "missing_ids": missing_ids_sorted,
        "extra_ids": extra_ids_sorted,
        "ids_by_file": {k: list(v) for k, v in ids_by_file.items()},
        "total_passing_ids": len(passing_ids),
        "total_md_ids": len(all_md_ids),
    }


def run_analysis_same_samples(
    dataset_name: str,
    llm_type: str = "llama_cpp",
    model_name: str = "qwen2.5-coder:32b-instruct-q8_0",
    prompt_gen_type_1: str = "base",
    prompt_gen_type_2: str = "tuctn-all-info",
    setup: str = "multi_ebt",
):
    """Run analysis on samples that have pass-ratio == 1.0 in BOTH prompt types.

    Args:
        dataset_name: Name of the dataset to load metrics for.
        llm_type: LLM type (e.g., llama_cpp, azure).
        model_name: Model name.
        prompt_gen_type_1: First prompt generation type.
        prompt_gen_type_2: Second prompt generation type.
        setup: Experiment setup type.
    """
    # Load passing IDs for both prompt types
    passing_ids_1 = load_passing_ids(
        dataset_name, llm_type, model_name, prompt_gen_type_1, setup
    )
    logger.info(
        f"Found {len(passing_ids_1)} IDs with pass-ratio=1.0 for {prompt_gen_type_1}"
    )

    passing_ids_2 = load_passing_ids(
        dataset_name, llm_type, model_name, prompt_gen_type_2, setup
    )
    logger.info(
        f"Found {len(passing_ids_2)} IDs with pass-ratio=1.0 for {prompt_gen_type_2}"
    )

    # Find intersection - IDs that pass in BOTH prompt types
    common_passing_ids = passing_ids_1 & passing_ids_2
    logger.info(
        f"Found {len(common_passing_ids)} IDs with pass-ratio=1.0 in BOTH prompt types"
    )

    # Process each prompt type with the common passing IDs
    for prompt_gen_type in [prompt_gen_type_1, prompt_gen_type_2]:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing prompt type: {prompt_gen_type}")

        annotated_samples = load_samples(
            dataset_name, llm_type, model_name, prompt_gen_type, setup
        )
        if not annotated_samples:
            logger.error(f"No inspection results for {prompt_gen_type}")
            continue

        # Deduplicate md entries by data_id (keep last occurrence)
        md_by_id: dict[str, dict] = {}
        for sample in annotated_samples:
            md_by_id[sample["data_id"]] = sample

        # Cross-reference with common passing IDs only
        final_samples: list[dict] = []

        # IDs in md that don't exist in common passing IDs: throw out
        thrown_out_no_pass = []

        for data_id, sample in md_by_id.items():
            if data_id not in common_passing_ids:
                thrown_out_no_pass.append(data_id)
                continue
            final_samples.append(sample)

        # IDs in common passing IDs but NOT in md: default semantic_match=yes, categories=[]
        ids_in_md = set(md_by_id.keys())
        defaulted_ids = []
        for data_id in sorted(common_passing_ids):
            if data_id not in ids_in_md:
                final_samples.append({
                    "data_id": data_id,
                    "semantic_match": True,
                    "categories": [],
                })
                defaulted_ids.append(data_id)

        # Print warnings
        if thrown_out_no_pass:
            logger.warning(
                f"IDs in md but not in common passing IDs (thrown out): "
                f"{len(thrown_out_no_pass)} IDs"
            )
        if defaulted_ids:
            logger.warning(
                f"{prompt_gen_type}: {len(defaulted_ids)} of {len(common_passing_ids)} "
                f"shared IDs carry no annotation and were DEFAULTED to equivalent, "
                f"which counts them as not-false-positive without anyone having "
                f"looked: {', '.join(defaulted_ids[:10])}"
                + (" ..." if len(defaulted_ids) > 10 else "")
            )

        # Sort by data_id for consistency
        final_samples.sort(key=lambda s: int(s["data_id"].split("-")[1]))

        logger.info(f"Final sample count: {len(final_samples)}")

        # Write each sample to JSONL with same_samples prefix
        su.io.mkdir(QUALITATIVE_DIR)
        each_sample_path = (
            QUALITATIVE_DIR / f"same_samples_qual_each_sample_{prompt_gen_type}.jsonl"
        )
        su.io.dump(each_sample_path, final_samples)
        logger.info(f"Wrote samples to {each_sample_path}")

        # Compute and write summary
        summary = compute_summary(final_samples)
        # How much of the distribution rests on a default rather than on an
        # inspection. Kept in the summary so a reader of the numbers can see it
        # without re-running the analysis.
        summary["defaulted-count"] = len(defaulted_ids)
        summary["defaulted-ids"] = defaulted_ids
        summary["annotated-count"] = len(final_samples) - len(defaulted_ids)
        summary_path = QUALITATIVE_DIR / f"same_samples_qual_summary_{prompt_gen_type}.json"
        su.io.dump(summary_path, summary, fmt=su.io.fmts.jsonPretty)
        logger.info(f"Wrote summary to {summary_path}")

        # Print summary
        logger.info(f"Summary for {prompt_gen_type}:")
        logger.info(f"  Total samples: {summary['total-samples']}")
        logger.info(
            f"  Semantic match yes: {summary['semantic-match-yes']['count']} "
            f"({summary['semantic-match-yes']['percentage']}%)"
        )
        logger.info(
            f"  Semantic match no: {summary['semantic-match-no']['count']} "
            f"({summary['semantic-match-no']['percentage']}%)"
        )
        if summary["semantic-match-unknown"]["count"] > 0:
            logger.info(
                f"  Semantic match unknown: {summary['semantic-match-unknown']['count']} "
                f"({summary['semantic-match-unknown']['percentage']}%)"
            )
        if summary["category-counts"]:
            logger.info(f"  Categories among no-semantic-match:")
            for cat, info in summary["category-counts"].items():
                logger.info(f"    {cat}: {info['count']} ({info['percentage']}%)")


def compare_category(
    prompt_gen_type_1: str = "base",
    prompt_gen_type_2: str = "tuctn-all-info",
    category: str = "",
    use_same_samples: bool = True,
    show_semantic_match_diff: bool = False,
):
    """Find IDs that are NOT in a category in prompt1 but ARE in that category in prompt2.

    Args:
        prompt_gen_type_1: First prompt generation type.
        prompt_gen_type_2: Second prompt generation type.
        category: The category to compare. If empty, lists all available categories.
        use_same_samples: If True, use same_samples files; otherwise use regular qual files.
        show_semantic_match_diff: If True, show IDs that differ in semantic_match=False status.
    """
    prefix = "same_samples_" if use_same_samples else ""

    # Load samples for both prompts
    samples_path_1 = QUALITATIVE_DIR / f"{prefix}qual_each_sample_{prompt_gen_type_1}.jsonl"
    samples_path_2 = QUALITATIVE_DIR / f"{prefix}qual_each_sample_{prompt_gen_type_2}.jsonl"

    if not samples_path_1.exists():
        logger.error(f"Samples file not found: {samples_path_1}")
        return
    if not samples_path_2.exists():
        logger.error(f"Samples file not found: {samples_path_2}")
        return

    samples_1: list[dict] = su.io.load(samples_path_1)  # type: ignore
    samples_2: list[dict] = su.io.load(samples_path_2)  # type: ignore

    # Build dictionaries by data_id
    samples_by_id_1 = {s["data_id"]: s for s in samples_1}
    samples_by_id_2 = {s["data_id"]: s for s in samples_2}

    # Use only IDs present in both sample files
    common_ids = set(samples_by_id_1.keys()) & set(samples_by_id_2.keys())
    logger.info(f"Using {len(common_ids)} common IDs from both sample files")

    # Only consider samples with semantic_match=False (matches compute_summary behavior)
    # Categories are only counted for no-semantic-match samples in the summary
    no_sm_ids_1 = {
        data_id for data_id in common_ids
        if samples_by_id_1[data_id].get("semantic_match") is False
    }
    no_sm_ids_2 = {
        data_id for data_id in common_ids
        if samples_by_id_2[data_id].get("semantic_match") is False
    }
    logger.info(f"Samples with semantic_match=False: {len(no_sm_ids_1)} in {prompt_gen_type_1}, {len(no_sm_ids_2)} in {prompt_gen_type_2}")

    # Show semantic_match=False difference if requested
    if show_semantic_match_diff:
        # IDs with semantic_match=False in prompt2 but not in prompt1
        no_sm_only_in_2 = no_sm_ids_2 - no_sm_ids_1
        # IDs with semantic_match=False in prompt1 but not in prompt2
        no_sm_only_in_1 = no_sm_ids_1 - no_sm_ids_2
        # IDs with semantic_match=False in both
        no_sm_in_both = no_sm_ids_1 & no_sm_ids_2

        logger.info(f"\n{'='*60}")
        logger.info(f"Semantic match=False comparison:")
        logger.info(f"In both: {len(no_sm_in_both)} samples")

        logger.info(f"\n--- semantic_match=False in {prompt_gen_type_2} but NOT in {prompt_gen_type_1}: {len(no_sm_only_in_2)} ---")
        for data_id in sorted(no_sm_only_in_2, key=lambda x: int(x.split("-")[1])):
            sm_1 = samples_by_id_1.get(data_id, {}).get("semantic_match")
            cat_2 = samples_by_id_2.get(data_id, {}).get("categories", [])
            logger.info(f"  {data_id} (semantic_match in {prompt_gen_type_1}: {sm_1}, categories in {prompt_gen_type_2}: {cat_2})")

        logger.info(f"\n--- semantic_match=False in {prompt_gen_type_1} but NOT in {prompt_gen_type_2}: {len(no_sm_only_in_1)} ---")
        for data_id in sorted(no_sm_only_in_1, key=lambda x: int(x.split("-")[1])):
            sm_2 = samples_by_id_2.get(data_id, {}).get("semantic_match")
            cat_1 = samples_by_id_1.get(data_id, {}).get("categories", [])
            logger.info(f"  {data_id} (semantic_match in {prompt_gen_type_2}: {sm_2}, categories in {prompt_gen_type_1}: {cat_1})")

        if not category:
            return {
                "no_sm_only_in_prompt1": sorted(no_sm_only_in_1, key=lambda x: int(x.split("-")[1])),
                "no_sm_only_in_prompt2": sorted(no_sm_only_in_2, key=lambda x: int(x.split("-")[1])),
                "no_sm_in_both": sorted(no_sm_in_both, key=lambda x: int(x.split("-")[1])),
            }

    # Collect all categories from no-semantic-match samples with common IDs
    all_categories: set[str] = set()
    for data_id in common_ids:
        if data_id in no_sm_ids_1:
            all_categories.update(samples_by_id_1[data_id].get("categories", []))
        if data_id in no_sm_ids_2:
            all_categories.update(samples_by_id_2[data_id].get("categories", []))

    if not category:
        logger.info(f"Available categories: {sorted(all_categories)}")
        return

    # Find IDs in category (only among no-semantic-match samples)
    ids_in_cat_1 = {
        data_id for data_id in no_sm_ids_1
        if category in samples_by_id_1[data_id].get("categories", [])
    }
    ids_in_cat_2 = {
        data_id for data_id in no_sm_ids_2
        if category in samples_by_id_2[data_id].get("categories", [])
    }

    # IDs in category in prompt2 but NOT in category in prompt1
    ids_only_in_2 = ids_in_cat_2 - ids_in_cat_1
    # IDs in category in prompt1 but NOT in category in prompt2
    ids_only_in_1 = ids_in_cat_1 - ids_in_cat_2
    # IDs in category in both
    ids_in_both = ids_in_cat_1 & ids_in_cat_2

    logger.info(f"\nCategory: {category}")
    logger.info(f"{'='*60}")
    logger.info(f"In {prompt_gen_type_1}: {len(ids_in_cat_1)} samples")
    logger.info(f"In {prompt_gen_type_2}: {len(ids_in_cat_2)} samples")
    logger.info(f"In both: {len(ids_in_both)} samples")

    logger.info(f"\n--- In '{category}' in {prompt_gen_type_2} but NOT in {prompt_gen_type_1}: {len(ids_only_in_2)} ---")
    for data_id in sorted(ids_only_in_2, key=lambda x: int(x.split("-")[1])):
        cat_1 = samples_by_id_1.get(data_id, {}).get("categories", [])
        logger.info(f"  {data_id} (categories in {prompt_gen_type_1}: {cat_1})")

    logger.info(f"\n--- In '{category}' in {prompt_gen_type_1} but NOT in {prompt_gen_type_2}: {len(ids_only_in_1)} ---")
    for data_id in sorted(ids_only_in_1, key=lambda x: int(x.split("-")[1])):
        cat_2 = samples_by_id_2.get(data_id, {}).get("categories", [])
        logger.info(f"  {data_id} (categories in {prompt_gen_type_2}: {cat_2})")

    return {
        "category": category,
        "ids_only_in_prompt1": sorted(ids_only_in_1, key=lambda x: int(x.split("-")[1])),
        "ids_only_in_prompt2": sorted(ids_only_in_2, key=lambda x: int(x.split("-")[1])),
        "ids_in_both": sorted(ids_in_both, key=lambda x: int(x.split("-")[1])),
    }


if __name__ == "__main__":
    su.log.setup(ExlongMacros.log_file)
    CLI(
        [
            run_analysis,
            run_agreement,
            find_missing_ids,
            run_analysis_same_samples,
            compare_category,
        ],
        as_positional=False,
    )
