#!/usr/bin/env bash
#
# Run the LLM experiments the paper reports, and evaluate the predictions.
#
# Three groups, one per result table: --model-comparison, --prompt-comparison
# and --repair.  Each runs the LLM (stage e), then evaluates against the
# developer-written tests (r) and the Randoop/EvoSuite tests (t).  Predictions
# are cached; the evaluation stages are not.
#
# WARNING: needs the GGUF weights, a GPU, Azure credentials for gpt-5-mini and
# ~100 buildable Java projects.  Takes days.  Pass --mock to print the plan.

set -euo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_GGUF_DIR="${GGUF_DIR:-}"
_CMD="ert"           # e: infer, r: EBT/NEBT eval, t: tool-test eval
_SAMPLE_SIZE="10"    # the paper reports pass@1, @5 and @10, so 10 samples
_TEMP="0.8"
_BATCH_SIZE="1"
_PARALLEL_SLOTS=""   # empty = auto (sample_size * batch_size)
_CTX_PER_SLOT="8192" # tokens per slot; total ctx = parallel_slots * ctx_per_slot
_EVAL_WORKERS="10"
_MAX_TOOL_TESTS="400" # combined Randoop+EvoSuite cap per target method
MOCK=0

RUN_MODEL_COMPARISON=false
RUN_PROMPT_COMPARISON=false
RUN_REPAIR=false
DOWNLOAD_MODELS=false

show_help() {
    cat <<EOF
Usage: ${0##*/} [OPTIONS]

Run the ExCoder LLM experiments and evaluate the predictions.
With no options, all three experiment groups run in order (same as --all).

OPTIONS:
    -m, --model-comparison      Every model, base + full-context prompt
    -p, --prompt-comparison     Main model, every prompt ablation
    -r, --repair                Main model, ${MAX_REPAIR_ITERATION:-4} rounds of self-repair
    -a, --all                   All three groups
    -M, --mock                  Dry run: print the plan, run nothing
    -d, --download-models       Fetch the GGUF weights first
    -g, --gguf-dir DIR          Directory holding the GGUF weights
    -c, --command CMD           Stages to run, any of e/r/t (default: $_CMD)
    -n, --sample-size NUM       Samples per prompt (default: $_SAMPLE_SIZE)
    -t, --temp FLOAT            Sampling temperature (default: $_TEMP)
    -b, --batch-size NUM        Prompts per LLM request (default: $_BATCH_SIZE)
    -P, --parallel-slots NUM    llama-server -np slots (default: samples * batch)
    -C, --ctx-per-slot NUM      KV cache tokens per slot (default: $_CTX_PER_SLOT)
    -w, --eval-workers NUM      Workers for the evaluation stages (default: $_EVAL_WORKERS)
    -T, --max-tool-tests NUM    Tool tests per target method (default: $_MAX_TOOL_TESTS)
    -h, --help                  Show this message

EXAMPLES:
    ${0##*/} --mock             # print everything the paper's results required
    ${0##*/} -m -g /models      # reproduce the model-comparison table
EOF
}


while [[ $# -gt 0 ]]; do
    case "$1" in
    -m | --model-comparison)  RUN_MODEL_COMPARISON=true; shift ;;
    -p | --prompt-comparison) RUN_PROMPT_COMPARISON=true; shift ;;
    -r | --repair)            RUN_REPAIR=true; shift ;;
    -a | --all)               RUN_MODEL_COMPARISON=true
                              RUN_PROMPT_COMPARISON=true
                              RUN_REPAIR=true; shift ;;
    -M | --mock)              MOCK=1; shift ;;
    -d | --download-models)   DOWNLOAD_MODELS=true; shift ;;
    -g | --gguf-dir)          _GGUF_DIR="$2"; shift 2 ;;
    -c | --command)           _CMD="$2"; shift 2 ;;
    -n | --sample-size)       _SAMPLE_SIZE="$2"; shift 2 ;;
    -t | --temp)              _TEMP="$2"; shift 2 ;;
    -b | --batch-size)        _BATCH_SIZE="$2"; shift 2 ;;
    -P | --parallel-slots)    _PARALLEL_SLOTS="$2"; shift 2 ;;
    -C | --ctx-per-slot)      _CTX_PER_SLOT="$2"; shift 2 ;;
    -w | --eval-workers)      _EVAL_WORKERS="$2"; shift 2 ;;
    -T | --max-tool-tests)    _MAX_TOOL_TESTS="$2"; shift 2 ;;
    -h | --help)              show_help; exit 0 ;;
    *) echo "Error: unknown option: $1" >&2; echo; show_help; exit 1 ;;
    esac
done

# No group selected means all of them.  Checked after parsing so that --mock
# or -g DIR on their own still run everything.
if [[ "$RUN_MODEL_COMPARISON$RUN_PROMPT_COMPARISON$RUN_REPAIR" != *true* ]]; then
    RUN_MODEL_COMPARISON=true
    RUN_PROMPT_COMPARISON=true
    RUN_REPAIR=true
fi

