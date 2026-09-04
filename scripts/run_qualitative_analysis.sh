#!/usr/bin/env bash
#
# Score the manual inspection of the passing outputs.
#
# Every method whose generated code passes all its tests was read by hand and
# labelled: is the retrofit semantically equivalent to the original, and if not,
# how does it fail?  This turns the annotation stores under annotations/ into
# the summary files under _work/results/qualitative/.
#
# Run this before run_paper_pipeline.sh.  Python only; takes minutes.

set -euo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="analyze"

show_help() {
    cat <<EOF
Usage: ${0##*/} [OPTIONS]

Score the manual inspection of the passing outputs.
With no options, every configuration is scored -- the usual invocation.

OPTIONS:
    -c, --compare       Also print the category-by-category comparison between
                        the baseline and the full-context prompt (default: on
                        as part of the analysis)
    -m, --find-missing  List target methods that pass but carry no annotation,
                        i.e. the work still to be done.  Produces no output
                        files.
    -h, --help          Show this message

EXAMPLES:
    ${0##*/}            # score everything -- run this before run_paper_pipeline.sh
    ${0##*/} -m         # just list the passing outputs that carry no annotation
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
    -c | --compare)      MODE="analyze"; shift ;;
    -m | --find-missing) MODE="find_missing"; shift ;;
    -h | --help)         show_help; exit 0 ;;
    *) echo "Error: unknown option: $1" >&2; echo; show_help; exit 1 ;;
    esac
done

# shellcheck disable=SC1091
source "${_here}/helper/env.sh"
# shellcheck disable=SC1091
source "${_here}/helper/config.sh"

cd "$PYTHON_DIR"

MAIN_LLM_TYPE="$(llm_type_of "$MAIN_MODEL")"

qa() { python -m throwgen.utils.qualitative_analysis "$@"; }

if [[ "$MODE" == "find_missing" ]]; then
    echo "Target methods that pass but have no annotation:"
    qa find_missing_ids \
        --dataset_name="$TEST_DATASET_NAME" \
        --llm_type="$MAIN_LLM_TYPE" \
        --model_name="$MAIN_MODEL" \
        --prompt_gen_type="${MAIN_PROMPT_TYPES[1]}" \
        --setup="$SETUP"
    exit 0
fi

# One summary per prompt: how many passing outputs are genuinely equivalent,
# and how the rest are distributed over the false-positive categories.
for prompt in "${MAIN_PROMPT_TYPES[@]}"; do
    echo "=== Scoring annotations for $prompt ==="
    qa run_analysis --dataset_name="$TEST_DATASET_NAME" --prompt_gen_type="$prompt"
done

# The same scoring restricted to the target methods both prompts solve, so the
# two are compared on identical inputs rather than on the sets each happened to
# get right.
echo "=== Scoring the target methods both prompts solve ==="
qa run_analysis_same_samples \
    --dataset_name="$TEST_DATASET_NAME" \
    --prompt_gen_type_1="${MAIN_PROMPT_TYPES[0]}" \
    --prompt_gen_type_2="${MAIN_PROMPT_TYPES[1]}"

echo "=== Category-by-category comparison ==="
qa compare_category \
    --prompt_gen_type_1="${MAIN_PROMPT_TYPES[0]}" \
    --prompt_gen_type_2="${MAIN_PROMPT_TYPES[1]}" \
    --show_semantic_match_diff=True

echo
echo "=========================================="
echo "Wrote _work/results/qualitative/"
echo "Next: scripts/run_paper_pipeline.sh -q"
echo "=========================================="
