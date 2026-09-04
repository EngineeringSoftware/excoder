from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT

logger = su.log.get_logger(__name__)


class BaseExtractor(ABC):
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        """
        :param all_data: the entire dataset, used mostly to extract information about the project names
        :param meta_data: extra information about dataset that can be useful
        """
        logger.info(f"Using {self.field_name} extractor")

    def setup(self):
        logger.info(f"No setup for {self.field_name}")

    @property
    @abstractmethod
    def field_name(self) -> str:
        pass

    @abstractmethod
    def extract_field(self, data: DataMultiEBT) -> Any:
        pass
