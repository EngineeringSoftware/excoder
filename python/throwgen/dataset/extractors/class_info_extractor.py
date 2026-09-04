import json
import os
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import seutil as su
from etestgen.macros import Macros
from seutil.maven import MavenProject
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_extractor import BaseExtractor
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.repos import load_all_projects
from tqdm import tqdm
from typing_extensions import override

logger = su.log.get_logger(__name__)


class ClassInfoExtractor(BaseExtractor):
    PUBLIC_INFO_KEYS = ["public_variables", "public_methods"]
    PRIVATE_INFO_KEYS = ["private_variables", "private_methods"]
    PROTECTED_INFO_KEYS = ["protected_variables", "protected_methods"]

    @override
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        """
        note that all_all data here is just for selected proj data
        """
        super().__init__(all_data, meta_data)

        # build tools in java
        with su.io.cd(ThrowgenMacros.java_src_dir):
            rr = su.bash.run("mvn clean compile assembly:single")
            if rr.returncode != 0:
                raise OSError(f"mvn build ends in error:\n\n{rr.stderr}")

        # get prjects info for all projects in dataset
        all_projects = load_all_projects()
        selected_projs = set()
        for data in all_data:
            selected_projs.add(data.project)
        self._projects = [
            proj for proj in all_projects if proj.full_name in selected_projs
        ]

        # clone and setup project
        for proj in self._projects:
            proj.set_cloned_dir(Macros.downloads_dir / proj.full_name)
        maven_projs = [MavenProject.from_project(prj) for prj in tqdm(self._projects)]
        self._name2proj = {
            proj.full_name: mvnproj
            for (proj, mvnproj) in zip(self._projects, maven_projs, strict=False)
        }

    @property
    @override
    def field_name(self) -> str:
        return "class_info"

    @override
    def setup(self):
        logger.info(f"Setting up for {self.field_name} extractor")
        for proj in tqdm(self._projects, desc="iterating projects"):
            proj.clone(Macros.downloads_dir)
            proj.checkout(proj.data["sha"], forced=True)

    def _get_full_class_path(
        self, short_class_name: str, all_classes: list[str]
    ) -> str | None:
        for cn in all_classes:
            if cn.endswith(short_class_name):
                return cn
        return None

    def _get_all_classes(self, project_path: Path | str) -> list[str]:
        out = []
        for root, _, files in os.walk(project_path):
            for file_name in files:
                if file_name.endswith(".java"):
                    out.append(os.path.join(root, file_name).replace("/", "."))
        return out

    def _process_template(self, type_name: str) -> list[str]:
        type_match = re.match(r"(.[^<>]*)(?:<(.*)>)?", type_name)
        assert type_match is not None
        out = [type_match.group(1)]
        if type_match.group(2):
            out.append(type_match.group(2))
        return out

    def _get_parent_class(
        self, class_path: Path | str, target_class_name: str
    ) -> str | None:
        with su.io.cd(ThrowgenMacros.java_src_dir):
            rr = su.bash.run(
                "java -cp "
                + "target/throwgen-datacollection-1.0-SNAPSHOT-jar-with-dependencies.jar"
                + f":{class_path} "
                + f"org.throwgen.core.ParentFinder {target_class_name}"
            )
            if rr.returncode != 0:
                raise OSError(f"Parent class find error in {id}.java\n\n{rr.stderr}")
            parent_match = re.search("parent_class:([0-9a-zA-Z/_]*);", rr.stdout)
            if parent_match is None:
                raise OSError(f"Parent class find returned nothing")
            else:
                parent_name = parent_match.group(1)
                if parent_name == "null":
                    return None
                else:
                    return parent_name

    def _get_all_class_info(
        self,
        project_path: Path | str,
        data_id: str,
        full_target_class_name: str,
        is_this: bool,  # whether collection class info for the class MUT is in
    ) -> dict[str, list[str]] | None:
        out = defaultdict(list)
        seen_methods = set()
        curr_code_path = os.path.join(
            project_path,
            full_target_class_name.split("$")[0].replace(".", "/") + ".java",
        )
        curr_class_name = full_target_class_name.split("$")[-1].split(".")[-1]
        curr_include_private = is_this

        while os.path.isfile(curr_code_path):
            current_class_info = self._get_class_info(
                curr_code_path,
                data_id + curr_class_name,
                curr_class_name,
                curr_include_private,
                is_this,  # collect protected if is this
            )
            curr_include_private = False  # private of parent classes cannot be called
            for info_key, info_list in current_class_info.items():
                for info in info_list:
                    signature_match = re.match(r"[\w<>\[\]]+\s+\w+\s*\(.*?\)", info)
                    if signature_match is not None:
                        if signature_match.group(0) not in seen_methods:
                            out[info_key].append(info)
                            seen_methods.add(signature_match.group(0))
                    else:
                        out[info_key].append(info)

            # get parent class path
            project_class_path = os.path.join(project_path, "target/classes")
            parent_class_name = self._get_parent_class(
                project_class_path, curr_class_name
            )
            if parent_class_name is not None:
                curr_code_path = os.path.join(
                    project_path, parent_class_name.replace(".", "/") + ".java"
                )
                curr_class_name = parent_class_name.split(".")[-1]
            else:
                break
        return out

    def _get_class_info(
        self,
        code_path: Path | str,
        data_id: str,
        target_class_name: str,
        include_private: bool,
        include_protected: bool,
    ) -> dict[str, list[str]]:
        with su.io.cd(ThrowgenMacros.java_src_dir):
            rr = su.bash.run(
                "java -cp "
                + "target/throwgen-datacollection-1.0-SNAPSHOT-jar-with-dependencies.jar "
                + "org.throwgen.core.ClassDataCollector "
                + f"{code_path} {data_id}.json {target_class_name}"
            )
            if rr.returncode != 0:
                raise OSError(
                    f"Class info extraction error in {id}.java\n\n{rr.stderr}"
                )
            with open(f"{data_id}.json") as class_data_file:
                collector_out = json.load(class_data_file)
                out = {
                    k: v for k, v in collector_out.items() if k in self.PUBLIC_INFO_KEYS
                }
                if include_private:
                    out.update(
                        {
                            k: v
                            for k, v in collector_out.items()
                            if k in self.PRIVATE_INFO_KEYS
                        }
                    )
                if include_protected:
                    out.update(
                        {
                            k: v
                            for k, v in collector_out.items()
                            if k in self.PROTECTED_INFO_KEYS
                        }
                    )
            su.bash.run(f"rm {data_id}.json")
        return out

    @override
    def extract_field(self, data: DataMultiEBT) -> dict[str, Any]:
        maven_module = self._name2proj[data.project].modules[data.module_i]
        mut_key = data.mut_key

        out = self._get_all_class_info(
            maven_module.main_srcpath,
            data.id,
            mut_key.split("#")[0].split("$")[0],
            True,
        )
        if out is None:
            return {}
        else:
            return out
