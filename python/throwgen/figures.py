import glob
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import seutil as su
from etestgen.macros import Macros
from jsonargparse import CLI

from throwgen.dataset.multi_ebt_data import MultiEBTDataset
from throwgen.eval.eval_set import load_eval_ids
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.utils.code import cyclomatic_complexity

logger = su.log.get_logger(__name__, su.log.INFO)

import matplotlib.pyplot as plt
from matplotlib_venn import venn2, venn3
import numpy as np
import pandas as pd

# Embed TrueType rather than matplotlib's default Type 3 fonts.  IEEE PDF
# eXpress rejects Type 3, so without this every regenerated figure has to be
# fixed by hand before the paper can be submitted.
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["ps.fonttype"] = 42

PROMPT2LABEL = {
    "tuctn-all-info": "ExCoder",
    "base": "Base",
}

# RQ3 complexity measures: (macro prefix, record key, bin width, open-bin
# start, x ticks, x label, output file). Methods at or above the open-bin
# start fall into one open-ended "N+" bin; this single config drives both
# the plots and the macros cited in the prose.
COMPLEXITY_MEASURES = [
    ("Loc", "loc", 3, 15, [5, 10], "Method length (by # of lines)", "success_vs_len.pdf"),
    ("Cc", "complexity", 1, 5, [1, 2, 3, 4], "Cyclomatic complexity", "success_vs_cc.pdf"),
]


def process_experiment(records, metric, bin_size, cap):
    # Convert to DataFrame
    df = pd.DataFrame(records)

    # Equal-width bins aligned to end at cap, plus one open-ended cap+ bin
    start = cap
    while start > df[metric].min():
        start -= bin_size
    bins = range(start, cap + 1, bin_size)

    # Assign each record below the cap to a bin
    closed = df[df[metric] < cap]
    open_bin = df[df[metric] >= cap]

    # Calculate success rate of both prompts for each bin
    rates = closed.groupby(
        pd.cut(closed[metric], bins=bins, right=False, include_lowest=True),
        observed=False,
    ).agg({"success_a": ["mean", "count"], "success_b": "mean"})

    # Get bin centers for plotting; the open cap+ bin sits a fixed fraction of
    # the closed-bin span past the last closed bin, so both panels show the
    # same visual gap regardless of their bin width
    if bin_size == 1:
        bin_centers = [interval.left for interval in rates.index]
    else:
        bin_centers = [interval.mid for interval in rates.index]
    bin_centers.append(bin_centers[-1] + 0.5 * (bin_centers[-1] - bin_centers[0]))
    success_a = list(rates[("success_a", "mean")].values * 100)
    success_a.append(open_bin["success_a"].mean() * 100)
    success_b = list(rates[("success_b", "mean")].values * 100)
    success_b.append(open_bin["success_b"].mean() * 100)
    counts = list(rates[("success_a", "count")].values)
    counts.append(len(open_bin))

    return bin_centers, success_a, success_b, counts


