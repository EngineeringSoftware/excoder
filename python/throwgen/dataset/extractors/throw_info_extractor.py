import os
from collections.abc import Iterator
from typing import Any

import seutil as su
from seutil.maven import SKIPS, MavenModule
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.class_info_extractor import ClassInfoExtractor
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override


class ThrowInfoExtractor(ClassInfoExtractor):
    PUBLIC_INFO_KEYS = ["public_constructors"]

    @override
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        """
        note that all_all data here is just for selected proj data
        """
        super().__init__(all_data, meta_data)
        self._param_compiled: set[str] = set()

    @property
    @override
    def field_name(self) -> str:
        return "throw_info"

    def extract_field(self, data: DataMultiEBT) -> dict[str, Any]:
        exceptions = [e.exception for e in data.ebts if e.exception is not None]
        return self._get_exceptions_constructors(exceptions, data)

    def _get_exceptions_constructors(
        self, exceptions: list[str], data: DataMultiEBT
    ) -> dict[str, Any]:
        maven_module = self._name2proj[data.project].modules[data.module_i]
        out = {}
        for i, exception_class in enumerate(exceptions):
            exception_file_path = os.path.join(
                maven_module.main_srcpath,
                exception_class.replace(".", "/") + ".java",
            )
            if os.path.isfile(exception_file_path):
                throw_info = self._get_class_info(
                    exception_file_path,
                    f"{data.id}-{i}",
                    exception_class.split(".")[-1],
                    False,
                    False,
                )
                out[exception_class] = throw_info
            else:
                collected_constructors = self._get_constructor_from_class(
                    maven_module, exception_class, data
                )
                if len(collected_constructors) > 0:
                    out[exception_class] = collected_constructors
        return out

    def _get_constructor_from_class(
        self, maven_module: MavenModule, exception_class: str, data: DataMultiEBT
    ) -> dict[str, list[str]]:
        with su.io.cd(ThrowgenMacros.java_src_dir):
            rr = su.bash.run(
                "java -cp "
                + f"target/throwgen-datacollection-1.0-SNAPSHOT-jar-with-dependencies.jar:{maven_module.dependency_classpath} "
                + f"org.throwgen.core.ConstructorCollector {exception_class} {data.id}.txt"
            )
            out = {}
            if rr.returncode == 0:
                with open(f"{data.id}.txt") as constructor_file:
                    collected_constructor = constructor_file.readlines()
                    out = {self.PUBLIC_INFO_KEYS[0]: collected_constructor}
                su.io.rm(f"{data.id}.txt")
            return out

    def _get_maven_modue_id(self, maven_module: MavenModule) -> str:
        return f"{maven_module.project}:{maven_module.coordinate}"

    def _compile_with_param(self, maven_module: MavenModule, timeout=600) -> bool:
        if self._get_maven_modue_id(maven_module) not in self._param_compiled:
            with su.io.cd(maven_module.dir / maven_module.rel_path):
                su.bash.run("mvn clean", 0)
                rr_comp = su.bash.run(
                    f"mvn test-compile {SKIPS} -Dmaven.compiler.parameters=true",
                    timeout=timeout,
                )
                if rr_comp.returncode != 0:
                    rr_package = su.bash.run(
                        f"mvn package -DskipTests {SKIPS} -Dmaven.compiler.parameters=true",
                        0,
                        timeout=timeout,
                    )
                    if rr_package.returncode != 0:
                        return False
        return True
