def strip_thinking(text: str, llm_type: str, model: str) -> str:
    """Strip the thinking block from *text* for models that emit one.

    For llama_cpp engines, looks up the end-thinking token via
    LlamaCppExperiment and returns everything after it (stripped). Returns
    *text* unchanged when no end-thinking token applies (different engine,
    model without one, or token not found in the text).
    """
    if llm_type != "llama_cpp":
        return text
    # Lazy import to avoid pulling transformers into every eval entry point.
    from throwgen.llm.llama_cpp_experiment import LlamaCppExperiment

    try:
        end_token = LlamaCppExperiment.get_model_info(model).get("end_thinking_token")
    except (KeyError, IndexError):
        return text
    if not end_token:
        return text
    idx = text.find(end_token)
    if idx != -1:
        return text[idx + len(end_token):].strip()
    return text
