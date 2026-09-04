#!/usr/bin/env bash
#
# Build the ExCoder dataset: mine the subject repositories, then run the
# collected methods through the filter funnel.
#
# Stages, all run by default:
#   collect  mine the NE2E datasets from the repository lists
#   test     the evaluation funnel and its real-* twins
#   tools    Randoop and EvoSuite tests for the evaluation set
#   val      the validation funnel
#   merge    the two final stages, merged
#
# WARNING: clones and builds hundreds of Java projects with Maven; takes days.
# Pass --mock for a dry run.

set -euo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MOCK=0
STAGES="all"

show_help() {
    cat <<EOF
Usage: ${0##*/} [OPTIONS]

Regenerate the ExCoder dataset, from the repository list to the evaluation set.
With no options, every stage runs in order (same as --stage all).

STAGES:
    collect  mine the NE2E inputs from the repository lists
    test     the evaluation funnel and its real-* twins
    tools    Randoop and EvoSuite tests for the evaluation set
    val      the validation funnel
    merge    all-data (the test and validation sets merged)
    all      all five, in that order  [default]

OPTIONS:
    -s, --stage STAGE   One of the stages above (default: all)
    -m, --mock          Dry run: print each step and verify the shipped
                        datasets exist, without cloning or building anything.
    -h, --help          Show this message.

EXAMPLES:
    ${0##*/} --mock             # dry run against the shipped datasets
    ${0##*/}                    # every stage, in order (days!)
    ${0##*/} --stage test       # rebuild only the evaluation funnel
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
    -s | --stage) STAGES="$2"; shift 2 ;;
    -m | --mock)  MOCK=1; shift ;;
    -h | --help)  show_help; exit 0 ;;
    *) echo "Error: unknown option: $1" >&2; echo; show_help; exit 1 ;;
    esac
done

case "$STAGES" in
collect | test | tools | val | merge | all) ;;
*)
    echo "Error: unknown stage: $STAGES" >&2
    echo "       Expected one of: collect test tools val merge all" >&2
    exit 1
    ;;
esac

export THROWGEN_MOCK="$MOCK"
# shellcheck disable=SC1091
source "${_here}/helper/env.sh"
# shellcheck disable=SC1091
source "${_here}/helper/config.sh"
# shellcheck disable=SC1091
source "${_here}/helper/do_experiment.sh"

# The dummy model replays the original method, so the runtime evaluation can
# answer data-collection questions.  One worker: Maven-bound, not CPU-bound.
export THROWGEN_EVAL_WORKERS=1
export THROWGEN_MAX_TOOL_TESTS=0

cd "$PYTHON_DIR"

banner() {
    echo
    echo "=========================================="
    echo "$*"
    echo "=========================================="
}

mebt() { run python -m throwgen.dataset.multi_ebt_data "$@"; }

# Re-run the throw remover, which rewrites <dataset>/throw-rm-output.jsonl.
# The throw counts are tallied from that file, so every dataset the paper
# counts passes through here after its last membership-changing filter.
capture_throw_removal() {
    banner "Recording how the ERC was removed in $1"
    mebt update_dataset --base_dataset_name="$1" --out_dataset_name="$1" \
        --selected_extractor_names="['MUTNoThrowExtractor']"
}

# Carry the dummy run's metrics over to the dataset a filter just produced, so
# the next filter does not have to re-run Maven for rows that survived.
carry_metrics() {
    local from="$1" to="$2" prompt="$3"
    local m
    for m in run-ebts run-nebts; do
        run python -m throwgen.eval.transform_results.partial_metrics \
            get_partial_metrics --original_dataset_name="$from" \
            --new_dataset_name="$to" --llm_type=base --model_name=dummy \
            --setup=dummy --prompt_gen_type="$prompt" --metrics_type="$m"
    done
}

