function generate_number {
    local model_name="$1"
    local model_type="$2"
    local dataset_name="$3"
    local setup_type="$4"
    local prompt_gen_type="$5"
    local original_dir="$PWD"
    local rc

    cd "$PYTHON_DIR" || return 1
    python -m throwgen.table_gen --dataset_name="$dataset_name" \
        make_result_numbers --llm_type="$model_type" \
        --prompt_gen_type="$prompt_gen_type" \
        --model_name="$model_name" --setup="$setup_type"
    rc=$?
    cd "$original_dir" || return 1
    return $rc
}
