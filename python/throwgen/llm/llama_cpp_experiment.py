import atexit
import collections
import logging
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import huggingface_hub
import requests
import seutil as su
from etestgen.macros import Macros
from jsonargparse import CLI
from throwgen.llm.base_experiment import BaseExperiment
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_PIPE_TAIL_LINES = 20


class ModelInfo(TypedDict):
    repo: str
    tokenizer: str
    file: list[str]
    model_type: NotRequired[str]
    model_tag: NotRequired[str]
    quant_type: NotRequired[str]
    extra_tag: NotRequired[str]
    end_thinking_token: NotRequired[str]


MODEL_MAP: dict[str, dict[str, dict[str, ModelInfo]]] = {
    "gpt-oss": {
        "120b": {
            "q8_0": {
                "repo": "bartowski/openai_gpt-oss-120b-GGUF",
                "tokenizer": "openai/gpt-oss-20b",
                "file": [
                    "openai_gpt-oss-120b-Q8_0/openai_gpt-oss-120b-Q8_0-00001-of-00002.gguf",
                    "openai_gpt-oss-120b-Q8_0/openai_gpt-oss-120b-Q8_0-00002-of-00002.gguf",
                ],
                "end_thinking_token": "<|channel|>final<|message|>",
            },
            "q4_k_m": {
                "repo": "bartowski/openai_gpt-oss-120b-GGUF",
                "tokenizer": "openai/gpt-oss-20b",
                "file": [
                    "openai_gpt-oss-120b-Q4_K_M/openai_gpt-oss-120b-Q4_K_M-00001-of-00002.gguf",
                    "openai_gpt-oss-120b-Q4_K_M/openai_gpt-oss-120b-Q4_K_M-00002-of-00002.gguf",
                ],
                "end_thinking_token": "<|channel|>final<|message|>",
            },
        },
        "20b": {
            "q8_0": {
                "repo": "bartowski/openai_gpt-oss-20b-GGUF",
                "tokenizer": "openai/gpt-oss-20b",
                "file": ["openai_gpt-oss-20b-Q8_0.gguf"],
                "end_thinking_token": "<|channel|>final<|message|>",
            },
            "q4_k_m": {
                "repo": "bartowski/openai_gpt-oss-20b-GGUF",
                "tokenizer": "openai/gpt-oss-20b",
                "file": ["openai_gpt-oss-20b-Q4_K_M.gguf"],
                "end_thinking_token": "<|channel|>final<|message|>",
            },
        },
    },
    "qwen3.5": {
        "35b-a3b": {
            "q4_k_m": {
                "repo": "bartowski/Qwen_Qwen3.5-35B-A3B-GGUF",
                "tokenizer": "Qwen/Qwen3.5-35B-A3B",
                "file": ["Qwen_Qwen3.5-35B-A3B-Q4_K_M.gguf"],
                "end_thinking_token": "</think>",
            },
            "q8_0": {
                "repo": "bartowski/Qwen_Qwen3.5-35B-A3B-GGUF",
                "tokenizer": "Qwen/Qwen3.5-35B-A3B",
                "file": ["Qwen_Qwen3.5-35B-A3B-Q8_0.gguf"],
                "end_thinking_token": "</think>",
            },
        },
        "122b-a10b": {
            "q4_k_m": {
                "repo": "bartowski/Qwen_Qwen3.5-122B-A10B-GGUF",
                "tokenizer": "Qwen/Qwen3.5-35B-A3B",
                "file": [
                    "Qwen_Qwen3.5-122B-A10B-Q4_K_M/Qwen_Qwen3.5-122B-A10B-Q4_K_M-00001-of-00002.gguf",
                    "Qwen_Qwen3.5-122B-A10B-Q4_K_M/Qwen_Qwen3.5-122B-A10B-Q4_K_M-00002-of-00002.gguf",
                ],
                "end_thinking_token": "</think>",
            },
        },
        "27b": {
            "q4_k_m": {
                "repo": "bartowski/Qwen_Qwen3.5-27B-GGUF",
                "tokenizer": "Qwen/Qwen3.5-27B",
                "file": ["Qwen_Qwen3.5-27B-Q4_K_M.gguf"],
                "end_thinking_token": "</think>",
            },
        },
    },
    "qwen2.5-coder": {
        "32b-instruct": {
            "q8_0": {
                "repo": "Qwen/Qwen2.5-Coder-32B-Instruct-GGUF",
                "tokenizer": "Qwen/Qwen2.5-Coder-0.5B-Instruct",
                "file": ["qwen2.5-coder-32b-instruct-q8_0.gguf"],
            },
        },
        "7b-instruct": {
            "q8_0": {
                "repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                "tokenizer": "Qwen/Qwen2.5-Coder-0.5B-Instruct",
                "file": ["qwen2.5-coder-7b-instruct-q8_0.gguf"],
            },
        },
    },
    "gemma3": {
        "27b-it": {
            "q8_0": {
                "repo": "bartowski/google_gemma-3-27b-it-GGUF",
                "tokenizer": "google/gemma-3-1b-it",
                "file": ["google_gemma-3-27b-it-Q8_0.gguf"],
            },
        },
    },
    "llama3.1": {
        "8b-instruct": {
            "q8_0": {
                "repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
                "tokenizer": "meta-llama/Llama-3.1-8B-Instruct",
                "file": ["Meta-Llama-3.1-8B-Instruct-Q8_0.gguf"],
            },
        },
    },
    "phi4": {
        "14b": {
            "q8_0": {
                "repo": "bartowski/phi-4-GGUF",
                "tokenizer": "microsoft/phi-4",
                "file": ["phi-4-Q8_0.gguf"],
            }
        }
    },
}