# ---------------------------------------------------------------------------
# The shared funnel: NE2E -> ...-with-throw
# ---------------------------------------------------------------------------
# $1 NE2E dataset name, $2 output prefix ("mega-test-data" / "mega-val-data").
build_funnel() {
    local ne2e="$1" name="$2" new

    banner "Converting $ne2e to multi-EBT data ($name)"
    mebt generate_dataset_from_ne2e --ne2e_dataset_name="$ne2e" --out_dataset_name="$name"
    mebt update_dataset --base_dataset_name="$name" --out_dataset_name="$name" \
        --selected_extractor_names="['MUTNoThrowExtractor']"
    [[ "$MOCK" == 1 ]] && expect_dataset "$name"

    banner "Dropping methods with no concrete exception type"
    new="${name}-with-exception"
    mebt filter_dataset --base_dataset_name="$name" --out_dataset_name="$new" \
        --selected_filter_names="['GenericExceptionFilter']"
    name="$new"
    [[ "$MOCK" == 1 ]] && expect_dataset "$name"

    banner "Dropping methods whose project cannot be resolved"
    new="${name}-with-project"
    mebt filter_dataset --base_dataset_name="$name" --out_dataset_name="$new" \
        --selected_filter_names="['NoProjectFilter']"
    name="$new"
    [[ "$MOCK" == 1 ]] && expect_dataset "$name"

    banner "Dropping methods whose EBTs do not pass as written (no gold)"
    do_experiment dummy base "$name" dummy mut er 1
    new="${name}-with-gold"
    mebt filter_dataset --base_dataset_name="$name" --out_dataset_name="$new" \
        --selected_filter_names="['NoGoldFilter']"
    carry_metrics "$name" "$new" mut
    name="$new"
    [[ "$MOCK" == 1 ]] && expect_dataset "$name"

    banner "Dropping methods whose EBTs still pass after the ERC is removed"
    do_experiment dummy base "$name" dummy mut_no_throw er 1
    new="${name}-with-throw"
    mebt filter_dataset --base_dataset_name="$name" --out_dataset_name="$new" \
        --selected_filter_names="['AutoPassFilter','CompileFilter']"
    carry_metrics "$name" "$new" mut
    carry_metrics "$name" "$new" mut_no_throw
    name="$new"
    [[ "$MOCK" == 1 ]] && expect_dataset "$name"

    banner "Extracting prompt context for $name"
    mebt update_dataset --base_dataset_name="$name" --out_dataset_name="$name" \
        --selected_extractor_names="['ClassInfoExtractor', 'NEBTExtractor', 'MethodInfoExtractor', 'UnreExceptionExtractor', 'ThrowInfoExtractor']"

    banner "Collecting line coverage of the ERC"
    do_experiment dummy base "$name" dummy mut_no_throw e 1
    run python -m throwgen.eval.metrics.coverage_metrics --dataset_name="$name" \
        --prompt_gen_type=mut_no_throw --llm_type=base --model_name=dummy \
        --setup=dummy --num_workers=1 run_eval

    banner "Collecting the exceptions thrown before the ERC (try/catch probe)"
    local try_name="try-catch-${name}"
    mebt update_dataset --base_dataset_name="$name" --out_dataset_name="$try_name" \
        --selected_extractor_names="['TryCatchAddExtractor']"
    do_experiment dummy base "$try_name" dummy mut_no_throw e 1
    run python -m throwgen.eval.metrics.coverage_metrics --dataset_name="$try_name" \
        --prompt_gen_type=mut_no_throw --llm_type=base --model_name=dummy \
        --setup=dummy --num_workers=6 run_eval
    mebt update_dataset --base_dataset_name="$name" --out_dataset_name="$name" \
        --selected_extractor_names="['CoverageExtractor', 'ThrownExceptionExtractor']"
    [[ "$MOCK" == 1 ]] && expect_dataset "$try_name"

    return 0
}

