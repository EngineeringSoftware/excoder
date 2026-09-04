import os
import pathlib
from typing import Any

import huggingface_hub
import seutil as su
from etestgen.macros import Macros
from jsonargparse import CLI
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__, su.log.INFO)

MODEL_MAP = {
    "qwen2.5-coder": {
        "32b-instruct": {
            "q6_K": {
                "quant": "gguf",
                "tokenizer": "Qwen/Qwen2.5-Coder-32B-Instruct",
                "repo": "bartowski/Qwen2.5-Coder-32B-Instruct-GGUF",
                "destination": "Qwen2.5-Coder-32B-Instruct-Q6_K.gguf",
            },
            "awq": {
                "quant": "awq",
                "tokenizer": "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
                "repo": "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ",
                "destination": "Qwen2.5-Coder-32B-Instruct-AWQ",
            },
            "gptq8": {
                "quant": "gptq",
                "tokenizer": "Qwen/Qwen2.5-Coder-32B-Instruct-GPTQ-Int8",
                "repo": "Qwen/Qwen2.5-Coder-32B-Instruct-GPTQ-Int8",
                "destination": "Qwen/Qwen2.5-Coder-32B-Instruct-GPTQ-Int8"
            }
        },
        "7b-instruct": {
            "q6_K": {
                "quant": "gguf",
                "tokenizer": "Qwen/Qwen2.5-Coder-7B-Instruct",
                "repo": "bartowski/Qwen2.5-Coder-7B-Instruct-GGUF",
                "destination": "Qwen2.5-Coder-7B-Instruct-Q6_K.gguf",
            },
            "awq": {
                "quant": "awq",
                "tokenizer": "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
                "repo": "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
                "destination": "Qwen2.5-Coder-7B-Instruct-AWQ",
            },
            "gptq8": {
                "quant": "gptq",
                "tokenizer": "Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int8",
                "repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int8",
                "destination": "Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int8"
            }
        },
    },
    "llama3.1": {
        "8b-instruct": {
            "q6_K": {
                "quant": "gguf",
                "tokenizer": "meta-llama/Llama-3.1-8B-Instruct",
                "repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
                "destination": "Qwen2.5-Coder-7B-Instruct-Q6_K.gguf",
            },
            "awq": {
                "quant": "awq",
                "tokenizer": "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4",
                "repo": "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4",
                "destination": "Meta-Llama-3.1-8B-Instruct-AWQ-INT4",
            },
        }
    },
    # "gemma3": {
    #     "27b-it": {
    #         "qat": {
    #             "quant": "gguf",
    #             "tokenizer": "google/gemma-3-4b-it",
    #             "repo": "stduhpf/google-gemma-3-27b-it-qat-q4_0-gguf-small",
    #             "destination": "gemma-3-27b-it-q4_0_s.gguf",
    #         },
    #     }
    # },
    # "codestral": {
    #     "22b-v0.1": {
    #         "tokenizer": "mistralai/Codestral-22B-v0.1",
    #         "repo": "bartowski/Codestral-22B-v0.1-GGUF",
    #         "destination": {
    #             "q6_K": "Codestral-22B-v0.1-Q6_K.gguf",
    #             "q8_0": "Codestral-22B-v0.1-Q8_0.gguf",
    #         },
    #     }
    # },
}


def get_model_info(model_name: str) -> tuple[dict[str, Any], pathlib.Path, str]:
    model_type = model_name.split(":")[0]
    quant_type = model_name.split("-")[-1]
    model_tag = model_name.split(":")[1][: -len(quant_type) - 1]
    model_info_dict = MODEL_MAP[model_type][model_tag][quant_type]
    target_dir = ThrowgenMacros.model_dir / model_type / model_tag
    destination_name = model_info_dict["destination"]
    return model_info_dict, target_dir, destination_name

def download_model(model_name: str):
    model_info_dict, _, _= get_model_info(model_name)
    if model_info_dict['quant'] == "awq":
        download_model_awq(model_name)
    elif model_info_dict['quant'] == "gguf":
        download_model_gguf(model_name)
    else:
        raise ValueError(f"{model_info_dict['quant']} is not a valid quant method")

def download_model_awq(model_name: str):
    model_info_dict, target_dir, dir_name = get_model_info(model_name)
    assert model_info_dict['quant'] == "awq"

    su.io.mkdir(target_dir)

    if not os.path.isdir(target_dir / dir_name):
        su.io.mkdir(target_dir / dir_name)
        logger.info(f"{model_name} not found in locally, pulling from hf")
        huggingface_hub.snapshot_download(
            repo_id=model_info_dict["repo"],
            local_dir=target_dir / dir_name,
        )
        logger.info(f"{model_name} saved at {target_dir / dir_name}")
    else:
        logger.info(f"{model_name} is already downloaded at {target_dir / dir_name}")

def download_model_gguf(model_name: str):
    model_info_dict, target_dir, file_name = get_model_info(model_name)
    assert model_info_dict['quant'] == "gguf"

    su.io.mkdir(target_dir)

    if not os.path.isfile(target_dir / file_name):
        logger.info(f"{model_name} not found in locally, pulling from hf")
        huggingface_hub.hf_hub_download(
            repo_id=model_info_dict["repo"],
            filename=file_name,
            local_dir=target_dir,
        )
        logger.info(f"{model_name} saved at {target_dir / file_name}")
    else:
        logger.info(f"{model_name} is already downloaded at {target_dir / file_name}")


if __name__ == "__main__":
    su.log.setup(Macros.log_file)
    CLI(download_model, as_positional=False)