def plot_success_vs_complexity(records, exp_a_label, exp_b_label):
    """
    Plot success rate vs method length and cyclomatic complexity with
    equal-width bins and one open-ended bin for the long tail, overlaid on a
    histogram of sample counts. One figure per measure, combined as subfigures
    in the paper.
    """
    fontsize = 14
    for _, metric, bin_size, cap, ticks, xlabel, filename in COMPLEXITY_MEASURES:
        bin_centers, success_a, success_b, counts = process_experiment(
            records, metric, bin_size, cap
        )
        fig, ax1 = plt.subplots(figsize=(6, 6))

        # Secondary y-axis for histogram (plot first so it's behind)
        ax2 = ax1.twinx()
        bar_width = bin_size * 0.4
        ax2.bar(bin_centers, counts, width=bar_width, alpha=0.3, color='gray', label='# of methods')
        ax2.set_ylabel("# of methods", fontsize=fontsize)
        ax2.set_ylim(0, max(counts) * 2.5)  # Leave room for line plot
        ax2.tick_params(axis='y', labelsize=fontsize)

        # Primary y-axis for success rate lines
        ax1.plot(bin_centers, success_a, marker="o", linewidth=2, label=exp_a_label, alpha=0.8, zorder=3)
        ax1.plot(bin_centers, success_b, marker="s", linewidth=2, label=exp_b_label, alpha=0.8, zorder=3)

        ax1.set_xlabel(xlabel, fontsize=fontsize)
        ax1.set_ylabel("pass@5 (All User)", fontsize=fontsize)
        ax1.set_ylim(0, 100)
        ax1.set_xticks(ticks + [bin_centers[-1]])
        ax1.set_xticklabels([str(t) for t in ticks] + [f"{cap}+"])
        ax1.tick_params(axis='both', labelsize=fontsize)
        ax1.grid(True, alpha=0.3)

        # Combine legends from both axes, place at bottom
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=3, fontsize=fontsize)

        # Set consistent plot area size (matches plot_repair_comparison)
        fig.subplots_adjust(left=0.15, right=0.85, bottom=0.25, top=0.95)
        plt.savefig(ThrowgenMacros.paper_dir / "figures" / filename)


def make_success_vs_complexity_plot(
    dataset_name: str,
    prompt_gen_a: str,
    prompt_gen_b: str,
    llm_type: str,
    model_name: str,
    setup: str,
):
    """Generate the RQ3 figure and its numbers, keyed on the method given to the LLM.

    Both measures describe ``mut_no_throw``, the ERC-removed method that is the
    task input, so removing the developer's ERC can lower them relative to the
    original implementation.
    """

    def load(prompt_gen_type: str) -> dict[str, float]:
        rows: list[dict[str, Any]] = su.io.load(
            ThrowgenMacros.metrics_dir
            / dataset_name
            / f"run-all-pass-at-k-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-each-sample.jsonl"
        )  # type: ignore
        return {r["id"]: r["pass-at-5"] for r in rows}

    pass_at_k_a = load(prompt_gen_a)
    pass_at_k_b = load(prompt_gen_b)
    dataset = MultiEBTDataset.from_saved(ThrowgenMacros.mebt_data_dir / dataset_name)
    # Pair on methods that both prompts have a retained runtime result for; the
    # runtime evaluator drops a project when project-level evaluation fails.
    paired_ids = pass_at_k_a.keys() & pass_at_k_b.keys()
    records = [
        {
            "loc": len(data.mut_no_throw.splitlines()),
            "complexity": cyclomatic_complexity(data.mut_no_throw),
            "success_a": pass_at_k_a[data.id],
            "success_b": pass_at_k_b[data.id],
        }
        for data in dataset
        if data.id in paired_ids
    ]
    logger.info(f"Paired {len(records)} of {len(dataset)} methods for RQ3")

    plot_success_vs_complexity(
        records,
        PROMPT2LABEL[prompt_gen_a],
        PROMPT2LABEL[prompt_gen_b],
    )

    latex_file = su.latex.File(
        ThrowgenMacros.paper_dir
        / "tables"
        / dataset_name
        / "numbers"
        / f"numbers-complexity-{setup}.tex",
        is_append=False,
    )
    for prefix, metric, bin_size, cap, _, _, _ in COMPLEXITY_MEASURES:
        values = [r[metric] for r in records]
        open_percent = sum(v >= cap for v in values) / len(values) * 100
        name = f"Complexity{prefix}"
        latex_file.append_macro(su.latex.Macro(f"{name}Max", f"{max(values)}\\xspace"))
        latex_file.append_macro(su.latex.Macro(f"{name}ClosedMax", f"{cap - 1}\\xspace"))
        latex_file.append_macro(su.latex.Macro(f"{name}OpenMin", f"{cap}\\xspace"))
        latex_file.append_macro(su.latex.Macro(f"{name}OpenLabel", f"{cap}+\\xspace"))
        latex_file.append_macro(
            su.latex.Macro(f"{name}OpenPercent", f"{open_percent:.1f}\\%\\xspace")
        )

        # Per-bin gaps, so the prose describing the panel is generated rather
        # than typed in and reread by hand whenever the evaluation is re-run.
        centers, success_a, success_b, counts = process_experiment(
            records, metric, bin_size, cap
        )
        bin_labels = [
            f"{cap}+" if i == len(centers) - 1
            else str(int(c)) if bin_size == 1
            else f"{int(c - bin_size / 2)} to {int(c + bin_size / 2) - 1}"
            for i, c in enumerate(centers)
        ]
        gaps = [a - b for a, b in zip(success_a, success_b)]
        best = max(range(len(gaps)), key=lambda i: gaps[i])
        worst = min(range(len(gaps)), key=lambda i: gaps[i])
        behind = [i for i, g in enumerate(gaps) if g < 0]
        tied = [i for i, g in enumerate(gaps) if abs(g) < 1e-9]
        latex_file.append_macro(
            su.latex.Macro(f"{name}BestGapLabel", f"{bin_labels[best]}\\xspace")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{name}BestGapValue", f"{gaps[best]:.1f}\\xspace")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{name}OpenGapValue", f"{gaps[-1]:.1f}\\xspace")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{name}WorstGapLabel", f"{bin_labels[worst]}\\xspace")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{name}WorstGapValue", f"{abs(gaps[worst]):.1f}\\xspace")
        )
        # The closed bins other than the first: the middle of the range, where
        # the gap is widest and which the prose contrasts with the two ends.
        if len(centers) > 2:
            mid_lo = int(centers[1] - bin_size / 2)
            mid_hi = cap - 1
            latex_file.append_macro(
                su.latex.Macro(
                    f"{name}MidRangeLabel",
                    (f"{mid_lo} to {mid_hi}" if mid_lo != mid_hi else str(mid_lo)) + "\\xspace",
                )
            )
        latex_file.append_macro(
            su.latex.Macro(f"{name}BehindBinCount", f"{len(behind)}\\xspace")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{name}TiedBinCount", f"{len(tied)}\\xspace")
        )
        latex_file.append_macro(
            su.latex.Macro(
                f"{name}WorstGapBinSize", f"{counts[worst]}\\xspace"
            )
        )
        if tied:
            latex_file.append_macro(
                su.latex.Macro(f"{name}TiedGapLabel", f"{bin_labels[tied[0]]}\\xspace")
            )
            latex_file.append_macro(
                su.latex.Macro(
                    f"{name}TiedGapBinSize", f"{counts[tied[0]]}\\xspace"
                )
            )
    latex_file.save()
    logger.info(f"Wrote complexity numbers to {latex_file.path}")