export THROWGEN_MOCK="$MOCK"
# shellcheck disable=SC1091
source "${_here}/helper/env.sh"
# shellcheck disable=SC1091
source "${_here}/helper/config.sh"
# shellcheck disable=SC1091
source "${_here}/helper/do_experiment.sh"

export THROWGEN_EVAL_WORKERS="$_EVAL_WORKERS"
export THROWGEN_MAX_TOOL_TESTS="$_MAX_TOOL_TESTS"

if [[ "$MOCK" != 1 && "$_CMD" == *e* && -z "$_GGUF_DIR" ]]; then
    echo "Error: --gguf-dir (or \$GGUF_DIR) is required to run local models." >&2
    exit 1
fi

# extra_args_for <llm_type>
extra_args_for() {
    local args="--sample_size=$_SAMPLE_SIZE --temp=$_TEMP --batch_size=$_BATCH_SIZE"
    if [[ "$1" == "llama_cpp" ]]; then
        args="$args --gguf_dir=$_GGUF_DIR"
        [[ -n "$_PARALLEL_SLOTS" ]] && args="$args --parallel_slots=$_PARALLEL_SLOTS"
        args="$args --ctx_per_slot=$_CTX_PER_SLOT"
    fi
    echo "$args"
}

# huggingface_hub skips files it already has, so this is safe to re-run.
if [[ "$DOWNLOAD_MODELS" = true ]]; then
    echo "--- Downloading GGUF weights into $_GGUF_DIR ---"
    for model in "${MODELS[@]}"; do
        [[ "$(llm_type_of "$model")" == "llama_cpp" ]] || continue
        echo "  $model"
        ( cd "$PYTHON_DIR" && run python -c \
            "from throwgen.llm.llama_cpp_experiment import LlamaCppExperiment; \
             LlamaCppExperiment.download_model_gguf('$model', '$_GGUF_DIR')" )
    done
fi

# The Randoop / EvoSuite / JUnit jars; download_jars is idempotent.
if [[ "$_CMD" == *t* ]]; then
    echo "--- Ensuring the Java tool jars are downloaded ---"
    ( cd "$PYTHON_DIR" && run python -c \
        "from etestgen.tools.program_analysis_based import GenerateTests; GenerateTests().download_jars()" )
fi

echo "============================================"
echo "ExCoder experiment pipeline"
echo "============================================"
echo "Dataset:        $TEST_DATASET_NAME"
echo "Setup:          $SETUP"
echo "Stages:         $_CMD"
echo "Samples / temp: $_SAMPLE_SIZE / $_TEMP"
echo "Eval workers:   $_EVAL_WORKERS"
echo "Max tool tests: $_MAX_TOOL_TESTS"
[[ "$MOCK" == 1 ]] && echo "Mode:           MOCK (nothing will be executed)"
echo "============================================"

# ---------------------------------------------------------------------------
# Model comparison
# ---------------------------------------------------------------------------
if [[ "$RUN_MODEL_COMPARISON" = true ]]; then
    echo; echo "### Model comparison"
    for model in "${MODELS[@]}"; do
        llm_type="$(llm_type_of "$model")"
        extra_args="$(extra_args_for "$llm_type")"
        for prompt in "${MAIN_PROMPT_TYPES[@]}"; do
            echo "--- $model | $llm_type | $prompt"
            # $extra_args is intentionally unquoted (word splitting).
            do_experiment "$model" "$llm_type" "$TEST_DATASET_NAME" "$SETUP" \
                "$prompt" "$_CMD" 1 $extra_args
        done
    done
fi

# ---------------------------------------------------------------------------
# Prompt comparison
# ---------------------------------------------------------------------------
if [[ "$RUN_PROMPT_COMPARISON" = true ]]; then
    echo; echo "### Prompt comparison"
    llm_type="$(llm_type_of "$MAIN_MODEL")"
    extra_args="$(extra_args_for "$llm_type")"
    for prompt in "${PROMPT_TYPES[@]}"; do
        echo "--- $MAIN_MODEL | $llm_type | $prompt"
        do_experiment "$MAIN_MODEL" "$llm_type" "$TEST_DATASET_NAME" "$SETUP" \
            "$prompt" "$_CMD" 1 $extra_args
    done
fi

# ---------------------------------------------------------------------------
# Self-repair loop
# ---------------------------------------------------------------------------
# Round i prompts the model with the test failures recorded for round i-1, so
# the rounds must run in order and each round's evaluation must have finished.
if [[ "$RUN_REPAIR" = true ]]; then
    echo; echo "### Self-repair (${MAX_REPAIR_ITERATION} rounds)"
    llm_type="$(llm_type_of "$MAIN_MODEL")"
    extra_args="$(extra_args_for "$llm_type")"
    for prompt in "${REPAIR_PROMPT_TYPES[@]}"; do
        for i in $(seq 1 "$MAX_REPAIR_ITERATION"); do
            echo "--- $MAIN_MODEL | ${prompt}@${i}"
            do_experiment "$MAIN_MODEL" "$llm_type" "$TEST_DATASET_NAME" \
                "$REPAIR_SETUP" "${prompt}@${i}" "$_CMD" 1 $extra_args
        done
    done
fi

echo
echo "============================================"
echo "Experiment pipeline finished."
echo "============================================"
