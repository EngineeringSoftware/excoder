from abc import ABC, abstractmethod
from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT

logger = su.log.get_logger(__name__)


class BaseDataFilter(ABC):
    def __init__(self, meta_data: dict[str, Any]):
        logger.info(f"using {type(self).__name__} filter" )

    @abstractmethod
    def toss_data(self, data: DataMultiEBT) -> bool:
        pass
