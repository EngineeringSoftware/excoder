#!/usr/bin/env bash
#
# Turn the evaluation results under _work/results into every number, table and
# figure in papers/issre26.
#
# Runs entirely on the artifacts that ship here -- no models, no Java, no GPU --
# and finishes in minutes.  Stage order matters and is handled for you: metrics
# are combined first, pass@k comes from the combined files, and every table and
# figure reads pass@k.

set -euo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_COMBINE_TESTS=false
RUN_PASS_AT_K=false
RUN_DATA_STAT_TABLE=false
RUN_RESULT_NUMBERS=false
RUN_BOLD=false
RUN_RESULT_TABLES=false
RUN_FIGURES=false
RUN_QUALITATIVE=false

# Suffix for generated macro/label names; empty for the paper.
TABLE_TAG=""

show_help() {
    cat <<EOF
Usage: ${0##*/} [OPTIONS]

Generate the ISSRE'26 numbers, tables and figures from _work/results.
With no options, every stage runs in dependency order (same as --all).

OPTIONS:
    -c, --combine-tests     Combine EBT/NEBT/tool per-sample metrics
    -k, --pass-at-k         Compute pass@k
    -s, --data-stat-table   Dataset statistics numbers and tables
    -n, --result-numbers    Per-configuration result macros
    -b, --bold              Bold the best cell per column
    -t, --result-tables     Result tables
    -f, --figures           Figures
    -q, --qualitative       Qualitative numbers, table and agreement
    -a, --all               Every step above, in dependency order
    -h, --help              Show this message

EXAMPLES:
    ${0##*/}                # every stage, in order -- the usual invocation
    ${0##*/} -n -b -t       # just rebuild the tables from existing pass@k files
EOF
}


while [[ $# -gt 0 ]]; do
    case "$1" in
    -c | --combine-tests)   RUN_COMBINE_TESTS=true; shift ;;
    -k | --pass-at-k)       RUN_PASS_AT_K=true; shift ;;
    -s | --data-stat-table) RUN_DATA_STAT_TABLE=true; shift ;;
    -n | --result-numbers)  RUN_RESULT_NUMBERS=true; shift ;;
    -b | --bold)            RUN_BOLD=true; shift ;;
    -t | --result-tables)   RUN_RESULT_TABLES=true; shift ;;
    -f | --figures)         RUN_FIGURES=true; shift ;;
    -q | --qualitative)     RUN_QUALITATIVE=true; shift ;;
    -a | --all)             RUN_COMBINE_TESTS=true
                            RUN_PASS_AT_K=true
                            RUN_DATA_STAT_TABLE=true
                            RUN_RESULT_NUMBERS=true
                            RUN_BOLD=true
                            RUN_RESULT_TABLES=true
                            RUN_FIGURES=true
                            RUN_QUALITATIVE=true; shift ;;
    -h | --help)            show_help; exit 0 ;;
    *) echo "Error: unknown option: $1" >&2; echo; show_help; exit 1 ;;
    esac
done

# No stage selected means all of them, in dependency order.
_stages_selected="${RUN_COMBINE_TESTS}${RUN_PASS_AT_K}${RUN_DATA_STAT_TABLE}"
_stages_selected+="${RUN_RESULT_NUMBERS}${RUN_BOLD}${RUN_RESULT_TABLES}"
_stages_selected+="${RUN_FIGURES}${RUN_QUALITATIVE}"
if [[ "$_stages_selected" != *true* ]]; then
    RUN_COMBINE_TESTS=true
    RUN_PASS_AT_K=true
    RUN_DATA_STAT_TABLE=true
    RUN_RESULT_NUMBERS=true
    RUN_BOLD=true
    RUN_RESULT_TABLES=true
    RUN_FIGURES=true
    RUN_QUALITATIVE=true
fi
unset _stages_selected

