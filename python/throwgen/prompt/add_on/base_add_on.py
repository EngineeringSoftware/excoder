from abc import ABC, abstractmethod
from typing import Any

import seutil as su
from etestgen.macros import Macros
from throwgen.dataset.data import DataMultiEBT

logger = su.log.get_logger(__name__)


class BaseAddOn(ABC):
    def __init__(self, desc_file_name: str):
        logger.info(f"using {self.field_name} add on")
        add_on_dir = (
            Macros.python_dir / "throwgen" / "prompt" / "prompt_text" / "add_on_desc"
        )
        with open(add_on_dir / f"{desc_file_name}.txt") as desc_file:
            self._desc = desc_file.read()

    @abstractmethod
    def data_available(self, data: DataMultiEBT, curr_args: dict[str, str]) -> bool:
        pass

    @property
    @abstractmethod
    def field_name(self) -> str:
        pass

    @abstractmethod
    def add_on_arg(self, data: DataMultiEBT, curr_args: dict[str, str]):
        pass

    @abstractmethod
    def _get_arg(self, data: DataMultiEBT, curr_args: dict[str, str]) -> str:
        pass
