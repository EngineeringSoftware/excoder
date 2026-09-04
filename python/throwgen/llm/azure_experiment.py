import asyncio
import os

import seutil as su
from azure.ai.inference.aio import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from etestgen.macros import Macros
from jsonargparse import CLI
from throwgen.llm.base_experiment import BaseExperiment

logger = su.log.get_logger(__name__, su.log.INFO)
PRICE_LIMIT = 200
PRICING_TABLE = {
    "gpt-5-mini": {
        "input": 0.28 / 1e6,
        "output": 2.0 / 1e6,
    }
}
SAMPLE_SIZE_MAX = 8


class AzureExperiment(BaseExperiment):
    def __init__(
        self,
        model: str,
        num_workers: int = 1,
    ):
        super().__init__(model, num_workers)
        self.llm_type = "azure"
        self._usage = 0

    def _check_usage(self, res) -> bool:
        self._usage += (
            res.usage.prompt_tokens * PRICING_TABLE[self.model_name]["input"]  # type: ignore
        )
        self._usage += (
            res.usage.completion_tokens  # type: ignore
            * PRICING_TABLE[self.model_name]["output"]
        )
        logger.info(f"Current usage: {self._usage}")
        return self._usage <= PRICE_LIMIT

    def _query(
        self,
        chat: list[dict[str, str]],
        sample_size: int,
        temp: float,
        worker_id: int = 0,
    ) -> list[str]:
        if self._usage >= PRICE_LIMIT:
            return ["price limit reached"] * sample_size
        out = []

        while len(out) < sample_size:
            local_size = sample_size - len(out)
            if local_size > SAMPLE_SIZE_MAX:
                local_size = SAMPLE_SIZE_MAX
            client = ChatCompletionsClient(
                endpoint=os.environ["AZURE_END_POINT"],
                model=self.model_name,
                credential=AzureKeyCredential(os.environ["AZURE_API_KEY"]),
            )
            response = asyncio.run(
                client.complete(messages=chat, model_extras=[("n", local_size)])  # type: ignore
            )
            out += [c.message.content for c in response.choices]
            print(len(out))
            asyncio.run(client.close())

            if not self._check_usage(response):
                logger.info("Price limit reached, only filler from now.")
        return out  # type: ignore


if __name__ == "__main__":
    import logging
    import sys

    from throwgen.utils.multi_thread_n_logging import setup_thread_logging

    # Check if using multi-threading based on CLI args
    use_threading = "--num_workers" in " ".join(sys.argv) and any(
        arg.split("=")[-1] != "1" for arg in sys.argv if "--num_workers" in arg
    )

    if use_threading:
        with setup_thread_logging(logging.INFO, Macros.log_file):
            CLI(AzureExperiment, as_positional=False)
    else:
        su.log.setup(Macros.log_file)
        CLI(AzureExperiment, as_positional=False)