# shellcheck disable=SC1091
source "${_here}/helper/env.sh"
# shellcheck disable=SC1091
source "${_here}/helper/config.sh"
# shellcheck disable=SC1091
source "${_here}/helper/generate_number.sh"

cd "$PYTHON_DIR"

MAIN_LLM_TYPE="$(llm_type_of "$MAIN_MODEL")"

banner() {
    echo
    echo "=========================================="
    echo "$*"
    echo "=========================================="
}

tg() { python -m throwgen.table_gen --dataset_name="$1" "${@:2}"; }

# Add a macro file to the paper's top-level all-numbers.tex if absent.
link_numbers() {
    local entry="$1"
    if ! grep -qF "$entry" "$PAPER_DIR/tables/all-numbers.tex"; then
        echo "\\input{${entry}}" >> "$PAPER_DIR/tables/all-numbers.tex"
    fi
}

# for_each_configuration <callback> -- once per configuration the paper reports.
for_each_configuration() {
    local cb="$1" prompt model llm_type iter

    for prompt in "${PROMPT_TYPES[@]}"; do
        "$cb" "$MAIN_LLM_TYPE" "$MAIN_MODEL" "$SETUP" "$prompt"
    done

    for prompt in "${REPAIR_PROMPT_TYPES[@]}"; do
        for iter in $(seq 1 "$MAX_REPAIR_ITERATION"); do
            "$cb" "$MAIN_LLM_TYPE" "$MAIN_MODEL" "$REPAIR_SETUP" "${prompt}@${iter}"
        done
    done

    for prompt in "${MAIN_PROMPT_TYPES[@]}"; do
        for model in "${MODELS[@]}"; do
            [[ "$model" == "$MAIN_MODEL" ]] && continue  # already covered above
            llm_type="$(llm_type_of "$model")"
            "$cb" "$llm_type" "$model" "$SETUP" "$prompt"
        done
    done
}

# ---------------------------------------------------------------------------
# Combine tests
# ---------------------------------------------------------------------------
combine_one() {
    local llm_type="$1" model="$2" setup="$3" prompt="$4" fn
    echo "combining: $model $prompt ($setup)"
    for fn in get_combined_test_metrics get_combined_with_tools_metrics; do
        python -m throwgen.eval.transform_results.combine_tests_metrics "$fn" \
            --dataset_name="$TEST_DATASET_NAME" --llm_type="$llm_type" \
            --model_name="$model" --setup="$setup" --prompt_gen_type="$prompt"
    done
}

if [[ "$RUN_COMBINE_TESTS" = true ]]; then
    banner "Combining per-sample test metrics"
    for_each_configuration combine_one
fi

# ---------------------------------------------------------------------------
# pass@k
# ---------------------------------------------------------------------------
pass_at_k_one() {
    local llm_type="$1" model="$2" setup="$3" prompt="$4" mt
    echo "pass@k: $model $prompt ($setup)"
    for mt in run-ebts run-all run-all-with-tools; do
        python -m throwgen.eval.transform_results.pass_at_k_metrics \
            --dataset_name="$TEST_DATASET_NAME" --llm_type="$llm_type" \
            --model_name="$model" --setup="$setup" --prompt_gen_type="$prompt" \
            --metrics_type="$mt"
    done
}

if [[ "$RUN_PASS_AT_K" = true ]]; then
    banner "Computing pass@k"
    for_each_configuration pass_at_k_one
fi

# ---------------------------------------------------------------------------
# Dataset statistics (Table I and the throw-count table)
# ---------------------------------------------------------------------------
# Counts come from the shipped datasets; nothing here re-derives them.
stats_for() {
    local ds="$1"
    python -m throwgen.utils.count_data_perks count_throw --dataset_name="$ds"
    python -m throwgen.dataset.stats --dataset_name="$ds"
    tg "$ds" make_stats_numbers
    tg "$ds" collect_all_macros
    link_numbers "tables/${ds}/all-numbers"
}

