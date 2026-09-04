import os
import re
from collections.abc import Iterator
from typing import Any

import seutil as su
from etestgen.macros import Macros
from seutil.maven import MavenProject
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_extractor import BaseExtractor
from throwgen.repos import load_all_projects
from tqdm import tqdm
from typing_extensions import override

logger = su.log.get_logger(__name__)


class ImportExtractor(BaseExtractor):
    @override
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        super().__init__(all_data, meta_data)

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
        return "import_info"

    @override
    def setup(self):
        logger.info(f"Setting up for {self.field_name} extractor")
        for proj in tqdm(self._projects, desc="iterating projects"):
            proj.clone(Macros.downloads_dir)
            proj.checkout(proj.data["sha"], forced=True)

    @override
    def extract_field(self, data: DataMultiEBT) -> list[str]:
        maven_module = self._name2proj[data.project].modules[data.module_i]
        target_class_name = data.mut_key.split("#")[0].split("$")[0]
        target_file_path = os.path.join(
            maven_module.main_srcpath,
            target_class_name.split("$")[0].replace(".", "/") + ".java",
        )
        with open(target_file_path) as target_file:
            java_content = target_file.read()

        return re.findall(r"import\s+(?:static\s+)?([\w.]+\*?);", java_content)
