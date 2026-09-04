#!/usr/bin/env bash
# do_experiment <model> <llm_type> <dataset> <setup> <prompt_gen_type> <cmd> <num_workers> [extra args...]
#
# `cmd` selects the stages to run; the letters may be combined ("ert"):
#
#   e  generate predictions with the LLM
#   r  run the developer-written tests (EBTs and NEBTs) against them
#   t  run the tool-generated tests (Randoop and EvoSuite) against them
#
# THROWGEN_EVAL_WORKERS and THROWGEN_MAX_TOOL_TESTS must be exported by the
# caller; they are deliberately not defaulted here, because a wrong value
# silently changes how much of the tool-test suite an evaluation covers.
function do_experiment {
    local model_name="$1"
    local model_type="$2"
    local dataset_name="$3"
    local setup_type="$4"
    local prompt_gen_type="$5"
    local cmd_select="$6"
    local num_workers="$7"
    local original_dir="$PWD"
    # shift 7 positional params; if fewer than 7 were given, shift only what
    # exists (bash leaves $@ unchanged when N > $#).
    [[ $# -ge 7 ]] && shift 7 || shift $#
    local kwargs="$*"
    local eval_workers="$THROWGEN_EVAL_WORKERS"
    local max_tool_tests="$THROWGEN_MAX_TOOL_TESTS"

    if [[ -z "$eval_workers" || -z "$max_tool_tests" ]]; then
        echo "do_experiment: THROWGEN_EVAL_WORKERS and THROWGEN_MAX_TOOL_TESTS must be set" >&2
        return 1
    fi

    cd "$PYTHON_DIR" || return 1
    echo "Command: $cmd_select, Workers: $num_workers"

    if [[ "$cmd_select" == *e* ]]; then
        # llama_cpp derives its worker count from the detected GPUs; the other
        # engines take --num_workers.
        local worker_arg=""
        [[ "$model_type" != "llama_cpp" ]] && worker_arg="--num_workers=$num_workers"
        # $kwargs and $worker_arg are intentionally unquoted (word splitting).
        run python -m "throwgen.llm.${model_type}_experiment" --model="$model_name" \
            $worker_arg $kwargs \
            "do_${setup_type}_experiment" --dataset_name="$dataset_name" \
            --prompt_gen_type="$prompt_gen_type" || { cd "$original_dir"; return 1; }
    fi

    if [[ "$cmd_select" == *r* ]]; then
        local test_type
        for test_type in ebts nebts; do
            run python -m throwgen.eval.metrics.runtime_metrics \
                --dataset_name="$dataset_name" --prompt_gen_type="$prompt_gen_type" \
                --llm_type="$model_type" --model_name="$model_name" --setup="$setup_type" \
                --test_type="$test_type" --num_workers="$eval_workers" \
                run_eval || { cd "$original_dir"; return 1; }
        done
    fi

    if [[ "$cmd_select" == *t* ]]; then
        run python -m throwgen.eval.metrics.tool_runtime_metrics \
            --dataset_name="$dataset_name" --prompt_gen_type="$prompt_gen_type" \
            --llm_type="$model_type" --model_name="$model_name" --setup="$setup_type" \
            --num_workers="$eval_workers" --max_tests_per_sample="$max_tool_tests" \
            run_eval || { cd "$original_dir"; return 1; }
    fi

    cd "$original_dir" || return 1
}