if [[ "$RUN_DATA_STAT_TABLE" = true ]]; then
    banner "Generating dataset statistics"

    stats_for "$TEST_DATASET_NAME"
    stats_for "$VAL_DATASET_NAME"
    stats_for "$ALL_DATASET_NAME"

    # dataset_stats.json is NOT recomputed for the funnel stages: the gold
    # stage is counted before its compile filter, so re-deriving it here would
    # renumber the paper.
    for ds in "$COLLECTED_DATASET_NAME" "$DIRECT_DATASET_NAME" \
              "$EXCEPTION_DATASET_NAME" "$GOLD_DATASET_NAME"; do
        tg "$ds" make_stats_numbers
        tg "$ds" collect_all_macros
        link_numbers "tables/${ds}/all-numbers"
    done

    # Inline funnel percentages; count_no_throw_error has to run first.
    python -m throwgen.utils.count_data_perks count_no_throw_error \
        --dataset_name="$GOLD_DATASET_NAME"
    tg "$TEST_DATASET_NAME" make_data_funnel_numbers \
        --collected_dataset_name="$COLLECTED_DATASET_NAME" \
        --direct_dataset_name="$DIRECT_DATASET_NAME" \
        --gold_dataset_name="$GOLD_DATASET_NAME"
    tg "$TEST_DATASET_NAME" collect_all_macros

    tg "$TEST_DATASET_NAME" make_all_stats_tables \
        --val_dataset_name="$VAL_DATASET_NAME" \
        --all_dataset_name="$ALL_DATASET_NAME"
fi

# ---------------------------------------------------------------------------
# Result numbers
# ---------------------------------------------------------------------------
numbers_one() {
    local llm_type="$1" model="$2" setup="$3" prompt="$4"
    echo "numbers: $model $prompt ($setup)"
    generate_number "$model" "$llm_type" "$TEST_DATASET_NAME" "$setup" "$prompt"
}

if [[ "$RUN_RESULT_NUMBERS" = true ]]; then
    banner "Generating result numbers"
    for_each_configuration numbers_one

    # Gains quoted inline in results.tex.
    tg "$TEST_DATASET_NAME" make_prompt_improvement_numbers --setup="$SETUP"
    tg "$TEST_DATASET_NAME" make_repair_improvement_numbers \
        --setup="$SETUP" --repair_setup="$REPAIR_SETUP" \
        --iteration="$MAX_REPAIR_ITERATION"
    tg "$TEST_DATASET_NAME" collect_all_macros
fi

# ---------------------------------------------------------------------------
# Bold
# ---------------------------------------------------------------------------
if [[ "$RUN_BOLD" = true ]]; then
    banner "Marking the best cell in each column"
    tg "$TEST_DATASET_NAME" make_prompt_comp_bold --setup="$SETUP"
    tg "$TEST_DATASET_NAME" make_model_comp_bold --setup="$SETUP"
    tg "$TEST_DATASET_NAME" make_repair_comp_bold --setup="$SETUP" \
        --repair_setup="$REPAIR_SETUP"
fi

# ---------------------------------------------------------------------------
# Result tables
# ---------------------------------------------------------------------------
if [[ "$RUN_RESULT_TABLES" = true ]]; then
    banner "Generating result tables"
    tg "$TEST_DATASET_NAME" make_model_comp_table --setup="$SETUP" --tag="$TABLE_TAG"
    tg "$TEST_DATASET_NAME" make_prompt_comp_table --setup="$SETUP" --tag="$TABLE_TAG"
    tg "$TEST_DATASET_NAME" make_repair_comp_table --setup="$SETUP" \
        --repair_setup="$REPAIR_SETUP" --tag="$TABLE_TAG"
    # make_complete_repair_comp_table (one row per repair round) is not called:
    # only the appendix printed it, and the appendix is not part of the paper.
    tg "$TEST_DATASET_NAME" collect_all_macros
fi