# ---------------------------------------------------------------------------
# collect: repository lists -> NE2E datasets
# ---------------------------------------------------------------------------
if [[ "$STAGES" == "all" || "$STAGES" == "collect" ]]; then
    # repos.json holds the repositories the experiments run on, repos_val.json
    # the ones the validation set is mined from.  They overlap, and a shared
    # project is not always pinned to the same commit in both, so each list
    # gets its own coverage directory.
    _repos="${REPOS_DIR}/filtered/repos.json"
    _repos_val="${REPOS_DIR}/filtered/repos_val.json"
    for _f in "$_repos" "$_repos_val"; do
        if [[ ! -f "$_f" ]]; then
            echo "Error: repository list not found: $_f" >&2
            exit 1
        fi
    done

    # mine_ne2e <repos-file> <coverage-dir> <output dataset name>
    #
    # Extraction always writes to _work/data/mut2e-new, so each call ends by
    # moving the result to _work/data/etestgen/ -- clearing the scratch
    # directory for the next call and publishing where the funnel expects it.
    mine_ne2e() {
        local repos_file="$1" cov_dir="$2" out_name="$3"

        banner "Collecting test coverage for ${out_name}"
        run python -m etestgen.eval.compute_etest_coverage compute_coverage_data \
            --out_dir="$cov_dir" --repos_file="$repos_file"

        banner "Computing coverage of the non-exception-based tests (${out_name})"
        run python -m etestgen.eval.compute_test_coverage compute_netest_coverage \
            --out_dir="$cov_dir" --repos_file="$repos_file"

        banner "Extracting the MUT2E dataset for ${out_name}"
        run rm -rf "${WORK_DIR}/data/mut2e-new"
        run python -m etestgen.eval.extract_etest_data_from_coverage \
            --coverage_dir="$cov_dir" --repos_file="$repos_file" \
            extract_mut2e_dataset

        banner "Extracting the guard condition from each stack trace (${out_name})"
        run python -m etestgen.eval.extract_etest_data_from_coverage \
            extract_conditions --dataset=mut2e-new

        banner "Pairing each EBT with the nEBTs covering the same method (${out_name})"
        run python -m etestgen.eval.get_ne_data collect_netest_data \
            --mut2e_data_dir="${WORK_DIR}/data/mut2e-new"

        banner "Publishing ${out_name} where the funnel expects it"
        run mkdir -p "${WORK_DIR}/data/etestgen"
        run rm -rf "${WORK_DIR}/data/etestgen/${out_name}"
        run mv "${WORK_DIR}/data/mut2e-new" \
            "${WORK_DIR}/data/etestgen/${out_name}"
    }

    mine_ne2e "$_repos"     "${WORK_DIR}/coverage-test" "$NE2E_TEST_DATASET"
    mine_ne2e "$_repos_val" "${WORK_DIR}/coverage-val"  "$NE2E_VAL_DATASET"

    if [[ "$STAGES" == "collect" ]]; then
        echo
        echo "NE2E collection finished.  Run --stage test (or no --stage) next."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# test split
# ---------------------------------------------------------------------------
if [[ "$STAGES" == "all" || "$STAGES" == "test" ]]; then
    banner "Collecting every target method (including indirect throws)"
    mebt generate_dataset_from_ne2e --ne2e_dataset_name="$NE2E_TEST_DATASET" \
        --out_dataset_name="non-direct-mega-test-data" --direct_throw=False
    [[ "$MOCK" == 1 ]] && expect_dataset "non-direct-mega-test-data"

    build_funnel "$NE2E_TEST_DATASET" "mega-test-data"

    # ProjectFilter keeps the evaluation projects and drops the held-out
    # validation ones, giving each stage a real-* twin.
    banner "Restricting each funnel stage to the evaluation projects"
    for stage in \
        "non-direct-mega-test-data" \
        "mega-test-data" \
        "mega-test-data-with-exception" \
        "mega-test-data-with-exception-with-project" \
        "mega-test-data-with-exception-with-project-with-gold" \
        "mega-test-data-with-exception-with-project-with-gold-with-throw"; do
        mebt filter_dataset --base_dataset_name="$stage" \
            --out_dataset_name="real-${stage}" \
            --selected_filter_names="['ProjectFilter']"
        [[ "$MOCK" == 1 ]] && expect_dataset "real-${stage}"
    done

    # The gold stage takes one more pass: CompileFilter drops the methods that
    # no longer compile once the ERC is removed.  Statistics are captured
    # BEFORE that filter -- the paper counts this stage pre-compile-filter, so
    # re-deriving them afterwards would renumber it.
    run python -m throwgen.dataset.stats --dataset_name="$GOLD_DATASET_NAME"

    # CompileFilter reads the dummy run's EBT results, carried across first.
    banner "Dropping gold-stage methods that stop compiling without the ERC"
    for prompt in mut mut_no_throw; do
        run python -m throwgen.eval.transform_results.partial_metrics \
            get_partial_metrics \
            --original_dataset_name="mega-test-data-with-exception-with-project-with-gold" \
            --new_dataset_name="$GOLD_DATASET_NAME" \
            --llm_type=base --model_name=dummy --setup=dummy \
            --prompt_gen_type="$prompt" --metrics_type=run-ebts
    done
    mebt filter_dataset --base_dataset_name="$GOLD_DATASET_NAME" \
        --out_dataset_name="$GOLD_DATASET_NAME" \
        --selected_filter_names="['CompileFilter']"
    [[ "$MOCK" == 1 ]] && expect_dataset "$GOLD_DATASET_NAME"

    capture_throw_removal "$TEST_DATASET_NAME"
