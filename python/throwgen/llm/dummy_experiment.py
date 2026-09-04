#!/usr/bin/env python3
import logging

import seutil as su
from etestgen.macros import Macros
from jsonargparse import CLI
from throwgen.llm.base_experiment import BaseExperiment
from throwgen.utils.multi_thread_n_logging import setup_thread_logging


class DummyExperiment(BaseExperiment):
    def __init__(
        self,
        model: str,
        num_workers: int = 1,
    ):
        super().__init__(model)
        self.llm_type = "dummy"

    def _query(
        self,
        chat: list[dict[str, str]],
        sample_size: int,
        temp: float,
        worker_id: int = 0,
    ) -> list[str]:
        return ["```java\n\n\n```"] * sample_size


if __name__ == "__main__":
    import sys

    # Check if using multi-threading based on CLI args
    use_threading = "--num_workers" in " ".join(sys.argv) and any(
        arg.split("=")[-1] != "1" for arg in sys.argv if "--num_workers" in arg
    )

    if use_threading:
        with setup_thread_logging(logging.INFO, Macros.log_file):
            CLI(DummyExperiment, as_positional=False)
    else:
        su.log.setup(Macros.log_file)
        CLI(DummyExperiment, as_positional=False)
