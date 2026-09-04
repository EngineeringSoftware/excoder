from collections.abc import Callable, Iterator
from typing import Any

from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_extractor import BaseExtractor
from throwgen.dataset.extractors.class_info_extractor import ClassInfoExtractor
from throwgen.dataset.extractors.coverage_extractor import CoverageExtractor
from throwgen.dataset.extractors.import_extractor import ImportExtractor
from throwgen.dataset.extractors.local_variable_type_extractor import \
    LocalVariableTypeExtractor
from throwgen.dataset.extractors.method_info_extractor import \
    MethodInfoExtractor
from throwgen.dataset.extractors.mut_no_throw_extractor import \
    MUTNoThrowExtractor
from throwgen.dataset.extractors.nebt_extractor import NEBTExtractor
from throwgen.dataset.extractors.throw_info_extractor import ThrowInfoExtractor
from throwgen.dataset.extractors.thrown_exception_extractor import \
    ThrownExceptionExtractor
from throwgen.dataset.extractors.tool_test_extractor import (
    EvosuiteTestExtractor,
    RandoopTestExtractor,
)
from throwgen.dataset.extractors.try_catch_add_extractor import \
    TryCatchAddExtractor
from throwgen.dataset.extractors.unre_exception_extractor import \
    UnreExceptionExtractor

NAME2EXTRACTORS: dict[
    str, Callable[[Iterator[DataMultiEBT], dict[str, Any]], BaseExtractor]
] = {
    MUTNoThrowExtractor.__name__: MUTNoThrowExtractor,
    ClassInfoExtractor.__name__: ClassInfoExtractor,
    NEBTExtractor.__name__: NEBTExtractor,
    ImportExtractor.__name__: ImportExtractor,
    ThrowInfoExtractor.__name__: ThrowInfoExtractor,
    UnreExceptionExtractor.__name__: UnreExceptionExtractor,
    MethodInfoExtractor.__name__: MethodInfoExtractor,
    CoverageExtractor.__name__: CoverageExtractor,
    TryCatchAddExtractor.__name__: TryCatchAddExtractor,
    ThrownExceptionExtractor.__name__: ThrownExceptionExtractor,
    LocalVariableTypeExtractor.__name__: LocalVariableTypeExtractor,
    RandoopTestExtractor.__name__: RandoopTestExtractor,
    EvosuiteTestExtractor.__name__: EvosuiteTestExtractor,
}