fi

# ---------------------------------------------------------------------------
# tools: Randoop and EvoSuite tests for the evaluation set
# ---------------------------------------------------------------------------
# Tests that already fail on the original method are noise, so they are dropped:
# the dummy model replays the original, the tool tests run against it, and
# anything that does not pass is filtered out.
if [[ "$STAGES" == "all" || "$STAGES" == "tools" ]]; then
    banner "Generating Randoop and EvoSuite tests"

    # Maven-bound; parallelises well across projects.
    export THROWGEN_EVAL_WORKERS=10
    export THROWGEN_MAX_TOOL_TESTS=400

    run python -m throwgen.tools.tool_test_adapter generate_and_extract \
        --dataset_name="$TEST_DATASET_NAME" --tool=all

    run python -m throwgen.dataset.multi_ebt_data update_dataset \
        --base_dataset_name="$TEST_DATASET_NAME" \
        --out_dataset_name="$TEST_DATASET_NAME" \
        --selected_extractor_names="['RandoopTestExtractor', 'EvosuiteTestExtractor']"

    sanity_check_tools() {
        run python -m throwgen.eval.metrics.tool_runtime_metrics \
            --dataset_name="$TEST_DATASET_NAME" --prompt_gen_type=mut \
            --llm_type=dummy --model_name=dummy --setup=dummy \
            --num_workers="$THROWGEN_EVAL_WORKERS" \
            --max_tests_per_sample="$THROWGEN_MAX_TOOL_TESTS" run_eval
    }

    banner "Running the tool tests against the original methods"
    run python -m throwgen.llm.dummy_experiment --model=dummy \
        do_dummy_experiment --dataset_name="$TEST_DATASET_NAME" --prompt_gen_type=mut
    sanity_check_tools

    banner "Dropping tool tests that fail on the original methods"
    run python -m throwgen.tools.filter_tool_tests --dataset_name="$TEST_DATASET_NAME"
    # Must now report 100%; anything less means a tool test is flaky.
    sanity_check_tools

    export THROWGEN_EVAL_WORKERS=1
    export THROWGEN_MAX_TOOL_TESTS=0
fi

# ---------------------------------------------------------------------------
# validation split
# ---------------------------------------------------------------------------
if [[ "$STAGES" == "all" || "$STAGES" == "val" ]]; then
    build_funnel "$NE2E_VAL_DATASET" "mega-val-data"
    capture_throw_removal "$VAL_DATASET_NAME"
fi

# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------
if [[ "$STAGES" == "all" || "$STAGES" == "merge" ]]; then
    banner "Merging the test and validation sets"
    mebt merge_dataset --first_dataset_name="$TEST_DATASET_NAME" \
        --second_dataset_name="$VAL_DATASET_NAME" --out_dataset_name="$ALL_DATASET_NAME"
    capture_throw_removal "$ALL_DATASET_NAME"
    [[ "$MOCK" == 1 ]] && expect_dataset "$ALL_DATASET_NAME"
fi

echo
echo "=========================================="
if [[ "$MOCK" == 1 ]]; then
    echo "Mock run finished: every shipped dataset stage is present."
else
    echo "Data generation finished."
fi
echo "=========================================="