def _is_port_available(port: int) -> bool:
    """Check if a port is available for binding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _find_available_port(start_port: int = 8080, max_attempts: int = 100) -> int:
    """Find an available port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        if _is_port_available(port):
            return port
    raise RuntimeError(
        f"Could not find available port in range {start_port}-{start_port + max_attempts}"
    )


class _GpuBackendConfig(TypedDict):
    cmd: list[str]
    device_prefix: str
    skip_line_prefix: NotRequired[str]


_GPU_BACKENDS: list[_GpuBackendConfig] = [
    {
        "cmd": ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        "device_prefix": "CUDA",
    },
    {
        "cmd": ["rocm-smi", "--showid", "--csv"],
        "device_prefix": "ROCM",
        "skip_line_prefix": "device",
    },
]


def _get_gpu_type() -> tuple[str, int]:
    """Return (device_prefix, num_gpus) for the first detected GPU backend.

    Iterates _GPU_BACKENDS in order. Returns ('', 0) if none are detected.
    """
    for backend in _GPU_BACKENDS:
        try:
            result = subprocess.run(
                backend["cmd"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                skip = backend.get("skip_line_prefix")
                lines = [
                    l
                    for l in result.stdout.strip().split("\n")
                    if l.strip() and (skip is None or not l.lower().startswith(skip))
                ]
                if lines:
                    return backend["device_prefix"], len(lines)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return "", 0


@dataclass
class _Server:
    """State for a single llama-server instance owned by a worker."""

    port: int
    base_url: str
    llama_cmd: list[str]
    proc: subprocess.Popen | None = None
    stderr_lines: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=_PIPE_TAIL_LINES)
    )
    stdout_lines: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=_PIPE_TAIL_LINES)
    )
    stderr_thread: threading.Thread | None = None
    stdout_thread: threading.Thread | None = None


