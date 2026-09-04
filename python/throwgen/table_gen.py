import glob
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import seutil as su
from etestgen.macros import Macros
from jsonargparse import CLI

from throwgen.eval.eval_set import load_eval_ids
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__, su.log.INFO)


class TableGen:
    # The rows of the ablation table, in the order they are printed.  The
    # leave-one-out variants the prompt registry also defines are deliberately
    # absent: the paper's ablation adds one component at a time.
    PROMPT_GEN_TYPES = [
        "tuctn-all-info",
        "only-avsym",
        "only-lcov",
        "only-nebt",
        "only-threxc",
        "cmtu",
        "base",
    ]
    MODEL_COMP_PROMPT_GEN_TYPES = [
        "base",
        "tuctn-all-info",
    ]
    REPAIR_COMP_PROMPT_GEN_TYPES = [
        "base-repair", "tuctn-all-info-repair",
    ]
    MAX_REPAIR_COMP_ITERATION = 4
    SELECTED_LLM_TYPES = [
        ("llama_cpp", "llama3.1:8b-instruct-q8_0"),
        ("llama_cpp", "phi4:14b-q8_0"),
        ("llama_cpp", "qwen2.5-coder:7b-instruct-q8_0"),
        ("llama_cpp", "qwen2.5-coder:32b-instruct-q8_0"),
        ("azure", "gpt-5-mini"),
    ]
    PROMPT_COMP_LLM_TYPES = ("llama_cpp", "qwen2.5-coder:32b-instruct-q8_0")

    IMPROVEMENT_MODELS = [
        (("llama_cpp", "qwen2.5-coder:32b-instruct-q8_0"), "QwenLarge"),
        (("azure", "gpt-5-mini"), "GPT"),
    ]
    REPAIR_IMPROVEMENT_MODELS = [
        (("llama_cpp", "qwen2.5-coder:32b-instruct-q8_0"), "QwenLarge"),
    ]

    EVAL_TYPES = [
        "run-ebts-pass-at-k",
        "run-all-pass-at-k",
        "run-all-with-tools-pass-at-k",
    ]
    RUN_METRICS_TYPES_DICT = {
        "compiled-at-k": [
            "run-ebts-pass-at-k-compiled-at-1",
            "run-ebts-pass-at-k-compiled-at-5",
            "run-ebts-pass-at-k-compiled-at-10",
        ],
        "ebts-pass-at-k": [
            "run-ebts-pass-at-k-pass-at-1",
            "run-ebts-pass-at-k-pass-at-5",
            "run-ebts-pass-at-k-pass-at-10",
        ],
        "all-pass-at-k": [
            "run-all-pass-at-k-pass-at-1",
            "run-all-pass-at-k-pass-at-5",
            "run-all-pass-at-k-pass-at-10",
        ],
        "allntools-pass-at-k": [
            "run-all-with-tools-pass-at-k-pass-at-1",
            "run-all-with-tools-pass-at-k-pass-at-5",
            "run-all-with-tools-pass-at-k-pass-at-10",
        ],
    }
    RUN_METRICS_TYPES = [m for v in RUN_METRICS_TYPES_DICT.values() for m in v]
    THROW_COUNT_TYPES = [
        "catch-throw",
        "if-throw",
        "switch-throw",
        "rest-throw",
        "total-throw",
    ]
    REMOVE_COMPILE_FAIL_TYPES = [
        "incompatible-types",
        "missing-return",
        "unreported-exception",
        "missing-return-only",
        "total-rm-comp-fail",
    ]
    STATS_TYPES = [
        "num-projects",
        "num-methods",
        "etest-sum",
        "exception-type",
    ]
    # Extra stats numbers emitted as LaTeX macros but NOT rendered as columns
    # in the stats table. Referenced inline in the dataset paragraph.
    EXTRA_STATS_TYPES = [
        "randoop-tests-sum",
        "randoop-tests-avg",
        "evosuite-tests-sum",
        "evosuite-tests-avg",
        "tool-tests-sum",
        "tool-tests-avg",
        "only-throw-mut",
        "empty-no-throw",
    ]
    # The four categories of the current taxonomy, spelled as the annotation
    # stores spell them. `annotation_store.FALSE_POSITIVE_CATEGORIES` is the
    # same list; keep the two in step.
    QUALITATIVE_CATEGORIES = [
        "too-lenient",
        "too-strict",
        "wrong-exception-handling",
        "code-destroyed",
    ]

    # Two of the four read badly as macro names, so the paper uses a shorter
    # spelling. The store's spelling stays the key everywhere else.
    QUALITATIVE_CATEGORY_MACRO = {
        "wrong-exception-handling": "wrong-handling",
        "code-destroyed": "destroyed-code",
    }
    # Columns for qualitative table: total, semantic match, then categories
    QUALITATIVE_COLUMNS = [
        # "total-samples",
        # "semantic-match-yes",
        "semantic-match-no",
    ] + QUALITATIVE_CATEGORIES

    def __init__(self, dataset_name: str):
        self._dataset_name: str = dataset_name
        self._tables_dir: Path = ThrowgenMacros.paper_dir / "tables" / dataset_name
        self._tables_dir.mkdir(parents=True, exist_ok=True)
        self._metrics_dir: Path = ThrowgenMacros.metrics_dir / dataset_name
        self._dataset_dir: Path = ThrowgenMacros.mebt_data_dir / dataset_name

    @staticmethod
    def _infer_fmt(value: Any, float_precision: int = 2):
        if isinstance(value, int):
            return ",d"
        else:
            return f",.{float_precision}f"

    def make_stats_numbers(self):
        logger.info(f"Making stats numbers of {self._dataset_name}")
        latex_file = su.latex.File(
            self._tables_dir
            / "numbers"
            / f"numbers-{self._dataset_name}-stats-stable.tex",
            is_append=False,
        )
        dataset_stats: dict[str, Any] = su.io.load(
            self._dataset_dir / "dataset_stats.json"
        )  # type: ignore
        all_keys = self.STATS_TYPES + self.EXTRA_STATS_TYPES
        if os.path.exists(self._dataset_dir / "throw-count.json"):
            dataset_stats.update(su.io.load(self._dataset_dir / "throw-count.json"))  # type: ignore
            all_keys += self.THROW_COUNT_TYPES

        if os.path.exists(self._dataset_dir / "removed-compile-fail.json"):
            dataset_stats.update(
                su.io.load(self._dataset_dir / "removed-compile-fail.json")  # type: ignore
            )
            all_keys += self.REMOVE_COMPILE_FAIL_TYPES

        for stats_key in all_keys:
            if stats_key not in dataset_stats:
                # intermediate filtering datasets lack tool-test stats
                logger.warning(f"Stat missing, skipping: {stats_key}")
                continue
            fmt = self._infer_fmt(dataset_stats[stats_key])
            latex_file.append_macro(
                su.latex.Macro(
                    f"stat-{stats_key}-{self._dataset_name}",
                    f"{dataset_stats[stats_key]:{fmt}}",
                )
            )

        # Derived stats referenced inline in the paper text
        if "method-lines-percentile" in dataset_stats:
            latex_file.append_macro(
                su.latex.Macro(
                    f"stat-max-method-lines-{self._dataset_name}",
                    f"{int(dataset_stats['method-lines-percentile']['100']):,d}",
                )
            )
        if "method-lines-larger-than-20" in dataset_stats:
            latex_file.append_macro(
                su.latex.Macro(
                    f"stat-method-lines-larger-than-20-{self._dataset_name}",
                    f"{dataset_stats['method-lines-larger-than-20']:.1f}",
                )
            )
        for stats_key in ["only-throw-mut", "empty-no-throw"]:
            if stats_key in dataset_stats:
                pct = dataset_stats[stats_key] / dataset_stats["num-methods"] * 100
                latex_file.append_macro(
                    su.latex.Macro(
                        f"stat-{stats_key}-percentage-{self._dataset_name}", f"{pct:.1f}"
                    )
                )

        latex_file.save()

    def make_data_funnel_numbers(
        self,
        collected_dataset_name: str,
        direct_dataset_name: str,
        gold_dataset_name: str,
    ):
        """Emit macros derived across the data-collection funnel stages,
        referenced inline in the dataset and task sections.

        Args:
            collected_dataset_name: Dataset with all collected methods
                (before the direct-throw filter).
            direct_dataset_name: Dataset with only direct-throw methods.
            gold_dataset_name: Dataset whose removed-compile-fail.json counts
                methods that fail to compile after ERC removal
                (generated by count_data_perks count_no_throw_error).
        """
        logger.info(f"Making data funnel numbers of {self._dataset_name}")
        latex_file = su.latex.File(
            self._tables_dir / "numbers" / f"numbers-{self._dataset_name}-funnel.tex",
            is_append=False,
        )
        collected_stats: dict[str, Any] = su.io.load(
            ThrowgenMacros.mebt_data_dir / collected_dataset_name / "dataset_stats.json"
        )  # type: ignore
        direct_stats: dict[str, Any] = su.io.load(
            ThrowgenMacros.mebt_data_dir / direct_dataset_name / "dataset_stats.json"
        )  # type: ignore
        eval_stats: dict[str, Any] = su.io.load(
            self._dataset_dir / "dataset_stats.json"
        )  # type: ignore

        direct_pct = direct_stats["num-methods"] / collected_stats["num-methods"] * 100
        latex_file.append_macro(
            su.latex.Macro("stat-direct-throw-percentage", f"{direct_pct:.1f}")
        )

        rm_comp_fail_path = (
            ThrowgenMacros.mebt_data_dir
            / gold_dataset_name
            / "removed-compile-fail.json"
        )
        if rm_comp_fail_path.exists():
            rm_comp_fail_stats: dict[str, Any] = su.io.load(rm_comp_fail_path)  # type: ignore
            rm_pct = (
                rm_comp_fail_stats["total-rm-comp-fail"]
                / eval_stats["num-methods"]
                * 100
            )
            latex_file.append_macro(
                su.latex.Macro("stat-rm-comp-fail-percentage", f"{rm_pct:.1f}")
            )
        else:
            logger.warning(
                f"Missing {rm_comp_fail_path}, skipping rm-comp-fail percentage"
            )

        latex_file.save()

    def make_result_numbers(
        self, llm_type: str, prompt_gen_type: str, model_name: str, setup: str
    ):
        logger.info(
            f"Making numbers for {self._dataset_name} {llm_type} {prompt_gen_type} {model_name} {setup}"
        )
        latex_file = su.latex.File(
            self._tables_dir
            / "numbers"
            / f"numbers-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-table.tex",
            is_append=False,
        )

        for eval_type in self.EVAL_TYPES:
            summary_path = (
                self._metrics_dir
                / f"{eval_type}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-summary.json"
            )
            if not summary_path.exists():
                logger.warning(f"Summary missing, skipping: {summary_path.name}")
                continue
            metrics: dict[str, float] = su.io.load(summary_path)  # type: ignore
            for key, val in metrics.items():
                if eval_type.startswith("run"):
                    val *= 100
                fmt = self._infer_fmt(val)
                latex_file.append_macro(
                    su.latex.Macro(
                        f"res-{self._dataset_name}-{eval_type}-{key}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}",
                        f"{val:{fmt}}",
                    )
                )

        latex_file.save()

    def make_all_stats_tables(self, val_dataset_name: str, all_dataset_name: str):
        logger.info(
            f"Making stats table of eval: {self._dataset_name} val: {val_dataset_name}"
        )

        # stats data
        latex_file = su.latex.File(self._tables_dir.parent / "table-dataset-stats.tex")
        cols = [su.latex.Macro(f"THead-data-stats-{t}").use() for t in self.STATS_TYPES]

        latex_file.append(r"\begin{table}[t]")
        latex_file.append(r"\begin{small}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro("TCap-dataset-stats").use()
            + r"\label{tab:dataset-stats}"
            + "}"
        )

        layout_str = "l |" + "c" * len(self.STATS_TYPES)
        latex_file.append(r"\begin{tabular}{" + layout_str + "}")
        latex_file.append(r"\toprule")
        latex_file.append(" & ".join(["Split"] + cols))
        latex_file.append(r"\\")
        latex_file.append(r"\midrule")
        for dataset in [all_dataset_name, val_dataset_name, self._dataset_name]:
            latex_file.append(su.latex.Macro(f"THead-data-stats-{dataset}").use())

            for stats_key in self.STATS_TYPES:
                latex_file.append(
                    " & " + su.latex.Macro(f"stat-{stats_key}-{dataset}").use()
                )
            latex_file.append(r"\\")
        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{small}")
        latex_file.append(r"\end{table}")
        latex_file.save()

        # throw count
        latex_file = su.latex.File(
            self._tables_dir.parent / "table-dataset-throw-count.tex"
        )
        cols = [
            su.latex.Macro(f"THead-data-stats-{t}").use()
            for t in self.THROW_COUNT_TYPES
        ]

        latex_file.append(r"\begin{table}[t]")
        latex_file.append(r"\begin{small}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro("TCap-dataset-throw-count").use()
            + r"\label{tab:dataset-throw-count}"
            + "}"
        )

        layout_str = "l |" + "c" * len(self.THROW_COUNT_TYPES)
        latex_file.append(r"\begin{tabular}{" + layout_str + "}")
        latex_file.append(r"\toprule")
        latex_file.append(" & ".join(["Split"] + cols))
        latex_file.append(r"\\")
        latex_file.append(r"\midrule")
        for dataset in [all_dataset_name, val_dataset_name, self._dataset_name]:
            latex_file.append(su.latex.Macro(f"THead-data-stats-{dataset}").use())

            for stats_key in self.THROW_COUNT_TYPES:
                latex_file.append(
                    " & " + su.latex.Macro(f"stat-{stats_key}-{dataset}").use()
                )
            latex_file.append(r"\\")
        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{small}")
        latex_file.append(r"\end{table}")

        latex_file.save()

    def make_prompt_comp_bold(self, setup: str):
        logger.info(f"Making bold for prompt comp")
        prompt_comp_dict: defaultdict[str, list[tuple[float, str]]] = defaultdict(list)
        for eval_type in self.EVAL_TYPES:
            for prompt_gen_type in self.PROMPT_GEN_TYPES:
                summary_path = (
                    self._metrics_dir
                    / f"{eval_type}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{prompt_gen_type}-{setup}-summary.json"
                )
                if not summary_path.exists():
                    logger.warning(f"Summary missing, skipping: {summary_path.name}")
                    continue
                metrics: dict[str, float] = su.io.load(summary_path)  # type: ignore
                for key, val in metrics.items():
                    prompt_comp_dict[f"{eval_type}-{key}"].append(
                        (
                            val,
                            f"res-{self._dataset_name}-{eval_type}-{key}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{prompt_gen_type}-{setup}",
                        )
                    )

        max_prompt_dict: dict[str, str] = {
            k: max(v, key=lambda x: x[0])[1] for k, v in prompt_comp_dict.items()
        }
        su.io.dump(
            self._tables_dir / "bold" / f"bold-prompt-comp-{setup}.json",
            max_prompt_dict,
            su.io.Fmt.jsonPretty,
        )

    def make_repair_comp_bold(self, setup: str, repair_setup: str):
        logger.info(f"Making bold for repair comp")
        prompt_comp_dict: defaultdict[str, list[tuple[float, str]]] = defaultdict(list)
        # Pair base prompts with their repair variants (matching make_repair_comp_table)
        row_groups = list(zip(
            self.MODEL_COMP_PROMPT_GEN_TYPES,
            [f"{p}@{self.MAX_REPAIR_COMP_ITERATION}" for p in self.REPAIR_COMP_PROMPT_GEN_TYPES]
        ))
        for eval_type in self.EVAL_TYPES:
            for base_prompt, repair_prompt in row_groups:
                # Base prompt with setup
                base_path = (
                    self._metrics_dir
                    / f"{eval_type}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{base_prompt}-{setup}-summary.json"
                )
                if base_path.exists():
                    metrics: dict[str, float] = su.io.load(base_path)  # type: ignore
                    for key, val in metrics.items():
                        prompt_comp_dict[f"{eval_type}-{key}"].append(
                            (
                                val,
                                f"res-{self._dataset_name}-{eval_type}-{key}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{base_prompt}-{setup}",
                            )
                        )
                else:
                    logger.warning(f"Summary missing, skipping: {base_path.name}")
                # Repair prompt with repair_setup
                repair_path = (
                    self._metrics_dir
                    / f"{eval_type}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{repair_prompt}-{repair_setup}-summary.json"
                )
                if repair_path.exists():
                    metrics = su.io.load(repair_path)  # type: ignore
                    for key, val in metrics.items():
                        prompt_comp_dict[f"{eval_type}-{key}"].append(
                            (
                                val,
                                f"res-{self._dataset_name}-{eval_type}-{key}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{repair_prompt}-{repair_setup}",
                            )
                        )
                else:
                    logger.warning(f"Summary missing, skipping: {repair_path.name}")

        max_prompt_dict: dict[str, str] = {
            k: max(v, key=lambda x: x[0])[1] for k, v in prompt_comp_dict.items()
        }
        su.io.dump(
            self._tables_dir / "bold" / f"bold-prompt-comp-{repair_setup}.json",
            max_prompt_dict,
            su.io.Fmt.jsonPretty,
        )

    def make_model_comp_bold(self, setup: str):
        logger.info(f"Making bold for model comp")
        model_comp_dict: defaultdict[str, defaultdict[str, list[tuple[float, str]]]] = (
            defaultdict(lambda: defaultdict(list))
        )

        for eval_type in self.EVAL_TYPES:
            for prompt_gen_type in self.MODEL_COMP_PROMPT_GEN_TYPES:
                for llm_type, model_name in self.SELECTED_LLM_TYPES:
                    summary_path = (
                        self._metrics_dir
                        / f"{eval_type}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}-summary.json"
                    )
                    if not summary_path.exists():
                        logger.warning(f"Summary missing, skipping: {summary_path.name}")
                        continue
                    metrics: dict[str, float] = su.io.load(summary_path)  # type: ignore
                    for key, val in metrics.items():
                        model_comp_dict[f"{llm_type}-{model_name}"][
                            f"{eval_type}-{key}"
                        ].append(
                            (
                                val,
                                f"res-{self._dataset_name}-{eval_type}-{key}-{llm_type}-{model_name}-{prompt_gen_type}-{setup}",
                            )
                        )
        max_model_dict: dict[str, dict[str, str]] = {
            model_name: {
                k: max(v, key=lambda x: x[0])[1] for k, v in model_dict.items()
            }
            for model_name, model_dict in model_comp_dict.items()
        }
        su.io.dump(
            self._tables_dir / "bold" / f"bold-model-comp-{setup}.json",
            max_model_dict,
            su.io.Fmt.jsonPretty,
        )

    def make_repair_comp_table(self, setup: str, repair_setup: str, tag: str = ""):
        logger.info(f"Making repair comp tables for {self._dataset_name} {setup} vs {repair_setup}")
        max_prompt_dict: dict[str, str] = su.io.load(
            self._tables_dir / "bold" / f"bold-prompt-comp-{repair_setup}.json"
        )  # type: ignore
        tag_suffix = f"-{tag}" if tag else ""
        latex_file = su.latex.File(self._tables_dir / f"table-prompt-comp-{repair_setup}.tex")
        cols = self.RUN_METRICS_TYPES
        # Pair base with repair variants (with max iteration)
        row_groups = list(zip(
            self.MODEL_COMP_PROMPT_GEN_TYPES,
            [f"{p}@{self.MAX_REPAIR_COMP_ITERATION}" for p in self.REPAIR_COMP_PROMPT_GEN_TYPES]
        ))

        latex_file.append(r"\begin{table*}[t]")
        # footnotesize, not small: this table carries twelve numeric columns and
        # only fits the two-column width at the smaller size.
        latex_file.append(r"\begin{footnotesize}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro(f"TCap-res-prompt-comp-{repair_setup}{tag_suffix}".replace("_", "-")).use()
            + f"\\label{{tab:prompt-comp-results-{repair_setup}{tag_suffix}}}"
            + "}"
        )
        layout_str = "l |" + "c" * len(self.RUN_METRICS_TYPES)

        latex_file.append(r"\begin{tabular}{" + layout_str + "}")
        latex_file.append(r"\toprule")
        latex_file.append(
            r"\multirow{2}{*}{" + su.latex.Macro(f"THead-prompt").use() + "}"
        )
        for k, v in self.RUN_METRICS_TYPES_DICT.items():
            latex_file.append(
                f"& \\multicolumn{{{len(v)}}}{{c}}{{{su.latex.Macro(f'THead-{k}').use()}}}"
            )
        latex_file.append(r"\\")
        for k in self.RUN_METRICS_TYPES:
            latex_file.append("& " + su.latex.Macro(f"THead-{k}-small").use())
        latex_file.append(r"\\")
        latex_file.append(r"\midrule")

        for group_idx, (base_prompt, repair_prompt) in enumerate(row_groups):
            # Base prompt uses the regular setup
            latex_file.append(su.latex.Macro(f"THead-{base_prompt}").use())
            for metric_n in cols:
                macro_name = f"res-{self._dataset_name}-{metric_n}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{base_prompt}-{setup}"
                latex_file.append(" & " + su.latex.Macro(macro_name).use())
            latex_file.append(r"\\")
            # Repair prompt uses the repair setup
            latex_file.append(su.latex.Macro(f"THead-{repair_prompt}").use())
            for metric_n in cols:
                macro_name = f"res-{self._dataset_name}-{metric_n}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{repair_prompt}-{repair_setup}"
                if macro_name == max_prompt_dict.get(metric_n):
                    latex_file.append(
                        " & " + f"\\textbf{{{su.latex.Macro(macro_name).use()}}}"
                    )
                else:
                    latex_file.append(" & " + su.latex.Macro(macro_name).use())
            latex_file.append(r"\\")
            if group_idx < len(row_groups) - 1:
                latex_file.append(r"\midrule")

        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{footnotesize}")
        latex_file.append(r"\end{table*}")
        latex_file.save()

    def make_complete_repair_comp_table(self, setup: str, repair_setup: str, tag: str = ""):
        logger.info(f"Making complete repair comp tables for {self._dataset_name} {setup} vs {repair_setup}")
        tag_suffix = f"-{tag}" if tag else ""
        latex_file = su.latex.File(self._tables_dir / f"table-complete-repair-comp-{repair_setup}.tex")
        cols = self.RUN_METRICS_TYPES
        # Pair base with all repair iterations
        row_groups = list(zip(
            self.MODEL_COMP_PROMPT_GEN_TYPES,
            self.REPAIR_COMP_PROMPT_GEN_TYPES
        ))

        latex_file.append(r"\begin{table*}[t]")
        latex_file.append(r"\begin{small}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro(f"TCap-res-complete-repair-comp-{setup}{tag_suffix}".replace("_", "-")).use()
            + f"\\label{{tab:complete-repair-comp-results{tag_suffix}}}"
            + "}"
        )
        layout_str = "l |" + "c" * len(self.RUN_METRICS_TYPES)

        latex_file.append(r"\begin{tabular}{" + layout_str + "}")
        latex_file.append(r"\toprule")
        latex_file.append(
            r"\multirow{2}{*}{" + su.latex.Macro(f"THead-prompt").use() + "}"
        )
        for k, v in self.RUN_METRICS_TYPES_DICT.items():
            latex_file.append(
                f"& \\multicolumn{{{len(v)}}}{{c}}{{{su.latex.Macro(f'THead-{k}').use()}}}"
            )
        latex_file.append(r"\\")
        for k in self.RUN_METRICS_TYPES:
            latex_file.append("& " + su.latex.Macro(f"THead-{k}-small").use())
        latex_file.append(r"\\")
        latex_file.append(r"\midrule")

        for group_idx, (base_prompt, repair_prompt_base) in enumerate(row_groups):
            # Base prompt uses the regular setup
            latex_file.append(su.latex.Macro(f"THead-{base_prompt}").use())
            for metric_n in cols:
                macro_name = f"res-{self._dataset_name}-{metric_n}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{base_prompt}-{setup}"
                latex_file.append(" & " + su.latex.Macro(macro_name).use())
            latex_file.append(r"\\")
            # All repair iterations
            for iteration in range(1, self.MAX_REPAIR_COMP_ITERATION + 1):
                repair_prompt = f"{repair_prompt_base}@{iteration}"
                latex_file.append(su.latex.Macro(f"THead-{repair_prompt}").use())
                for metric_n in cols:
                    macro_name = f"res-{self._dataset_name}-{metric_n}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{repair_prompt}-{repair_setup}"
                    latex_file.append(" & " + su.latex.Macro(macro_name).use())
                latex_file.append(r"\\")
            if group_idx < len(row_groups) - 1:
                latex_file.append(r"\midrule")

        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{small}")
        latex_file.append(r"\end{table*}")
        latex_file.save()

    def make_prompt_comp_table(self, setup: str, tag: str = ""):
        logger.info(f"Making prompt comp tables for {self._dataset_name} {setup}")
        max_prompt_dict: dict[str, str] = su.io.load(
            self._tables_dir / "bold" / f"bold-prompt-comp-{setup}.json"
        )  # type: ignore
        tag_suffix = f"-{tag}" if tag else ""
        latex_file = su.latex.File(self._tables_dir / f"table-prompt-comp-{setup}.tex")
        cols = self.RUN_METRICS_TYPES
        rows = self.PROMPT_GEN_TYPES

        latex_file.append(r"\begin{table*}[t]")
        latex_file.append(r"\begin{small}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro(f"TCap-res-prompt-comp-{setup}{tag_suffix}".replace("_", "-")).use()
            + f"\\label{{tab:prompt-comp-results{tag_suffix}}}"
            + "}"
        )
        layout_str = "l |" + "c" * len(self.RUN_METRICS_TYPES)

        latex_file.append(r"\setlength{\tabcolsep}{8.1pt}")
        latex_file.append(r"\begin{tabular}{" + layout_str + "}")
        latex_file.append(r"\toprule")
        latex_file.append(
            r"\multirow{2}{*}{" + su.latex.Macro(f"THead-prompt").use() + "}"
        )
        for k, v in self.RUN_METRICS_TYPES_DICT.items():
            latex_file.append(
                f"& \\multicolumn{{{len(v)}}}{{c}}{{{su.latex.Macro(f'THead-{k}').use()}}}"
            )
        latex_file.append(r"\\")
        for k in self.RUN_METRICS_TYPES:
            latex_file.append("& " + su.latex.Macro(f"THead-{k}-small").use())
        latex_file.append(r"\\")
        latex_file.append(r"\midrule")

        for i, prompt_gen_type in enumerate(rows):
            latex_file.append(su.latex.Macro(f"THead-{prompt_gen_type}").use())
            for metric_n in cols:
                macro_name = f"res-{self._dataset_name}-{metric_n}-{self.PROMPT_COMP_LLM_TYPES[0]}-{self.PROMPT_COMP_LLM_TYPES[1]}-{prompt_gen_type}-{setup}"
                if macro_name == max_prompt_dict.get(metric_n):
                    latex_file.append(
                        " & " + f"\\textbf{{{su.latex.Macro(macro_name).use()}}}"
                    )
                else:
                    latex_file.append(" & " + su.latex.Macro(macro_name).use())
            latex_file.append(r"\\")
            if i == 0:
                latex_file.append(r"\midrule")

        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{small}")
        latex_file.append(r"\end{table*}")
        latex_file.save()

    def make_model_comp_table(self, setup: str, tag: str = ""):
        logger.info(f"Making model comp tables for {self._dataset_name} {setup}")
        max_model_dict: dict[str, dict[str, str]] = su.io.load(
            self._tables_dir / "bold" / f"bold-model-comp-{setup}.json"
        )  # type: ignore
        tag_suffix = f"-{tag}" if tag else ""
        latex_file = su.latex.File(self._tables_dir / f"table-model-comp-{setup}.tex")
        cols = self.RUN_METRICS_TYPES
        rows = self.SELECTED_LLM_TYPES

        latex_file.append(r"\begin{table*}[t]")
        latex_file.append(r"\begin{small}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro(f"TCap-res-model-comp-{setup}{tag_suffix}".replace("_", "-")).use()
            + f"\\label{{tab:model-comp-results{tag_suffix}}}"
            + "}"
        )
        layout_str = "l | c |" + "c" * len(self.RUN_METRICS_TYPES)

        latex_file.append(r"\setlength{\tabcolsep}{4.8pt}")
        latex_file.append(r"\begin{tabular}{" + layout_str + "}")
        latex_file.append(r"\toprule")
        latex_file.append(
            r"\multirow{2}{*}{" + su.latex.Macro(f"THead-model").use() + "}"
        )
        latex_file.append(
            "& " + r"\multirow{2}{*}{" + su.latex.Macro(f"THead-prompt").use() + "}"
        )
        for k, v in self.RUN_METRICS_TYPES_DICT.items():
            latex_file.append(
                f"& \\multicolumn{{{len(v)}}}{{c}}{{{su.latex.Macro(f'THead-{k}').use()}}}"
            )
        latex_file.append(r"\\")
        latex_file.append("&")
        for k in self.RUN_METRICS_TYPES:
            latex_file.append("& " + su.latex.Macro(f"THead-{k}-small").use())

        latex_file.append(r"\\")
        latex_file.append(r"\midrule")

        for i, (llm_t, model_n) in enumerate(rows):
            escaped_model_n = model_n.replace("_", "-")
            model_macros = su.latex.Macro(f"THead-{escaped_model_n}").use()
            latex_file.append(
                rf"\multirow{{{len(self.MODEL_COMP_PROMPT_GEN_TYPES)}}}{{*}}{{{model_macros}}}"
            )
            for prompt_gen_type in self.MODEL_COMP_PROMPT_GEN_TYPES:
                latex_file.append(
                    "&" + su.latex.Macro(f"THead-{prompt_gen_type}").use()
                )
                for metric_n in cols:
                    macro_name = f"res-{self._dataset_name}-{metric_n}-{llm_t}-{model_n}-{prompt_gen_type}-{setup}"
                    if macro_name == max_model_dict.get(f"{llm_t}-{model_n}", {}).get(metric_n):
                        latex_file.append(
                            " & " + f"\\textbf{{{su.latex.Macro(macro_name).use()}}}"
                        )
                    else:
                        latex_file.append(" & " + su.latex.Macro(macro_name).use())
                latex_file.append(r"\\")
            if i < len(rows) - 1:
                latex_file.append(r"\midrule")

        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{small}")
        latex_file.append(r"\end{table*}")
        latex_file.save()

    def make_data_comp_table(self, setup: str, comp_dataset_name: str):
        logger.info(f"Making data comp tables for {self._dataset_name} {setup}")
        latex_file = su.latex.File(self._tables_dir / f"table-data-comp-{setup}.tex")
        cols = self.RUN_METRICS_TYPES
        rows = self.SELECTED_LLM_TYPES

        latex_file.append(r"\begin{table*}[t]")
        latex_file.append(r"\begin{small}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro(f"TCap-res-data-comp-{setup}".replace("_", "-")).use()
            + r"\label{tab:data-comp-results}"
            + "}"
        )
        layout_str = "l | c |" + "c" * len(self.RUN_METRICS_TYPES)

        latex_file.append(r"\begin{tabular}{" + layout_str + "}")
        latex_file.append(r"\toprule")
        latex_file.append(
            r"\multirow{2}{*}{" + su.latex.Macro(f"THead-model").use() + "}"
        )
        latex_file.append(
            "& " + r"\multirow{2}{*}{" + su.latex.Macro(f"THead-comp-dataset").use() + "}"
        )
        for k in self.RUN_METRICS_TYPES_DICT:
            latex_file.append(
                "& " + r"\multicolumn{2}{c}{" + su.latex.Macro(f"THead-{k}").use() + "}"
            )
        latex_file.append(r"\\")
        latex_file.append("&")
        for k in self.RUN_METRICS_TYPES:
            latex_file.append("& " + su.latex.Macro(f"THead-{k}-small").use())

        latex_file.append(r"\\")
        latex_file.append(r"\midrule")

        for i, (llm_t, model_n) in enumerate(rows):
            escaped_model_n = model_n.replace("_", "-")
            model_macros = su.latex.Macro(f"THead-{escaped_model_n}").use()
            latex_file.append(
                rf"\multirow{{{len(self.MODEL_COMP_PROMPT_GEN_TYPES)}}}{{*}}{{{model_macros}}}"
            )
            for dn in [self._dataset_name, comp_dataset_name]:
                latex_file.append("&" + su.latex.Macro(f"THead-{dn}").use())
                for metric_n in cols:
                    macro_name = f"res-{dn}-{metric_n}-{llm_t}-{model_n}-{self.MODEL_COMP_PROMPT_GEN_TYPES[1]}-{setup}"
                    latex_file.append(" & " + su.latex.Macro(macro_name).use())
                latex_file.append(r"\\")
            if i < len(rows) - 1:
                latex_file.append(r"\midrule")

        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{small}")
        latex_file.append(r"\end{table*}")
        latex_file.save()

    def collect_all_macros(self):
        logger.info(f"Collecting all marcos for {self._dataset_name}")
        latex_file = su.latex.File(self._tables_dir / "all-numbers.tex")
        for num_macros_path in glob.glob(
            str(self._tables_dir / "numbers" / "numbers-*.tex")
        ):
            relative_path = f"{self._tables_dir.parent.stem}/{self._tables_dir.stem}/numbers/{Path(num_macros_path).stem}"
            latex_file.append(f"\\input{{{relative_path}}}")
        latex_file.save()

    def make_qualitative_numbers(
        self,
        tags: list[str],
        over_all_methods: bool = False,
    ):
        """Write macros from qualitative analysis summaries to LaTeX file.

        Args:
            tags: List of tags to load summaries for (e.g., ["base", "tuctn"]).
                  Each tag corresponds to qual_summary_{tag}.json and
                  same_samples_qual_summary_{tag}.json files.
            over_all_methods: Also emit `-semantic-match-yes-of-methods-pct`
                  macros, taken over every target method in the dataset rather
                  than over the ERC that pass all tests. The Venn diagrams use
                  the same total, so macros and figures share a denominator.
        """
        logger.info(f"Making qualitative numbers for tags: {tags}")

        eval_total: int | None = None
        if over_all_methods:
            eval_total = len(load_eval_ids(self._dataset_name))
            logger.info(f"Evaluation set total: {eval_total}")

        # Output: LaTeX file
        output_path = ThrowgenMacros.paper_dir / "tables" / "qualitative-numbers.tex"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        latex_file = su.latex.File(output_path, is_append=False)

        # Define the file prefixes and their corresponding macro prefixes
        file_configs = [
            ("qual_summary_", "qual"),
            ("same_samples_qual_summary_", "qual-same"),
        ]

        for file_prefix, macro_prefix in file_configs:
            for tag in tags:
                # Input: qualitative summary JSON for this tag
                summary_path = Macros.work_dir / "results" / "qualitative" / f"{file_prefix}{tag}.json"
                if not summary_path.exists():
                    logger.warning(f"Summary file not found: {summary_path}")
                    continue

                summary: dict[str, Any] = su.io.load(summary_path)
                tag_suffix = tag.replace("_", "-")

                # Total samples (100%)
                total = summary["total-samples"]
                latex_file.append_macro(
                    su.latex.Macro(f"{macro_prefix}-{tag_suffix}-total-samples-count", f"{total:,d}")
                )
                latex_file.append_macro(
                    su.latex.Macro(f"{macro_prefix}-{tag_suffix}-total-samples-pct", "100.00")
                )

                # Semantic match yes/no counts and percentages
                for key in ["semantic-match-yes", "semantic-match-no"]:
                    latex_file.append_macro(
                        su.latex.Macro(f"{macro_prefix}-{tag_suffix}-{key}-count", f"{summary[key]['count']:,d}")
                    )
                    latex_file.append_macro(
                        su.latex.Macro(f"{macro_prefix}-{tag_suffix}-{key}-pct", f"{summary[key]['percentage']:.2f}")
                    )

                for key in ["semantic-match-yes", "semantic-match-no"]:
                    latex_file.append_macro(
                        su.latex.Macro(
                            f"{macro_prefix}-{tag_suffix}-{key}-of-total-pct",
                            f"{100.0 * summary[key]['count'] / total:.2f}",
                        )
                    )

                if eval_total:
                    for key in ["semantic-match-yes", "semantic-match-no"]:
                        latex_file.append_macro(
                            su.latex.Macro(
                                f"{macro_prefix}-{tag_suffix}-{key}-of-methods-pct",
                                f"{100.0 * summary[key]['count'] / eval_total:.2f}",
                            )
                        )

                # Category counts among no-semantic-match samples
                category_counts: dict[str, dict] = summary.get("category-counts", {})
                for cat in self.QUALITATIVE_CATEGORIES:
                    safe_cat = self.QUALITATIVE_CATEGORY_MACRO.get(
                        cat, cat.replace(" ", "-").replace("_", "-")
                    )
                    if cat in category_counts:
                        info = category_counts[cat]
                        latex_file.append_macro(
                            su.latex.Macro(f"{macro_prefix}-{tag_suffix}-{safe_cat}-count", f"{info['count']:,d}")
                        )
                        latex_file.append_macro(
                            su.latex.Macro(f"{macro_prefix}-{tag_suffix}-{safe_cat}-pct", f"{info['percentage']:.2f}")
                        )
                    else:
                        # Category not present, use 0
                        latex_file.append_macro(
                            su.latex.Macro(f"{macro_prefix}-{tag_suffix}-{safe_cat}-count", "0")
                        )
                        latex_file.append_macro(
                            su.latex.Macro(f"{macro_prefix}-{tag_suffix}-{safe_cat}-pct", "0.00")
                        )

        # Numbers the section quotes about the *difference* between the two
        # prompts. Derived here rather than written by hand so they cannot drift
        # from the table above them, which is what a reviewer checks first.
        self._append_qualitative_comparison(latex_file, tags)

        latex_file.save()
        logger.info(f"Wrote qualitative numbers to {output_path}")

    def _append_qualitative_comparison(self, latex_file, tags: list[str]) -> None:
        """Cross-prompt macros, one set per denominator the section can quote.

        ``fp-diff-count`` is how many more false positives one prompt has than
        the other, ``fp-rate-gap-pct`` is the gap between the two prompts in the
        share of passing \ERC that is a false positive, and
        ``max-share-gap-pct`` is the widest gap between them on any one
        category.

        The ``qual-`` set is over each prompt's own passing \ERC, so the two
        columns have different denominators and the rate gap is the comparable
        number. The ``qual-same-`` set is over the target methods both prompts
        produced a passing \ERC for, which holds the denominator fixed at the
        cost of dropping the methods only one prompt reached.
        """
        if len(tags) != 2:
            logger.warning(
                f"Skipping the cross-prompt macros: they compare two prompts, got {tags}"
            )
            return

        for file_prefix, macro_prefix in [
            ("qual_summary_", "qual"),
            ("same_samples_qual_summary_", "qual-same"),
        ]:
            summaries = {}
            for tag in tags:
                path = (
                    Macros.work_dir / "results" / "qualitative"
                    / f"{file_prefix}{tag}.json"
                )
                if not path.exists():
                    logger.warning(
                        f"Summary file not found, skipping comparison: {path}"
                    )
                    break
                summaries[tag] = su.io.load(path)
            if len(summaries) != len(tags):
                continue

            first, second = (summaries[t] for t in tags)
            latex_file.append_macro(
                su.latex.Macro(
                    f"{macro_prefix}-fp-diff-count",
                    f"{abs(first['semantic-match-no']['count'] - second['semantic-match-no']['count']):,d}",
                )
            )

            fp_rates = [
                100.0 * s["semantic-match-no"]["count"] / s["total-samples"]
                for s in (first, second)
            ]
            latex_file.append_macro(
                su.latex.Macro(
                    f"{macro_prefix}-fp-rate-gap-pct",
                    f"{abs(fp_rates[0] - fp_rates[1]):.1f}",
                )
            )

            gaps = []
            for cat in self.QUALITATIVE_CATEGORIES:
                shares = [
                    s.get("category-counts", {}).get(cat, {}).get("percentage", 0.0)
                    for s in (first, second)
                ]
                gaps.append(abs(shares[0] - shares[1]))
            latex_file.append_macro(
                su.latex.Macro(f"{macro_prefix}-max-share-gap-pct", f"{max(gaps):.1f}")
            )

    def make_agreement_numbers(self, tags: list[str]):
        """Write inter-annotator agreement macros to LaTeX.

        Reads the ``agreement_{tag}.json`` files written by
        ``qualitative_analysis.run_agreement`` and emits, per prompt and per
        pair of annotators, Cohen's kappa along with the raw agreement it is
        computed from.

        A pair whose kappa is null is skipped: ``run_agreement`` reports null
        when one store used a single label throughout (an empty store is the
        usual cause), where the coefficient is not interpretable. Skipping
        means the macro is absent and the build fails loudly rather than the
        paper quoting a meaningless 0.00.

        Args:
            tags: Prompt gen types to emit for (e.g. ["base", "tuctn-all-info"]).
        """
        logger.info(f"Making agreement numbers for tags: {tags}")

        output_path = ThrowgenMacros.paper_dir / "tables" / "agreement-numbers.tex"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        latex_file = su.latex.File(output_path, is_append=False)

        # Every interpretable pair across every arm, so the range the prose
        # quotes is computed here rather than read off these macros by hand.
        all_kappas: list[float] = []

        for tag in tags:
            agreement_path = (
                Macros.work_dir / "results" / "qualitative" / f"agreement_{tag}.json"
            )
            if not agreement_path.exists():
                logger.warning(f"Agreement file not found: {agreement_path}")
                continue

            agreement: dict[str, Any] = su.io.load(agreement_path)
            tag_suffix = tag.replace("_", "-")

            latex_file.append_macro(
                su.latex.Macro(
                    f"agree-{tag_suffix}-total-samples-count",
                    f"{agreement['total-samples']:,d}",
                )
            )

            for name, store in agreement.get("stores", {}).items():
                for key in ["labelled", "defaulted"]:
                    latex_file.append_macro(
                        su.latex.Macro(
                            f"agree-{tag_suffix}-{name}-{key}-count",
                            f"{store[key]:,d}",
                        )
                    )

            for pair, stats in agreement.get("pairs", {}).items():
                if stats["kappa"] is None:
                    logger.warning(
                        f"{tag}: {pair} has no interpretable kappa "
                        f"(a store used one label throughout), skipping"
                    )
                    continue
                all_kappas.append(stats["kappa"])
                prefix = f"agree-{tag_suffix}-{pair}"
                latex_file.append_macro(
                    su.latex.Macro(f"{prefix}-kappa", f"{stats['kappa']:.2f}")
                )
                latex_file.append_macro(
                    su.latex.Macro(f"{prefix}-pct", f"{stats['agreement-pct']:.1f}")
                )
                latex_file.append_macro(
                    su.latex.Macro(f"{prefix}-agree-count", f"{stats['agree']:,d}")
                )
                latex_file.append_macro(
                    su.latex.Macro(
                        f"{prefix}-disagree-count", f"{stats['disagree']:,d}"
                    )
                )

        if all_kappas:
            latex_file.append_macro(
                su.latex.Macro("agree-kappa-pair-count", f"{len(all_kappas):d}")
            )
            latex_file.append_macro(
                su.latex.Macro("agree-kappa-min", f"{min(all_kappas):.2f}")
            )
            latex_file.append_macro(
                su.latex.Macro("agree-kappa-max", f"{max(all_kappas):.2f}")
            )

        latex_file.save()
        logger.info(
            f"Wrote agreement numbers to {output_path} "
            f"({len(all_kappas)} interpretable pairs)"
        )

    def make_prompt_improvement_numbers(self, setup: str):
        """Generate LaTeX macros showing improvement of tuctn-all-info over base for selected models.

        Outputs macros like:
        - \\OverQwenLargeCompOne, \\OverQwenLargeCompFive, \\OverQwenLargeCompTen
        - \\OverQwenLargePassEBTOne, \\OverQwenLargePassEBTFive, \\OverQwenLargePassEBTTen
        - \\OverQwenLargePassAllOne, \\OverQwenLargePassAllFive, \\OverQwenLargePassAllTen
        - Same for GPT

        Args:
            setup: The experiment setup (e.g., "multi_ebt").
        """
        logger.info(f"Making prompt improvement numbers for {self._dataset_name} {setup}")

        # Metrics mapping: (eval_type, metric_key) -> macro_suffix
        metrics_mapping = [
            ("run-ebts-pass-at-k", "compiled-at", "Comp"),
            ("run-ebts-pass-at-k", "pass-at", "PassEBT"),
            ("run-all-pass-at-k", "pass-at", "PassAll"),
            ("run-all-with-tools-pass-at-k", "pass-at", "PassAllTools"),
        ]

        k_name_map = {1: "One", 5: "Five", 10: "Ten"}

        latex_file = su.latex.File(
            self._tables_dir / "numbers" / f"numbers-prompt-improvement-{setup}.tex",
            is_append=False,
        )

        for (llm_type, model_name), model_label in self.IMPROVEMENT_MODELS:
            for eval_type, metric_key_base, macro_metric_name in metrics_mapping:
                # Load metrics for both prompts
                tuctn_metrics: dict[str, float] = su.io.load(
                    self._metrics_dir
                    / f"{eval_type}-{llm_type}-{model_name}-tuctn-all-info-{setup}-summary.json"
                )  # type: ignore
                base_metrics: dict[str, float] = su.io.load(
                    self._metrics_dir
                    / f"{eval_type}-{llm_type}-{model_name}-base-{setup}-summary.json"
                )  # type: ignore

                for k in [1, 5, 10]:
                    metric_key = f"{metric_key_base}-{k}"
                    tuctn_val = tuctn_metrics[metric_key]
                    base_val = base_metrics[metric_key]
                    # Round to the precision the tables print before subtracting,
                    # so a reader can reproduce the difference from the table.
                    diff = round(tuctn_val * 100, 2) - round(base_val * 100, 2)

                    macro_name = f"Over{model_label}{macro_metric_name}{k_name_map[k]}"
                    latex_file.append_macro(
                        su.latex.Macro(macro_name, f"{diff:.2f}\\xspace")
                    )

        latex_file.save()
        logger.info(f"Wrote prompt improvement numbers to {latex_file.path}")

    def make_repair_improvement_numbers(self, setup: str, repair_setup: str, iteration: int = 4):
        """Generate LaTeX macros showing improvement of tuctn-all-info-repair over base-repair.

        Outputs macros like:
        - \\OverQwenLargeRepairCompOne, \\OverQwenLargeRepairCompFive, etc.

        Args:
            setup: The base experiment setup (e.g., "multi_ebt").
            repair_setup: The repair experiment setup (e.g., "repair").
            iteration: The repair iteration to compare (default 4).
        """
        logger.info(f"Making repair improvement numbers for {self._dataset_name} {repair_setup}@{iteration}")

        # Metrics mapping: (eval_type, metric_key) -> macro_suffix
        metrics_mapping = [
            ("run-ebts-pass-at-k", "compiled-at", "Comp"),
            ("run-ebts-pass-at-k", "pass-at", "PassEBT"),
            ("run-all-pass-at-k", "pass-at", "PassAll"),
            ("run-all-with-tools-pass-at-k", "pass-at", "PassAllTools"),
        ]

        k_name_map = {1: "One", 5: "Five", 10: "Ten"}

        latex_file = su.latex.File(
            self._tables_dir / "numbers" / f"numbers-repair-improvement-{repair_setup}.tex",
            is_append=False,
        )

        for (llm_type, model_name), model_label in self.REPAIR_IMPROVEMENT_MODELS:
            for eval_type, metric_key_base, macro_metric_name in metrics_mapping:
                # Load metrics for both repair prompts at specified iteration
                tuctn_path = (
                    self._metrics_dir
                    / f"{eval_type}-{llm_type}-{model_name}-tuctn-all-info-repair@{iteration}-{repair_setup}-summary.json"
                )
                base_path = (
                    self._metrics_dir
                    / f"{eval_type}-{llm_type}-{model_name}-base-repair@{iteration}-{repair_setup}-summary.json"
                )
                if not tuctn_path.exists() or not base_path.exists():
                    logger.warning(
                        f"Repair summary missing for {eval_type} / {model_name}, skipping"
                    )
                    continue
                tuctn_repair_metrics: dict[str, float] = su.io.load(tuctn_path)  # type: ignore
                base_repair_metrics: dict[str, float] = su.io.load(base_path)  # type: ignore

                for k in [1, 5, 10]:
                    metric_key = f"{metric_key_base}-{k}"
                    tuctn_val = tuctn_repair_metrics[metric_key]
                    base_val = base_repair_metrics[metric_key]
                    # Round to the precision the tables print before subtracting,
                    # so a reader can reproduce the difference from the table.
                    diff = round(tuctn_val * 100, 2) - round(base_val * 100, 2)

                    macro_name = f"Over{model_label}Repair{macro_metric_name}{k_name_map[k]}"
                    latex_file.append_macro(
                        su.latex.Macro(macro_name, f"{diff:.2f}\\xspace")
                    )

        latex_file.save()
        logger.info(f"Wrote repair improvement numbers to {latex_file.path}")

    def _get_passing_ids(self, results: list[dict[str, Any]]) -> set[str]:
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

    def make_overlap_numbers(
        self,
        setup: str,
        metrics_type: str = "run-all",
    ):
        """Generate LaTeX macros for overlap statistics between the two main
        prompts (MODEL_COMP_PROMPT_GEN_TYPES) on the PROMPT_COMP_LLM_TYPES model.

        Outputs macros for:
        1. Number of datapoints passing both prompts
        2. Number of datapoints passing only the first main prompt (base)
        3. Number of datapoints passing only the second main prompt (tuctn-all-info)
        4. Number of datapoints passing neither prompt

        Args:
            setup: Experiment setup (e.g., "multi_ebt").
            metrics_type: Type of metrics file to load (e.g., "run-all", "run-ebts").
        """
        logger.info(
            f"Making overlap numbers for {self._dataset_name} {setup} {metrics_type}"
        )

        prompt_a = self.MODEL_COMP_PROMPT_GEN_TYPES[0]  # "base"
        prompt_b = self.MODEL_COMP_PROMPT_GEN_TYPES[1]  # "tuctn-all-info"
        llm_type, model_name = self.PROMPT_COMP_LLM_TYPES
        # Load results for both prompts
        results_a: list[dict[str, Any]] = su.io.load(
            self._metrics_dir
            / f"{metrics_type}-{llm_type}-{model_name}-{prompt_a}-{setup}-each-sample.jsonl"
        )  # type: ignore
        results_b: list[dict[str, Any]] = su.io.load(
            self._metrics_dir
            / f"{metrics_type}-{llm_type}-{model_name}-{prompt_b}-{setup}-each-sample.jsonl"
        )  # type: ignore

        # Get all IDs from the results
        total_ids = {r["id"] for r in results_a}

        # Get passing IDs for each prompt
        passing_a = self._get_passing_ids(results_a)
        passing_b = self._get_passing_ids(results_b)

        # Calculate overlap statistics
        both = len(passing_a & passing_b)
        only_a = len(passing_a - passing_b)
        only_b = len(passing_b - passing_a)
        neither = len(total_ids - (passing_a | passing_b))

        logger.info(f"  Total datapoints: {len(total_ids)}")
        logger.info(f"  Both prompts: {both}")
        logger.info(f"  Only {prompt_a}: {only_a}")
        logger.info(f"  Only {prompt_b}: {only_b}")
        logger.info(f"  Neither: {neither}")

        # Write LaTeX macros
        latex_file = su.latex.File(
            self._tables_dir
            / "numbers"
            / f"numbers-overlap-{llm_type}-{model_name}-{metrics_type}-{setup}.tex",
            is_append=False,
        )

        macro_prefix = f"overlap-{self._dataset_name}-{metrics_type}-{llm_type}-{model_name}-{setup}"

        latex_file.append_macro(
            su.latex.Macro(f"{macro_prefix}-both", f"{both:,d}")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{macro_prefix}-only-{prompt_a}", f"{only_a:,d}")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{macro_prefix}-only-{prompt_b}", f"{only_b:,d}")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{macro_prefix}-pass-{prompt_a}", f"{both+only_a:,d}")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{macro_prefix}-pass-{prompt_b}", f"{both+only_b:,d}")
        )
        latex_file.append_macro(
            su.latex.Macro(f"{macro_prefix}-neither", f"{neither:,d}")
        )

        latex_file.save()
        logger.info(f"Wrote overlap numbers to {latex_file.path}")

    def make_qualitative_table(self, tags: list[str]):
        """Generate the qualitative-analysis table.

        One column per prompt, one row per outcome: the share of passing \ERC
        that are not semantically equivalent, then how those break down over
        the false-positive categories.  Percentages only -- the counts are in
        tables/qualitative-numbers.tex and quoted inline where they matter.

        Single-column `table`, not `table*`: the paper is tuned to exactly 12
        pages and this table is narrow enough not to need the full width.

        Args:
            tags: prompts to show as columns, e.g. ["base", "tuctn-all-info"].
        """
        logger.info(f"Making qualitative table for tags: {tags}")

        output_path = self._tables_dir.parent / "table-qualitative.tex"
        latex_file = su.latex.File(output_path)

        suffixes = [t.replace("_", "-") for t in tags]

        latex_file.append(r"\begin{table}[!tbp]")
        latex_file.append(r"\vspace{10pt}")
        latex_file.append(r"\begin{small}")
        latex_file.append(r"\begin{center}")
        latex_file.append(
            r"\caption{"
            + su.latex.Macro("TCap-qualitative").use()
            + r"\label{tab:qualitative}"
            + "}"
        )
        latex_file.append(r"\vspace{3pt}")
        latex_file.append(r"\begin{tabular}{l |" + "c" * len(tags) + "}")
        latex_file.append(r"\toprule")
        latex_file.append(
            " & ".join([r"(\%)"] + [su.latex.Macro(f"THead-{t}").use() for t in tags])
        )
        latex_file.append(r"\\")
        latex_file.append(r"\midrule")

        # How many of the passing \ERC are false positives, as a share of all
        # passing \ERC for that prompt.
        latex_file.append(
            " & ".join(
                [su.latex.Macro("THead-qual-semantic-match-no").use()]
                + [
                    su.latex.Macro(f"qual-{s}-semantic-match-no-of-total-pct").use()
                    for s in suffixes
                ]
            )
        )
        latex_file.append(r"\\")
        latex_file.append(r"\midrule")

        # ... and how those false positives divide over the categories, as a
        # share of the false positives rather than of all passing \ERC.
        for cat in self.QUALITATIVE_CATEGORIES:
            macro_cat = self.QUALITATIVE_CATEGORY_MACRO.get(cat, cat)
            latex_file.append(
                " & ".join(
                    [su.latex.Macro(f"THead-qual-{macro_cat}").use()]
                    + [
                        su.latex.Macro(f"qual-{s}-{macro_cat}-pct").use()
                        for s in suffixes
                    ]
                )
            )
            latex_file.append(r"\\")

        latex_file.append(r"\bottomrule")
        latex_file.append(r"\end{tabular}")
        latex_file.append(r"\end{center}")
        latex_file.append(r"\end{small}")
        latex_file.append(r"\end{table}")
        latex_file.save()
        logger.info(f"Wrote qualitative table to {output_path}")


if __name__ == "__main__":
    su.log.setup(Macros.log_file)
    CLI(TableGen, as_positional=False)
