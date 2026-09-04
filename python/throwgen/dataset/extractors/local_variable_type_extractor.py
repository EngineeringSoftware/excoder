import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import seutil as su
from seutil.maven import MavenModule, MavenProject
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.class_info_extractor import ClassInfoExtractor
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override


class LocalVariableTypeExtractor(ClassInfoExtractor):
    @property
    @override
    def field_name(self) -> str:
        return "local_variable_type"

    @override
    def extract_field(self, data: DataMultiEBT) -> dict[str, dict[str, list[str]]]:
        maven_module = self._name2proj[data.project].modules[data.module_i]
        all_classes = self._get_all_classes(maven_module.main_srcpath)
        class_list = self._get_local_var_types(
            self._preprocess_code(data.mut_no_throw), data.id
        )
        out: dict[str, dict[str, list[str]]] = {}
        for cn in class_list:
            class_name = self._get_full_class_path(cn, all_classes)
            if class_name is not None:
                class_info = self._get_all_class_info(
                    maven_module.main_srcpath,
                    data.id,
                    class_name,
                    False,
                )
                if class_info is not None:
                    out[class_name] = class_info
        return out

    def _get_local_var_types(self, code: str, id: str) -> list[str]:
        with su.io.cd(ThrowgenMacros.java_src_dir):
            with open(f"{id}.java", "w") as throw_mut_file:
                throw_mut_file.write(code)
            rr = su.bash.run(
                "java -cp "
                + "target/throwgen-datacollection-1.0-SNAPSHOT-jar-with-dependencies.jar "
                + f"org.throwgen.core.LocalVariableTypeCollector {id}.java vars.txt"
            )
            if rr.returncode != 0:
                raise OSError(f"Remove throw error in {id}.java\n\n{rr.stderr}")

            su.bash.run(f"rm {id}.java")
            local_var_types = []
            with open("vars.txt") as vars_file:
                for var_type in vars_file.readlines():
                    local_var_types += self._process_template(var_type)
            su.bash.run("rm vars.txt")

        return local_var_types

    def _preprocess_code(self, code: str) -> str:
        if re.search(r"\sdefault\s", " " + code) is None:
            self._class_header = "class temp"
        else:
            self._class_header = "interface temp"
        self._preprocessed = True
        return self._class_header + " {" + code + "}"
