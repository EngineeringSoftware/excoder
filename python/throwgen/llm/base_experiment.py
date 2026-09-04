import dataclasses
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, TypedDict

import seutil as su
from etestgen.macros import Macros
from jsonargparse import CLI
from throwgen.dataset.data import DataLLMOuput
from throwgen.dataset.multi_ebt_data import MultiEBTDataset
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.prompt.add_on_prompt_gen import AddOnPrompt
from throwgen.prompt.add_on_repair_prompt import AddOnRepairPrompt
from throwgen.prompt.base_prompt_gen import BasePromptGen
from throwgen.prompt.multi_ebt_prompt_gen import MultiEBTPrompt
from throwgen.prompt.one_field_prompt_gen import OneFieldPromptGen
from throwgen.utils.multi_thread_n_logging import setup_thread_logging
from tqdm import tqdm

logger = logging.getLogger(__name__)
DEFAULT_SAMPLE_SIZE = 10
DEFAULT_TEMP = 0.8


class WorkerTask(TypedDict):
    """Type definition for worker task. Supports batches of prompts."""

    data_ids: list[str]
    task_idxs: list[int]
    messages_batch: list[list[dict[str, str]]]
    sample_size: int
    temp: float


class WorkerResult(TypedDict):
    """Type definition for worker result. Parallel arrays with WorkerTask."""

    data_ids: list[str]
    task_idxs: list[int]
    results_batch: list[list[str]]  # one list[str] per prompt in the batch


class PromptConfig(TypedDict):
    """Type definition for prompt configuration."""

    gen: BasePromptGen
    file: tuple[str, str]