def plot_repair_comparison(
    iterations_a: list[float],
    iterations_b: list[float],
    label_a: str,
    label_b: str,
    metric_name: str,
    output_path: Path,
):
    """
    Plot pass@k metric across repair iterations for two prompts.

    Args:
        iterations_a, iterations_b: List of metric values for each iteration (index 0 = initial)
        label_a, label_b: Labels for the two prompts
        metric_name: Name of the metric for y-axis label
        output_path: Path to save the figure
    """
    fig, ax = plt.subplots(figsize=(6, 6))
    fontsize = 14

    x_a = list(range(len(iterations_a)))
    x_b = list(range(len(iterations_b)))

    # Convert to percentage
    y_a = [v * 100 for v in iterations_a]
    y_b = [v * 100 for v in iterations_b]

    ax.plot(x_a, y_a, marker="o", linewidth=2, label=label_a, alpha=0.8)
    ax.plot(x_b, y_b, marker="s", linewidth=2, label=label_b, alpha=0.8)

    ax.set_xlabel("Repair Iteration", fontsize=fontsize)
    ax.set_ylabel(metric_name, fontsize=fontsize)
    ax.set_xticks(range(max(len(iterations_a), len(iterations_b))))
    ax.tick_params(axis='both', labelsize=fontsize)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize=fontsize)
    ax.grid(True, alpha=0.3)

    # Set y-axis to show relevant range
    all_values = y_a + y_b
    y_min = max(0, min(all_values) - 5)
    y_max = min(100, max(all_values) + 5)
    ax.set_ylim(y_min, y_max)

    # Set consistent plot area size (matches plot_success_vs_complexity)
    fig.subplots_adjust(left=0.15, right=0.85, bottom=0.25, top=0.95)
    plt.savefig(output_path)
    logger.info(f"Saved repair comparison plot to {output_path}")