# ---------------------------------------------------------------------------
# Qualitative analysis
# ---------------------------------------------------------------------------
if [[ "$RUN_QUALITATIVE" = true ]]; then
    banner "Generating qualitative numbers and agreement"

    # make_qualitative_numbers only warns about a missing summary and carries
    # on, which would leave the macro file short a few entries and fail the
    # LaTeX build with an undefined control sequence a long way from the cause.
    # Fail here instead, where the fix is obvious.
    for prompt in "${MAIN_PROMPT_TYPES[@]}"; do
        for prefix in qual_summary same_samples_qual_summary; do
            f="${WORK_DIR}/results/qualitative/${prefix}_${prompt}.json"
            if [[ ! -f "$f" ]]; then
                echo "Error: missing $f" >&2
                echo "       Run scripts/run_qualitative_analysis.sh first." >&2
                exit 1
            fi
        done
    done

    tg "$TEST_DATASET_NAME" make_qualitative_numbers \
        --tags='["base", "tuctn-all-info"]' --over_all_methods=true
    tg "$TEST_DATASET_NAME" make_qualitative_table --tags='["base", "tuctn-all-info"]'

    # Cohen's kappa between the two annotation stores, scored over every
    # passing ERC exactly as the qualitative numbers are.
    for prompt in "${MAIN_PROMPT_TYPES[@]}"; do
        python -m throwgen.utils.qualitative_analysis run_agreement \
            --dataset_name="$TEST_DATASET_NAME" --llm_type="$MAIN_LLM_TYPE" \
            --model_name="$MAIN_MODEL" --prompt_gen_type="$prompt" --setup="$SETUP"
    done
    tg "$TEST_DATASET_NAME" make_agreement_numbers --tags='["base", "tuctn-all-info"]'
    link_numbers "tables/agreement-numbers"
fi

# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
if [[ "$RUN_FIGURES" = true ]]; then
    banner "Generating figures"

    # Success rate vs method length and cyclomatic complexity.
    python -m throwgen.figures success_vs_complexity \
        --dataset_name="$TEST_DATASET_NAME" \
        --prompt_gen_a="${MAIN_PROMPT_TYPES[0]}" \
        --prompt_gen_b="${MAIN_PROMPT_TYPES[1]}" \
        --llm_type="$MAIN_LLM_TYPE" --model_name="$MAIN_MODEL" --setup="$SETUP"

    # pass@5 at each repair round.
    python -m throwgen.figures repair_comparison \
        --dataset_name="$TEST_DATASET_NAME" \
        --prompt_gen_a="${REPAIR_PROMPT_TYPES[0]}" \
        --prompt_gen_b="${REPAIR_PROMPT_TYPES[1]}" \
        --llm_type="$MAIN_LLM_TYPE" --model_name="$MAIN_MODEL" \
        --max_iterations="$MAX_REPAIR_ITERATION" \
        --metrics_type="run-all" --pass_at_k=5

    # Which methods each prompt solves, and how they overlap.
    python -m throwgen.figures result_venn \
        --dataset_name="$TEST_DATASET_NAME" \
        --prompt_gen_a="${MAIN_PROMPT_TYPES[0]}" \
        --prompt_gen_b="${MAIN_PROMPT_TYPES[1]}" \
        --llm_type="$MAIN_LLM_TYPE" --model_name="$MAIN_MODEL" \
        --metrics_type="run-all"

    python -m throwgen.figures qualitative_venn \
        --dataset_name="$TEST_DATASET_NAME" \
        --prompt_a="${MAIN_PROMPT_TYPES[0]}" \
        --prompt_b="${MAIN_PROMPT_TYPES[1]}" \
        --llm_type="$MAIN_LLM_TYPE" --model_name="$MAIN_MODEL" \
        --metrics_type="run-all"
fi

echo
echo "=========================================="
echo "Paper pipeline finished."
echo "Build the PDF with: make -C papers/issre26"
echo "=========================================="
