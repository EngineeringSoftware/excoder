#!/usr/bin/env bash
# The single source of truth for every model, prompt and dataset name the
# paper depends on.  All four pipelines read it.

# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

# NE2E inputs, under _work/data/etestgen.
readonly NE2E_TEST_DATASET="mut2e-new"
readonly NE2E_VAL_DATASET="nebt-data_val"

# The evaluation set: every table and figure in the paper is computed over it.
readonly TEST_DATASET_NAME="real-mega-test-data-with-exception-with-project-with-gold-with-throw"
readonly VAL_DATASET_NAME="mega-val-data-with-exception-with-project-with-gold-with-throw"
readonly ALL_DATASET_NAME="all-data"

# Funnel stages the data-collection section quotes counts for.
readonly COLLECTED_DATASET_NAME="real-non-direct-mega-test-data"
readonly DIRECT_DATASET_NAME="real-mega-test-data"
readonly EXCEPTION_DATASET_NAME="real-mega-test-data-with-exception"
readonly GOLD_DATASET_NAME="real-mega-test-data-with-exception-with-project-with-gold"

# ---------------------------------------------------------------------------
# Setups
# ---------------------------------------------------------------------------

readonly SETUP="multi_ebt"
readonly REPAIR_SETUP="repair"
readonly MAX_REPAIR_ITERATION=4

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

# The five models in the model-comparison table.
declare -a MODELS=(
    "qwen2.5-coder:7b-instruct-q8_0"
    "llama3.1:8b-instruct-q8_0"
    "phi4:14b-q8_0"
    "qwen2.5-coder:32b-instruct-q8_0"
    "gpt-5-mini"
)

# Used for the prompt ablation, the repair loop, the figures and the
# qualitative analysis.
readonly MAIN_MODEL="qwen2.5-coder:32b-instruct-q8_0"

declare -A MODEL_LLM_TYPES=(
    ["qwen2.5-coder:7b-instruct-q8_0"]="llama_cpp"
    ["llama3.1:8b-instruct-q8_0"]="llama_cpp"
    ["phi4:14b-q8_0"]="llama_cpp"
    ["qwen2.5-coder:32b-instruct-q8_0"]="llama_cpp"
    ["gpt-5-mini"]="azure"
)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

# The two prompts every model is run with.
declare -a MAIN_PROMPT_TYPES=(
    "base"
    "tuctn-all-info"
)

# Every prompt the main model is run with.
declare -a PROMPT_TYPES=(
    "base"
    "tuctn-all-info"
    "cmtu"
    "only-avsym"
    "only-lcov"
    "only-nebt"
    "only-threxc"
)

# base_experiment.PROMPT defines more variants than the paper reports; add a
# name here to run one.

declare -a REPAIR_PROMPT_TYPES=(
    "base-repair"
    "tuctn-all-info-repair"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# llm_type_of <model-name> -> llama_cpp | azure
llm_type_of() {
    local t="${MODEL_LLM_TYPES[$1]}"
    if [[ -z "$t" ]]; then
        echo "config.sh: unknown model '$1'" >&2
        return 1
    fi
    echo "$t"
}
