from collections import defaultdict
from collections.abc import Iterator
import os
from typing import Any

import seutil as su
import tqdm
from etestgen.eval import (
    collect_stack_trace_from_netest,
    compute_etest_coverage,
    compute_test_coverage,
)
from etestgen.eval.compute_test_coverage import TestMethod
from etestgen.macros import Macros
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_extractor import BaseExtractor
from throwgen.repos import load_all_projects
from typing_extensions import override

logger = su.log.get_logger(__name__)


class NEBTExtractor(BaseExtractor):
    @override
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        """
        note that all_all data here is just for selected proj data
        """
        super().__init__(all_data, meta_data)
        all_projects = load_all_projects()
        selected_projs = set()
        for data in all_data:
            selected_projs.add(data.project)
        self._projects = [
            proj for proj in all_projects if proj.full_name in selected_projs
        ]
        self._coverage_dir = Macros.work_dir / "coverage-new"
        self._module2tests_cov: dict[str, dict[str, list[TestMethod]]] = {}

    @property
    @override
    def field_name(self) -> str:
        return "nebts"

    @override
    def setup(self):
        logger.info(f"Setting up for {self.field_name} extractor")
        # Scratch: the subset of the repository lists this extractor runs on.
        # Written under _work rather than next to the curated lists in repos/,
        # which is version controlled.
        temp_repos_file_path = Macros.work_dir / "temp-repos.json"
        su.io.dump(temp_repos_file_path, self._projects)

        etest_cov_collector = compute_etest_coverage.EtestCoverageComputer()
        test_cov_collector = compute_test_coverage.TestCoverageCollector()
        stacktrace_collector = collect_stack_trace_from_netest.TestStackTraceCollector()
        etest_cov_collector.compute_coverage_data(repos_file=temp_repos_file_path)
        test_cov_collector.compute_netest_coverage(repos_file=temp_repos_file_path)
        stacktrace_collector.compute_netest_coverage(
            out_dir=self._coverage_dir, repos_file=temp_repos_file_path
        )

        for project in tqdm.tqdm(self._projects, desc="generating stack trace"):  #  type: ignore
            stacktrace_collector.collect_project_stack_trace_with_etypes(
                project, out_dir=self._coverage_dir / project.full_name
            )

    @override
    def extract_field(self, data: DataMultiEBT) -> list[TestMethod]:
        self._load_module_test_coverage(data.project, data.module_i)
        return self._module2tests_cov[f"{data.project}.{data.module_i}"][data.mut_key]

    def _load_module_test_coverage(
        self,
        proj_name: str,
        module_i: int,
    ):
        """
        load coverage data of proj_name.module_id into self._module2tests_cov
        data is already loaded return without doing anything
        """

        if f"{proj_name}.{module_i}" in self._module2tests_cov:
            return

        module_cov_dir = self._coverage_dir / proj_name / str(module_i)
        try:
            test_methods: list[TestMethod] = su.io.load(
                module_cov_dir / "manual.tests.jsonl",
                clz=TestMethod,
            )  # type: ignore
            netest_coverage: list[dict[str, Any]] = su.io.load(
                module_cov_dir / "netest-coverage.jsonl"
            )  # type: ignore
            mut2tests = defaultdict(list)
            for n_cov in netest_coverage:
                for mut_id in n_cov["methods"]:
                    mut2tests[mut_id.replace("/", ".")].append(
                        test_methods[n_cov["test_i"]]
                    )
            self._module2tests_cov[f"{proj_name}.{module_i}"] = mut2tests
        except FileNotFoundError:
            logger.warning(
                f"{proj_name}.{module_i} have an error when extracting coverage, no nebt is loaded"
            )
            self._module2tests_cov[f"{proj_name}.{module_i}"] = defaultdict(list)