class LlamaCppExperiment(BaseExperiment):
    def __init__(
        self,
        model: str,
        gguf_dir: str,
        gpu_layers: int | None = None,
        sample_size: int = 10,
        temp: float = 0.8,
        batch_size: int = 1,
        parallel_slots: int | None = None,
        ctx_per_slot: int = 8192,
        ctx_size: int | None = None,
        port: int = 8080,
    ):
        """Launch one llama-server per detected GPU and route queries by worker_id.

        Detected GPUs each get their own server (bound via ``-dev``) and the
        matching BaseExperiment worker pool. With no GPUs, a single server runs
        on the default device.
        """
        prefix, num_gpus = _get_gpu_type()
        logger.info(f"Detected {num_gpus} {prefix or 'CPU'} device(s)")
        server_count = max(1, num_gpus)

        super().__init__(model, server_count, sample_size, temp, batch_size)
        self.llm_type = "llama_cpp"

        if parallel_slots is None:
            parallel_slots = sample_size * batch_size
        if ctx_size is None:
            ctx_size = parallel_slots * ctx_per_slot

        model_info = self.get_model_info(model)
        tokenizer_name = model_info["tokenizer"]
        self._tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
        assert (
            hasattr(self._tokenizer, "apply_chat_template")
            and self._tokenizer.chat_template is not None
        ), f"{tokenizer_name} does not have a chat template"

        model_path = self.get_model_path(model, gguf_dir)

        self._servers: list[_Server] = []
        next_port = port
        for w in range(server_count):
            srv_port = _find_available_port(start_port=next_port)
            next_port = srv_port + 1
            llama_cmd = [
                "llama-server",
                "--no-mmap",
                "-m", str(model_path),
                "-c", str(ctx_size),
                "--port", str(srv_port),
                "-np", str(parallel_slots),
            ]
            if gpu_layers is not None:
                llama_cmd += ["-ngl", str(gpu_layers)]
            if num_gpus > 0:
                llama_cmd += ["-dev", f"{prefix}{w}"]

            server = _Server(
                port=srv_port,
                base_url=f"http://localhost:{srv_port}/",
                llama_cmd=llama_cmd,
            )
            self._servers.append(server)
            self._start_server(server)

        atexit.register(self._ensure_cleanup_all)

    def _drain_pipe(self, pipe: Any, buf: collections.deque) -> None:
        for raw_line in pipe:
            buf.append(raw_line.decode("utf-8", errors="replace").rstrip())

    def _start_server(self, server: _Server) -> None:
        server.stderr_lines.clear()
        server.stdout_lines.clear()
        logger.info(
            f"Starting llama-server on port {server.port}: {' '.join(server.llama_cmd)}"
        )
        server.proc = subprocess.Popen(
            server.llama_cmd,
            preexec_fn=os.setsid,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        server.stderr_thread = threading.Thread(
            target=self._drain_pipe,
            args=(server.proc.stderr, server.stderr_lines),
            daemon=True,
        )
        server.stdout_thread = threading.Thread(
            target=self._drain_pipe,
            args=(server.proc.stdout, server.stdout_lines),
            daemon=True,
        )
        server.stderr_thread.start()
        server.stdout_thread.start()

        done = False
        while not done:
            time.sleep(5)
            server.proc.poll()
            if server.proc.returncode is not None:
                stderr_tail = "\n".join(server.stderr_lines)
                raise ChildProcessError(
                    f"llama-server exited unexpectedly on port {server.port} "
                    f"(exit code {server.proc.returncode}):\n{stderr_tail}"
                )
            logger.info(f"waiting for model to load on port {server.port}")
            try:
                res = requests.get(f"{server.base_url}health", timeout=2)
                done = res.status_code == 200
            except requests.exceptions.RequestException:
                pass

    def _restart_server(self, server: _Server) -> None:
        logger.warning(f"Restarting llama-server on port {server.port}...")
        self._kill_server(server)
        if server.stderr_thread:
            server.stderr_thread.join(timeout=5)
        if server.stdout_thread:
            server.stdout_thread.join(timeout=5)
        self._start_server(server)

    def _post_completion_with_retry(
        self, server: _Server, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = requests.post(
                    f"{server.base_url}completion",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, list):
                    result = [result]
                return result
            except requests.exceptions.ConnectionError as e:
                last_exc = e
                stdout_tail = "\n".join(server.stdout_lines)
                stderr_tail = "\n".join(server.stderr_lines)
                logger.warning(
                    f"Connection error on port {server.port}, "
                    f"attempt {attempt + 1}/{_MAX_RETRIES}: {e}\n"
                    f"stdout tail:\n{stdout_tail}\nstderr tail:\n{stderr_tail}"
                )
                if attempt < _MAX_RETRIES - 1:
                    self._restart_server(server)
        stdout_tail = "\n".join(server.stdout_lines)
        stderr_tail = "\n".join(server.stderr_lines)
        raise RuntimeError(
            f"llama-server on port {server.port} failed after {_MAX_RETRIES} retries: {last_exc}\n"
            f"stdout tail:\n{stdout_tail}\nstderr tail:\n{stderr_tail}"
        ) from last_exc

    def _query(
        self,
        chat: list[dict[str, str]],
        sample_size: int,
        temp: float,
        worker_id: int = 0,
    ) -> list[str]:
        return self._query_batch([chat], sample_size, temp, worker_id)[0]

    def _query_batch(
        self,
        chats_batch: list[list[dict[str, str]]],
        sample_size: int,
        temp: float,
        worker_id: int = 0,
    ) -> list[list[str]]:
        """Route this batch to the server owned by ``worker_id`` and send all
        prompts in a single request using n_cmpl + multi-prompt.

        llama.cpp returns n_prompts * n_cmpl results sequentially:
        [prompt0_cmpl0, prompt0_cmpl1, ..., prompt1_cmpl0, prompt1_cmpl1, ...]
        """
        server = self._servers[worker_id % len(self._servers)]
        prompts = [self._apply_template(chat) for chat in chats_batch]
        payload: dict = {
            # Single prompt → scalar; multiple → list (llama.cpp distinguishes the two)
            "prompt": prompts[0] if len(prompts) == 1 else prompts,
            "cache_prompt": True,
            "seed": 123,
            "temp": temp,
            "n_cmpl": sample_size,
        }
        logger.debug(payload)
        try:
            results = self._post_completion_with_retry(server, payload)
            n = len(chats_batch)
            return [
                [
                    results[i * sample_size + j].get("content", "").strip()
                    for j in range(sample_size)
                ]
                for i in range(n)
            ]
        except Exception as e:
            # requests can wrap KeyboardInterrupt as a ConnectionError — unwrap it
            cause = e
            while cause is not None:
                if isinstance(cause, KeyboardInterrupt):
                    raise KeyboardInterrupt() from e
                cause = getattr(cause, "__context__", None)
            print(f"!!! INFERENCE FAILED on port {server.port}: {e}")
            return [["```java\n\n\n```"] * sample_size for _ in chats_batch]

    def _apply_template(self, chat: list[dict[str, str]]):
        return self._tokenizer.apply_chat_template(
            chat,
            tokenize=False,
            add_generation_prompt=True,
        )

    def _ensure_cleanup_all(self) -> None:
        for server in self._servers:
            if server.proc and server.proc.poll() is None:
                self._kill_server(server)

    def _kill_server(self, server: _Server, timeout: float = 5.0) -> None:
        if server.proc is None:
            return
        try:
            os.killpg(os.getpgid(server.proc.pid), signal.SIGTERM)
            server.proc.wait(timeout=timeout)
            logger.info(
                f"llama-server graceful shutdown (pid={server.proc.pid}, port={server.port})"
            )
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(server.proc.pid), signal.SIGKILL)
            server.proc.wait()
            logger.info(
                f"llama-server force-killed (pid={server.proc.pid}, port={server.port})"
            )
        server.proc = None

    def close(self) -> None:
        self._ensure_cleanup_all()

    def __del__(self) -> None:  # pragma: no cover
        # __del__ is called at arbitrary times; the atexit handler covers most
        # cases, but we call close() anyway for immediate cleanup if the object
        # goes out of scope early.
        try:
            self.close()
        except Exception:
            # Suppress all exceptions; __del__ should never crash the interpreter.
            pass

    @staticmethod
    def get_model_path(model_name: str, gguf_dir: str) -> Path:
        model_info_dict = LlamaCppExperiment.get_model_info(model_name)
        assert (
            "model_tag" in model_info_dict
            and "quant_type" in model_info_dict
            and "model_type" in model_info_dict
        )
        file_name = f"{model_info_dict['model_type']}-{model_info_dict['model_tag']}-{model_info_dict['quant_type']}"
        if "extra_tag" in model_info_dict:
            file_name += file_name + f"@{model_info_dict['extra_tag']}"

        return (
            Path(gguf_dir)
            / model_info_dict["model_type"]
            / model_info_dict["model_tag"]
            / f"{file_name}.gguf"
        )

    @staticmethod
    def get_model_info(
        model_name: str,
    ) -> ModelInfo:
        model_type = model_name.split(":")[0]
        if "@" in model_name:
            quant_type, extra_tag = model_name.split("-")[-1].split("@")
        else:
            quant_type = model_name.split("-")[-1]
            extra_tag = None
        model_tag = model_name.split(":")[1][: -len(quant_type) - 1]
        model_info_dict: ModelInfo = MODEL_MAP[model_type][model_tag][quant_type]
        model_info_dict.update(
            {
                "model_type": model_type,
                "model_tag": model_tag,
                "quant_type": quant_type,
            }
        )
        if extra_tag:
            model_info_dict.update({"extra_tag": extra_tag})

        return model_info_dict

    @staticmethod
    def download_model_gguf(model_name: str, gguf_dir: str):
        model_info_dict = LlamaCppExperiment.get_model_info(model_name)
        save_path = LlamaCppExperiment.get_model_path(model_name, gguf_dir)

        if not os.path.isfile(save_path):
            if len(model_info_dict["file"]) == 1:
                huggingface_hub.hf_hub_download(
                    repo_id=model_info_dict["repo"],
                    filename=model_info_dict["file"][0],
                    local_dir=save_path.parent,
                )
                shutil.move(save_path.parent / model_info_dict["file"][0], save_path)
            else:
                for file_name in model_info_dict["file"]:
                    huggingface_hub.hf_hub_download(
                        repo_id=model_info_dict["repo"],
                        filename=file_name,
                        local_dir=save_path.parent,
                    )
                subprocess.run(
                    [
                        "llama-gguf-split",
                        "--merge",
                        str(save_path.parent / model_info_dict["file"][0]),
                        str(save_path),
                    ],
                )
        else:
            logger.info(f"{save_path} exists")


if __name__ == "__main__":
    import sys
    from throwgen.utils.multi_thread_n_logging import setup_thread_logging

    # Check if using multi-threading based on CLI args
    use_threading = "--num_workers" in " ".join(sys.argv) and any(
        arg.split("=")[-1] != "1" for arg in sys.argv if "--num_workers" in arg
    )

    if use_threading:
        with setup_thread_logging(logging.INFO, Macros.log_file):
            CLI(LlamaCppExperiment, as_positional=False)
    else:
        su.log.setup(Macros.log_file)
        CLI(LlamaCppExperiment, as_positional=False)
