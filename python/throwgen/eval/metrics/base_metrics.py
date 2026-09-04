import pprint
from abc import ABC, abstractmethod
from typing import Any

import seutil as su
from etestgen.utils import aggregate_metrics, summarize_metrics
from throwgen.dataset.data import DataLLMOuput
from throwgen.dataset.multi_ebt_data import MultiEBTDataset
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.utils.output_process import strip_thinking

logger = su.log.get_logger(__name__, su.log.INFO)


class BaseMetrics(ABC):
    def __init__(
        self,
        llm_type: str,
        model_name: str,
        setup: str,
        dataset_name: str,
        prompt_gen_type: str,
    ):
        self._llm_type = llm_type
        self._model_name = model_name
        self._setup = setup
        self._dataset_name = dataset_name
        self._prompt_gen_type = prompt_gen_type
        results: list[DataLLMOuput] = su.io.load(
            ThrowgenMacros.llm_output_dir
            / dataset_name
            / f"{self._llm_type}-{self._model_name}-{self._prompt_gen_type}-{self._setup}.jsonl",
            clz=DataLLMOuput,
        )  # type: ignore
        for res in results:
            res.preds = [strip_thinking(p, llm_type, model_name) for p in res.preds]
        self._id2result: dict[str, DataLLMOuput] = {res.id: res for res in results}
        dataset = MultiEBTDataset.from_saved(
            ThrowgenMacros.mebt_data_dir / dataset_name
        )
        self._id2data = {data.id: data for data in dataset}

    @property
    @abstractmethod
    def _metrics_type(self) -> str:
        pass

    @abstractmethod
    def _eval_metrics(
        self,
    ) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
        raise NotImplementedError("eval is not implemented")

    def run_eval(self):
        pred_metrics, each_sample_results = self._eval_metrics()
        metrics_summary = summarize_metrics(aggregate_metrics(pred_metrics))  # type: ignore
        su.io.dump(
            ThrowgenMacros.metrics_dir
            / self._dataset_name
            / (
                f"{self._metrics_type}-{self._llm_type}-{self._model_name}-{self._prompt_gen_type}-{self._setup}-summary.json"
            ),
            metrics_summary,
            su.io.Fmt.jsonPretty,
        )
        su.io.dump(
            ThrowgenMacros.metrics_dir
            / self._dataset_name
            / (
                f"{self._metrics_type}-{self._llm_type}-{self._model_name}-{self._prompt_gen_type}-{self._setup}-each-sample.jsonl"
            ),
            each_sample_results,
        )
        logger.info(
            f"{self._metrics_type} summary:\n" + pprint.pformat(metrics_summary)
        )