class BaseExperiment:
    PROMPT: dict[str, PromptConfig] = {
        "base": {
            "gen": MultiEBTPrompt,
            "file": ("system.md", "multi-ebt.md"),
        },
        "base-repair": {
            "gen": AddOnRepairPrompt,
            "file": ("system.md", "add_on_body/base-repair.md"),
        },
        "mut": {"gen": OneFieldPromptGen, "file": ("system.md", "mut_field.md")},
        "mut_no_throw": {
            "gen": OneFieldPromptGen,
            "file": ("system.md", "mut_no_throw_field.md"),
        },
        "tuctn-all-info-repair": {
            "gen": AddOnRepairPrompt,
            "file": ("system.md", "add_on_body/tuctn-all-info-repair.md"),
        },
        "tuctn-all-info": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/tuctn-all-info.md"),
        },
        "tuct-all-info": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/tuct-all-info.md"),
        },
        "cmtu": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/ci-mi-ti-ue.md"),
        },
        "no-avsym": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/no-avsym.md"),
        },
        "no-excon": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/no-excon.md"),
        },
        "no-lcov": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/no-lcov.md"),
        },
        "no-threxc": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/no-threxc.md"),
        },
        "only-avsym": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/only-avsym.md"),
        },
        "only-lcov": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/only-lcov.md"),
        },
        "only-nebt": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/only-nebt.md"),
        },
        "only-threxc": {
            "gen": AddOnPrompt,
            "file": ("system.md", "add_on_body/only-threxc.md"),
        },
    }

    def __init__(
        self,
        model: str,
        num_workers: int = 1,
        sample_size: int = DEFAULT_SAMPLE_SIZE,
        temp: float = DEFAULT_TEMP,
        batch_size: int = 1,
    ):
        self.model_name = model
        self._num_workers = num_workers
        self.sample_size = sample_size
        self.temp = temp
        self.batch_size = batch_size
        self.llm_type = "base"
        logger.info(f"Using {model}")

    def _query(
        self,
        chat: list[dict[str, str]],
        sample_size: int,
        temp: float,
        worker_id: int = 0,
    ) -> list[str]:
        raise NotImplementedError("Please Implement _query method")

    def _query_batch(
        self,
        chats_batch: list[list[dict[str, str]]],
        sample_size: int,
        temp: float,
        worker_id: int = 0,
    ) -> list[list[str]]:
        """Query the LLM with a batch of prompts. Default: call _query for each.
        Override in subclasses to send all prompts in a single request."""
        return [self._query(chat, sample_size, temp, worker_id) for chat in chats_batch]

    def _run_experiment_with_threading(
        self,
        tasks: list[WorkerTask],
        process_func: Callable[[WorkerTask, int], WorkerResult],
        save_path: Path | None = None,
    ) -> list[DataLLMOuput]:
        """
        Helper function to run experiments with optional multi-threading.

        Each WorkerTask contains a batch of prompts (messages_batch). process_func
        must return a WorkerResult with parallel data_ids/task_idxs/results_batch.

        If ``save_path`` is provided, each DataLLMOuput is appended to that file
        as soon as all of its tasks finish, so partial progress survives crashes.

        Returns:
            List of DataLLMOuput results (preserves order by data_id)
        """
        # Track original data ID order across all batches, and how many tasks
        # each data_id needs before its DataLLMOuput is complete.
        data_id_order = []
        seen_ids: set[str] = set()
        expected_counts: dict[str, int] = {}
        for task in tasks:
            for data_id in task["data_ids"]:
                if data_id not in seen_ids:
                    data_id_order.append(data_id)
                    seen_ids.add(data_id)
                expected_counts[data_id] = expected_counts.get(data_id, 0) + 1

        save_file = None
        save_lock = Lock()
        written_ids: set[str] = set()
        if save_path is not None:
            save_path.parent.mkdir(exist_ok=True, parents=True)
            save_file = open(save_path, "w", encoding="utf-8")
            logger.info(f"Streaming results to {save_path} as they complete")

        def _flush_if_complete(data_id: str, id_to_preds: dict) -> None:
            if save_file is None or data_id in written_ids:
                return
            if len(id_to_preds[data_id]) != expected_counts[data_id]:
                return
            sorted_preds = sorted(id_to_preds[data_id], key=lambda x: x[0])
            all_preds: list[str] = []
            for _, results in sorted_preds:
                all_preds.extend(results)
            record = DataLLMOuput(id=data_id, preds=all_preds)
            save_file.write(json.dumps(dataclasses.asdict(record)))
            save_file.write("\n")
            save_file.flush()
            written_ids.add(data_id)

        def _accumulate(id_to_preds: dict, result: WorkerResult) -> None:
            with save_lock:
                for data_id, task_idx, results in zip(
                    result["data_ids"], result["task_idxs"], result["results_batch"]
                ):
                    if data_id not in id_to_preds:
                        id_to_preds[data_id] = []
                    id_to_preds[data_id].append((task_idx, results))
                    _flush_if_complete(data_id, id_to_preds)

        if self._num_workers == 1:
            id_to_preds: dict = {}
            for task in tqdm(tasks, desc="Inferencing"):
                _accumulate(id_to_preds, process_func(task, 0))
        else:
            logger.info(
                f"Starting multi-threaded experiment with {self._num_workers} workers"
            )
            task_queue: Queue[WorkerTask] = Queue()
            result_queue: Queue[WorkerResult] = Queue()

            for task in tasks:
                task_queue.put(task)

            def worker(worker_id: int) -> None:
                while True:
                    try:
                        task = task_queue.get_nowait()
                    except Empty:
                        break
                    result_queue.put(process_func(task, worker_id))

            threads = [
                Thread(target=worker, args=(i,), name=f"Worker-{i}")
                for i in range(self._num_workers)
            ]
            for t in threads:
                t.start()

            total = len(tasks)
            id_to_preds = {}
            with tqdm(total=total, desc="Inferencing") as pbar:
                collected = 0
                while collected < total:
                    try:
                        _accumulate(id_to_preds, result_queue.get(timeout=0.1))
                        collected += 1
                        pbar.update(1)
                    except Empty:
                        if not any(t.is_alive() for t in threads):
                            break

            for t in threads:
                t.join()

            while not result_queue.empty():
                _accumulate(id_to_preds, result_queue.get())

        # Sort within each ID by task_idx and flatten
        for data_id in id_to_preds:
            id_to_preds[data_id].sort(key=lambda x: x[0])
            all_preds: list[str] = []
            for _, results in id_to_preds[data_id]:
                all_preds.extend(results)
            id_to_preds[data_id] = all_preds

        return [
            DataLLMOuput(id=data_id, preds=id_to_preds[data_id])
            for data_id in data_id_order
            if data_id in id_to_preds
        ]

    def do_multi_ebt_experiment(
        self,
        dataset_name: str,
        prompt_gen_type: str,
    ):
        logger.info(f"Doing a multi ebt experiment on dataset {dataset_name}")
        dataset = MultiEBTDataset.from_saved(
            ThrowgenMacros.mebt_data_dir / dataset_name
        )
        prompt_gen = self.PROMPT[prompt_gen_type]["gen"](
            *self.PROMPT[prompt_gen_type]["file"]
        )

        # Build batched tasks
        tasks: list[WorkerTask] = []
        batch_ids: list[str] = []
        batch_idxs: list[int] = []
        batch_msgs: list[list[dict[str, str]]] = []
        all_data = list(dataset)
        for i, data in enumerate(all_data):
            batch_ids.append(data.id)
            batch_idxs.append(0)
            batch_msgs.append(prompt_gen.get_message(data))
            if len(batch_msgs) == self.batch_size or i == len(all_data) - 1:
                tasks.append(
                    {
                        "data_ids": batch_ids,
                        "task_idxs": batch_idxs,
                        "messages_batch": batch_msgs,
                        "sample_size": self.sample_size,
                        "temp": self.temp,
                    }
                )
                batch_ids, batch_idxs, batch_msgs = [], [], []

        def process_task(task: WorkerTask, worker_id: int) -> WorkerResult:
            results_batch = self._query_batch(
                task["messages_batch"],
                task["sample_size"],
                task["temp"],
                worker_id=worker_id,
            )
            return {
                "data_ids": task["data_ids"],
                "task_idxs": task["task_idxs"],
                "results_batch": results_batch,
            }

        output_path = (
            ThrowgenMacros.llm_output_dir
            / dataset_name
            / f"{self.llm_type}-{self.model_name}-{prompt_gen_type}-multi_ebt.jsonl"
        )
        out_results = self._run_experiment_with_threading(
            tasks, process_task, save_path=output_path
        )

        su.io.dump(output_path, out_results)

    def do_repair_experiment(
        self,
        dataset_name: str,
        prompt_gen_type: str,
    ):
        logger.info(f"Doing a repair analysis experiment on dataset {dataset_name}")
        dataset = MultiEBTDataset.from_saved(
            ThrowgenMacros.mebt_data_dir / dataset_name
        )
        prompt_gen_name, round_num = prompt_gen_type.split("@")
        round_num = int(round_num)
        prompt_gen: AddOnRepairPrompt = self.PROMPT[prompt_gen_name]["gen"](
            *self.PROMPT[prompt_gen_name]["file"]
        )

        # Load previous outputs and evaluations
        if round_num <= 1:
            base_prompt = prompt_gen_name[: -len("-repair")]
            last_round_output: list[DataLLMOuput] = su.io.load(
                ThrowgenMacros.llm_output_dir
                / dataset_name
                / f"{self.llm_type}-{self.model_name}-{base_prompt}-"
                f"multi_ebt.jsonl",
                clz=DataLLMOuput,
            )  # type: ignore
            id2output: dict[str, DataLLMOuput] = {
                llm_out.id: llm_out for llm_out in last_round_output
            }

            ebt_file = (
                ThrowgenMacros.metrics_dir
                / dataset_name
                / f"run-ebts-{self.llm_type}-{self.model_name}-"
                f"{base_prompt}-multi_ebt-each-sample.jsonl"
            )
            nebt_file = (
                ThrowgenMacros.metrics_dir
                / dataset_name
                / f"run-nebts-{self.llm_type}-{self.model_name}-"
                f"{base_prompt}-multi_ebt-each-sample.jsonl"
            )
            # Load EBT and NEBT results separately
            ebt_results: list[dict[str, Any]] = su.io.load(ebt_file)  # type: ignore
            nebt_results: list[dict[str, Any]] = su.io.load(nebt_file)  # type: ignore

            id2ebt_eval: dict[str, dict[str, Any]] = {
                res["id"]: res for res in ebt_results
            }
            id2nebt_eval: dict[str, dict[str, Any]] = {
                res["id"]: res for res in nebt_results
            }
        else:
            prev_round = round_num - 1
            last_round_output: list[DataLLMOuput] = su.io.load(
                ThrowgenMacros.llm_output_dir
                / dataset_name
                / f"{self.llm_type}-{self.model_name}-{prompt_gen_name}@"
                f"{prev_round}-repair.jsonl",
                clz=DataLLMOuput,
            )  # type: ignore
            id2output: dict[str, DataLLMOuput] = {
                llm_out.id: llm_out for llm_out in last_round_output
            }

            ebt_file = (
                ThrowgenMacros.metrics_dir
                / dataset_name
                / f"run-ebts-{self.llm_type}-{self.model_name}-"
                f"{prompt_gen_name}@{prev_round}-repair"
                f"-each-sample.jsonl"
            )
            nebt_file = (
                ThrowgenMacros.metrics_dir
                / dataset_name
                / f"run-nebts-{self.llm_type}-{self.model_name}-"
                f"{prompt_gen_name}@{prev_round}-repair"
                f"-each-sample.jsonl"
            )
            # Load EBT and NEBT results separately
            ebt_results: list[dict[str, Any]] = su.io.load(ebt_file)  # type: ignore
            nebt_results: list[dict[str, Any]] = su.io.load(nebt_file)  # type: ignore

            id2ebt_eval: dict[str, dict[str, Any]] = {
                res["id"]: res for res in ebt_results
            }
            id2nebt_eval: dict[str, dict[str, Any]] = {
                res["id"]: res for res in nebt_results
            }
        # Build tasks (repair is always batch_size=1 per code sample)
        tasks: list[WorkerTask] = []
        for data in dataset:
            if data.id not in id2output:
                logger.warning(f"Skipping {data.id}: Output not found")
                continue
            past_output: DataLLMOuput = id2output[data.id]

            if data.id not in id2ebt_eval:
                logger.warning(f"Skipping {data.id}: EBT result not found")
                continue

            ebt_eval_data = id2ebt_eval[data.id]
            nebt_eval_data = id2nebt_eval.get(data.id, None)
            extracted_codes = past_output.extract_code()
            ebt_eval_results = ebt_eval_data["result"]
            nebt_eval_results = nebt_eval_data["result"] if nebt_eval_data else None

            for idx, (ebt_eval_result, code) in enumerate(
                zip(ebt_eval_results, extracted_codes, strict=True)
            ):
                nebt_eval_result = (
                    nebt_eval_results[idx] if nebt_eval_results and idx < len(nebt_eval_results) else None
                )
                messages = prompt_gen.get_message((data, code, ebt_eval_result, nebt_eval_result))
                tasks.append(
                    {
                        "data_ids": [data.id],
                        "task_idxs": [idx],
                        "messages_batch": [messages],
                        "sample_size": 1,
                        "temp": self.temp,
                    }
                )

        def process_task(task: WorkerTask, worker_id: int) -> WorkerResult:
            data_id = task["data_ids"][0]
            task_idx = task["task_idxs"][0]
            ebt_all_pass = id2ebt_eval[data_id]["result"][task_idx]["summary"]["all-pass"]
            nebt_all_pass = (
                id2nebt_eval[data_id]["result"][task_idx]["summary"]["all-pass"]
                if data_id in id2nebt_eval
                else True
            )
            if ebt_all_pass and nebt_all_pass:
                return {
                    "data_ids": [data_id],
                    "task_idxs": [task_idx],
                    "results_batch": [[id2output[data_id].preds[task_idx]]],
                }
            results = self._query_batch(
                task["messages_batch"],
                task["sample_size"],
                task["temp"],
                worker_id=worker_id,
            )
            return {
                "data_ids": [data_id],
                "task_idxs": [task_idx],
                "results_batch": results,
            }

        # Run inference
        output_path = (
            ThrowgenMacros.llm_output_dir
            / dataset_name
            / f"{self.llm_type}-{self.model_name}-{prompt_gen_type}-repair.jsonl"
        )
        out_results = self._run_experiment_with_threading(
            tasks, process_task, save_path=output_path
        )

        su.io.dump(
            output_path,
            out_results,
        )

    def do_dummy_experiment(self, dataset_name: str, prompt_gen_type: str):
        """
        running a dummy experiment which returns the user message always
        used for testing eval
        """
        logger.info(f"Doing a dummy experiment on dataset {dataset_name}")
        dataset = MultiEBTDataset.from_saved(
            ThrowgenMacros.mebt_data_dir / dataset_name
        )
        prompt_gen = self.PROMPT[prompt_gen_type]["gen"](
            *self.PROMPT[prompt_gen_type]["file"]
        )
        out_results = []
        for data in tqdm(dataset):
            messages = prompt_gen.get_message(data)
            dummy_pred = messages[1]["content"]
            out_results.append(DataLLMOuput(id=data.id, preds=[dummy_pred]))

        su.io.dump(
            ThrowgenMacros.llm_output_dir
            / dataset_name
            / f"{self.llm_type}-{self.model_name}-{prompt_gen_type}-dummy.jsonl",
            out_results,
        )

    # -----------------
    # helper functions
    # -----------------

    def _extract_code(self, res: str) -> str:
        code_match = re.search(
            r"```(\w*)\n([\s\S]*?)```",
            res,
            flags=re.MULTILINE,
        )
        if code_match is not None:
            return code_match.group(2)
        else:
            return ""


if __name__ == "__main__":
    import sys

    # Check if using multi-threading based on CLI args
    use_threading = "--num_workers" in " ".join(sys.argv) and any(
        arg.split("=")[-1] != "1" for arg in sys.argv if "--num_workers" in arg
    )

    if use_threading:
        with setup_thread_logging(logging.INFO, Macros.log_file):
            CLI(BaseExperiment, as_positional=False)
    else:
        su.log.setup(Macros.log_file)
        CLI(BaseExperiment, as_positional=False)