def make_repair_comparison_plot(
    dataset_name: str,
    prompt_gen_a: str,
    prompt_gen_b: str,
    llm_type: str,
    model_name: str,
    max_iterations: int = 5,
    metrics_type: str = "run-ebts",
    pass_at_k: int = 5,
):
    """
    Plot comparison of repair experiment results at each iteration.

    Args:
        dataset_name: Name of the dataset
        prompt_gen_a: First repair prompt (e.g., "base-repair")
        prompt_gen_b: Second repair prompt (e.g., "tuctn-all-info-repair")
        llm_type: LLM type (e.g., "llama_cpp")
        model_name: Model name (e.g., "qwen2.5-coder:32b-instruct-q8_0")
        max_iterations: Maximum number of repair iterations to check
        metrics_type: Type of metrics ("run-ebts" or "run-all")
        pass_at_k: Which pass@k metric to use (e.g., 5 for pass@5)
    """
    metric_key = f"pass-at-{pass_at_k}"

    def load_iterations(repair_prompt: str) -> list[float]:
        """Load metrics for each iteration of a repair prompt."""
        # Extract base prompt name (e.g., "base" from "base-repair")
        base_prompt = repair_prompt.replace("-repair", "")
        results = []

        # Load initial (multi_ebt) result
        initial_path = (
            ThrowgenMacros.metrics_dir
            / dataset_name
            / f"{metrics_type}-pass-at-k-{llm_type}-{model_name}-{base_prompt}-multi_ebt-summary.json"
        )
        initial_data = su.io.load(initial_path)
        results.append(initial_data[metric_key])
        logger.info(f"Loaded initial result from {initial_path}")

        # Load repair iterations
        for k in range(1, max_iterations + 1):
            repair_path = (
                ThrowgenMacros.metrics_dir
                / dataset_name
                / f"{metrics_type}-pass-at-k-{llm_type}-{model_name}-{repair_prompt}@{k}-repair-summary.json"
            )
            repair_data = su.io.load(repair_path)
            results.append(repair_data[metric_key])
            logger.info(f"Loaded repair@{k} result from {repair_path}")

        return results

    # Load iterations for both prompts
    iterations_a = load_iterations(prompt_gen_a)
    iterations_b = load_iterations(prompt_gen_b)

    if not iterations_a or not iterations_b:
        logger.error("Failed to load iterations for one or both prompts")
        return

    # Create labels
    label_a = "Iter-" + PROMPT2LABEL.get(prompt_gen_a.replace("-repair", ""), prompt_gen_a)
    label_b = "Iter-" + PROMPT2LABEL.get(prompt_gen_b.replace("-repair", ""), prompt_gen_b)

    # Output path
    output_path = (
        ThrowgenMacros.paper_dir
        / "figures"
        / f"repair_comparison_{prompt_gen_a}_vs_{prompt_gen_b}-pass-at-{pass_at_k}.pdf"
    )

    plot_repair_comparison(
        iterations_a,
        iterations_b,
        label_a,
        label_b,
        f"pass@{pass_at_k} (All User)",
        output_path,
    )


