from abc import ABC, abstractmethod
from typing import Any

import seutil as su
from etestgen.macros import Macros
from throwgen.dataset.data import DataMultiEBT

logger = su.log.get_logger(__name__)


class BaseEditorModule(ABC):
    def __init__(self, desc_file_name: str):
        logger.info(f"using {self.edit_name} editor")
        editor_dir = (
            Macros.python_dir / "throwgen" / "prompt" / "prompt_text" / "editor_desc"
        )
        with open(editor_dir / f"{desc_file_name}.txt") as desc_file:
            self._desc = desc_file.read()

    @property
    @abstractmethod
    def edit_name(self) -> str:
        pass

    @property
    @abstractmethod
    def base_name(self) -> str:
        pass

    def data_available(self, base_field: str, data: DataMultiEBT) -> bool:
        return base_field != self._make_edit(base_field, data)

    @abstractmethod
    def _make_edit(self, base_field: str, data: DataMultiEBT) -> str:
        pass

    def __call__(self, base_field: str, data: DataMultiEBT) -> Any:
        out = self._make_edit(base_field, data)
        return out