def get_passing_ids(results: list[dict[str, Any]]) -> set[str]:
    """
    Get IDs of datapoints that have at least one sample with pass-ratio of 1.0.

    Args:
        results: List of result dicts, each with 'id' and 'result' fields.

    Returns:
        Set of IDs where at least one sample has pass-ratio == 1.0.
    """
    passing_ids = set()
    for r in results:
        data_id = r["id"]
        samples = r.get("result", [])
        for sample in samples:
            summary = sample.get("summary", {})
            if summary.get("pass-ratio") == 1.0:
                passing_ids.add(data_id)
                break
    return passing_ids


def plot_result_venn(
    set_a: set[str],
    set_b: set[str],
    total_ids: set[str],
    label_a: str,
    label_b: str,
    output_path: Path,
):
    """
    Plot a Venn diagram showing overlap between two sets of passing datapoints.

    Args:
        set_a: Set of IDs passing for prompt A.
        set_b: Set of IDs passing for prompt B.
        total_ids: Set of all IDs in the dataset.
        label_a: Label for prompt A.
        label_b: Label for prompt B.
        output_path: Path to save the figure.
    """
    from matplotlib.patches import Rectangle, Patch

    fig, ax = plt.subplots(figsize=(8, 6))
    fontsize = 19
    number_fontsize = 19

    # Create Venn diagram for A and B first to get bounds
    v = venn2([set_a, set_b], set_labels=("", ""), ax=ax)

    # Style the subset labels (numbers)
    for text in v.subset_labels:
        if text:
            text.set_fontsize(number_fontsize)

    # Calculate counts
    only_a = len(set_a - set_b)
    only_b = len(set_b - set_a)
    both = len(set_a & set_b)
    neither = len(total_ids - (set_a | set_b))

    # Draw the "All" rectangle as background
    all_color = "#E0E0E0"
    margin = 0.4
    rect_x = -0.25 - margin
    rect_y = -0.25 - margin
    rect_w = 0.5 + 2 * margin
    rect_h = 0.5 + 2 * margin
    rect = Rectangle(
        (rect_x, rect_y), rect_w, rect_h,
        facecolor=all_color, edgecolor="black", linewidth=1.5,
        zorder=0,
    )
    ax.add_patch(rect)

    # Add "neither" count in the bottom-left corner inside the rectangle
    ax.text(rect_x + 0.08, rect_y + 0.08, str(neither), fontsize=number_fontsize, ha="left", va="bottom")

    # Set axis limits to show the full rectangle
    ax.set_xlim(rect_x - 0.1, rect_x + rect_w + 0.1)
    ax.set_ylim(rect_y - 0.1, rect_y + rect_h + 0.1)

    # Build legend
    legend_patches = []
    legend_labels = []
    if v.get_patch_by_id("10"):
        legend_patches.append(v.get_patch_by_id("10"))
        legend_labels.append(label_a)
    if v.get_patch_by_id("01"):
        legend_patches.append(v.get_patch_by_id("01"))
        legend_labels.append(label_b)
    legend_patches.append(Patch(facecolor=all_color, edgecolor="black", linewidth=1.5))
    legend_labels.append("All")

    ax.legend(
        legend_patches, legend_labels,
        loc="upper left", bbox_to_anchor=(0.75, 1),
        fontsize=fontsize, frameon=True,
    )

    ax.set_aspect("equal")
    ax.axis("off")

    plt.savefig(output_path, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    logger.info(f"Saved Venn diagram to {output_path}")
    logger.info(f"  {label_a} only: {only_a}, {label_b} only: {only_b}, Both: {both}, Neither: {neither}")

    # Print IDs unique to each set
    only_a_ids = sorted(set_a - set_b)
    only_b_ids = sorted(set_b - set_a)
    logger.info(f"  IDs only in {label_a}: {only_a_ids}")
    logger.info(f"  IDs only in {label_b}: {only_b_ids}")


def get_semantic_match_ids(results: list[dict[str, Any]]) -> set[str]:
    """
    Get IDs of datapoints that have semantic_match == True.

    Args:
        results: List of result dicts, each with 'data_id' and 'semantic_match' fields.

    Returns:
        Set of data_ids where semantic_match is True.
    """
    return {r["data_id"] for r in results if r.get("semantic_match", False)}


def make_qualitative_venn(
    prompt_a: str,
    prompt_b: str,
    output_filename: str | None = None,
    dataset_name: str | None = None,
    llm_type: str | None = None,
    model_name: str | None = None,
    setup: str = "multi_ebt",
    metrics_type: str = "run-all",
):
    """
    Create a Venn diagram showing overlap of semantic matches between two prompts
    from qualitative analysis data.

    Args:
        prompt_a: First prompt name (e.g., "base").
        prompt_b: Second prompt name (e.g., "tuctn-all-info").
        output_filename: Optional custom output filename. If None, uses default naming.
        dataset_name: If given (with llm_type and model_name), the enclosing box
            spans every \tarmethod in the evaluation set rather than only those
            that were inspected, so this figure shares its total with the
            passing-tests Venn diagram.
        llm_type: LLM type used for the run whose metrics define the total.
        model_name: Model name used for the run whose metrics define the total.
        setup: Experiment setup for that run.
        metrics_type: Metrics type for that run.
    """
    qual_dir = Macros.work_dir / "results" / "qualitative"

    # Load qualitative results for both prompts
    results_a: list[dict[str, Any]] = su.io.load(
        qual_dir / f"qual_each_sample_{prompt_a}.jsonl"
    )  # type: ignore
    results_b: list[dict[str, Any]] = su.io.load(
        qual_dir / f"qual_each_sample_{prompt_b}.jsonl"
    )  # type: ignore

    # Get all IDs from both results (union in case they differ)
    total_ids = {r["data_id"] for r in results_a} | {r["data_id"] for r in results_b}

    # Optionally widen the total to the full evaluation set, so that the
    # enclosing box matches the one in the passing-tests Venn diagram.
    if dataset_name is not None:
        eval_ids = set(load_eval_ids(dataset_name))
        missing = total_ids - eval_ids
        if missing:
            raise ValueError(
                f"{len(missing)} inspected data_ids are not in the evaluation set: "
                f"{sorted(missing)[:5]}"
            )
        total_ids = eval_ids

    # Get semantic match IDs for each prompt
    match_a = get_semantic_match_ids(results_a)
    match_b = get_semantic_match_ids(results_b)

    logger.info(f"Total datapoints: {len(total_ids)}")
    logger.info(f"Prompt A ({prompt_a}): {len(match_a)} semantic matches")
    logger.info(f"Prompt B ({prompt_b}): {len(match_b)} semantic matches")

    # Get labels
    label_a = PROMPT2LABEL.get(prompt_a, prompt_a)
    label_b = PROMPT2LABEL.get(prompt_b, prompt_b)

    # Output path
    if output_filename is None:
        output_filename = f"venn_qualitative_{prompt_a}_vs_{prompt_b}.pdf"
    output_path = ThrowgenMacros.paper_dir / "figures" / output_filename

    plot_result_venn(match_a, match_b, total_ids, label_a, label_b, output_path)


def make_result_venn(
    dataset_name: str,
    prompt_gen_a: str,
    prompt_gen_b: str,
    llm_type: str,
    model_name: str,
    setup: str,
    metrics_type: str = "run-all",
):
    """
    Create a Venn diagram showing overlap of passing datapoints between two prompts.

    A datapoint is considered "passing" if it has at least one sample with pass-ratio of 1.0.

    Args:
        dataset_name: Name of the dataset.
        prompt_gen_a: First prompt generation type.
        prompt_gen_b: Second prompt generation type.
        llm_type: LLM type (e.g., "ollama", "vllm").
        model_name: Model name.
        setup: Experiment setup (e.g., "multi_ebt").
        metrics_type: Type of metrics file to load (e.g., "run-all", "run-ebts").
    """
    # Load results for both prompts
    results_a: list[dict[str, Any]] = su.io.load(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"{metrics_type}-{llm_type}-{model_name}-{prompt_gen_a}-{setup}-each-sample.jsonl"
    )  # type: ignore
    results_b: list[dict[str, Any]] = su.io.load(
        ThrowgenMacros.metrics_dir
        / dataset_name
        / f"{metrics_type}-{llm_type}-{model_name}-{prompt_gen_b}-{setup}-each-sample.jsonl"
    )  # type: ignore

    # The dataset, not the metrics, defines the total: a \tarmethod whose
    # project failed to build has no metrics row but is still a failure.
    total_ids = set(load_eval_ids(dataset_name))

    # Get passing IDs for each prompt
    passing_a = get_passing_ids(results_a)
    passing_b = get_passing_ids(results_b)

    logger.info(f"Total datapoints: {len(total_ids)}")
    logger.info(f"Prompt A ({prompt_gen_a}): {len(passing_a)} passing datapoints")
    logger.info(f"Prompt B ({prompt_gen_b}): {len(passing_b)} passing datapoints")

    # Get labels
    label_a = PROMPT2LABEL.get(prompt_gen_a, prompt_gen_a)
    label_b = PROMPT2LABEL.get(prompt_gen_b, prompt_gen_b)

    # Output path
    output_path = (
        ThrowgenMacros.paper_dir
        / "figures"
        / f"venn_{prompt_gen_a}_vs_{prompt_gen_b}-{metrics_type}.pdf"
    )

    plot_result_venn(passing_a, passing_b, total_ids, label_a, label_b, output_path)


class FiguresCLI:
    """CLI for generating figures."""

    def success_vs_complexity(
        self,
        dataset_name: str,
        prompt_gen_a: str,
        prompt_gen_b: str,
        llm_type: str,
        model_name: str,
        setup: str,
    ):
        """Generate success vs length and cyclomatic complexity plot."""
        make_success_vs_complexity_plot(
            dataset_name=dataset_name,
            prompt_gen_a=prompt_gen_a,
            prompt_gen_b=prompt_gen_b,
            llm_type=llm_type,
            model_name=model_name,
            setup=setup,
        )

    def repair_comparison(
        self,
        dataset_name: str,
        prompt_gen_a: str,
        prompt_gen_b: str,
        llm_type: str,
        model_name: str,
        max_iterations: int,
        metrics_type: str,
        pass_at_k: int,
    ):
        """Generate repair comparison plot."""
        make_repair_comparison_plot(
            dataset_name=dataset_name,
            prompt_gen_a=prompt_gen_a,
            prompt_gen_b=prompt_gen_b,
            llm_type=llm_type,
            model_name=model_name,
            max_iterations=max_iterations,
            metrics_type=metrics_type,
            pass_at_k=pass_at_k,
        )

    def result_venn(
        self,
        dataset_name: str,
        prompt_gen_a: str,
        prompt_gen_b: str,
        llm_type: str,
        model_name: str,
        metrics_type: str,
    ):
        """Generate Venn diagram showing overlap of passing datapoints between two prompts."""
        make_result_venn(
            dataset_name=dataset_name,
            prompt_gen_a=prompt_gen_a,
            prompt_gen_b=prompt_gen_b,
            llm_type=llm_type,
            model_name=model_name,
            setup="multi_ebt",
            metrics_type=metrics_type,
        )

    def qualitative_venn(
        self,
        prompt_a: str,
        prompt_b: str,
        output_filename: str | None = None,
        dataset_name: str | None = None,
        llm_type: str | None = None,
        model_name: str | None = None,
        metrics_type: str = "run-all",
    ):
        """Generate Venn diagram showing overlap of semantic matches from qualitative analysis."""
        make_qualitative_venn(
            prompt_a=prompt_a,
            prompt_b=prompt_b,
            output_filename=output_filename,
            dataset_name=dataset_name,
            llm_type=llm_type,
            model_name=model_name,
            setup="multi_ebt",
            metrics_type=metrics_type,
        )


if __name__ == "__main__":
    CLI(FiguresCLI, as_positional=False)
