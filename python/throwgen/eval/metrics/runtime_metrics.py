import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import seutil as su
from etestgen.data.tool import Tool
from etestgen.eval.compute_throws_coverage import TestMethod
from etestgen.macros import Macros
from etestgen.utils import summarize_topk_metrics
from jsonargparse import CLI
from seutil.bash import BashError
from seutil.maven import SKIPS, MavenModule, MavenProject
from seutil.project import Project
from throwgen.dataset.data import DataLLMOuput
from throwgen.eval.metrics.base_metrics import BaseMetrics
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.repos import load_all_projects
from throwgen.utils.multi_process_n_logging import (pool_w_log,
                                                    setup_logging_queue)
from tqdm import tqdm
from typing_extensions import override

TIMEOUT = 600
TEST_PLACEHOLDER = "/*TEST PLACEHOLDER*/"
logger = su.log.get_logger(__name__)

def nested_defaultdict_list():
    return defaultdict(list)

class RuntimeMetrics(BaseMetrics):
    @override
    def __init__(
        self,
        llm_type: str,
        model_name: str,
        setup: str,
        dataset_name: str,
        prompt_gen_type: str,
        test_type: Literal["nebts", "ebts"] = "ebts",
        num_workers: int = 1,
    ):
        super().__init__(llm_type, model_name, setup, dataset_name, prompt_gen_type)
        self._test_type = test_type

        assert num_workers > 0
        self._silence_low_level_tqdm = num_workers > 1
        self._num_workers = num_workers

        self._maven_out_path = ThrowgenMacros.maven_out_dir / "no-throw"
        self._work_dir = su.io.mktmp_dir(f"throwgen-run-{time.time()}")

        self._projects: list[Project] = load_all_projects()

        self._proj_mod_to_result = defaultdict(nested_defaultdict_list)
        for key, res in self._id2result.items():
            local_proj_name = self._id2data[key].project
            local_module_i = self._id2data[key].module_i
            self._proj_mod_to_result[local_proj_name][local_module_i].append(res)

        self._proj_to_modules = defaultdict(set)
        for key in self._id2result:
            project_name = self._id2data[key].project
            module_i = self._id2data[key].module_i
            self._proj_to_modules[project_name].add(module_i)

    @property
    @override
    def _metrics_type(self) -> str:
        return f"run-{self._test_type}"

    @override
    def _eval_metrics(
        self,
    ) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
        eval_proj_set = list(self._proj_to_modules.keys())
        projects_for_evaluation = [
            p for p in self._projects if p.full_name in eval_proj_set
        ]
        runtime_metrics = []
        each_sample_results = []
        if self._num_workers == 1:
            # don't start another process in this case
            for proj in tqdm(projects_for_evaluation, desc="Projects"):
                # target modules
                project_metrics, esr_project = self._secure_proj_runtime_metrics(proj)
                runtime_metrics += project_metrics
                each_sample_results += esr_project
        else:
            with pool_w_log(self._num_workers) as pool:
                for project_metrics, esr_project in tqdm(
                    pool.imap(
                        self._secure_proj_runtime_metrics, projects_for_evaluation
                    ),
                    total=len(projects_for_evaluation),
                ):
                    runtime_metrics += project_metrics
                    each_sample_results += esr_project

        # remove work dir to avoid piling up
        su.io.rmdir(self._work_dir, force=True)
        return runtime_metrics, each_sample_results

    def _secure_proj_runtime_metrics(
        self, project: Project
    ) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
        try:
            return self._eval_proj_runtime_metrics(project)
        except BashError as e:
            logger.warning(f"error when evaling {project.full_name}: {e}")
            return [], []
        except ValueError as e:
            logger.warning(f"value error when evaling {project.full_name}: {e}")
            return [], []

    def _eval_proj_runtime_metrics(
        self,
        project: Project,
    ) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
        project.clone(Macros.downloads_dir)
        project.checkout(project.data["sha"], forced=True)

        # move project to avoid clashing
        new_project_path = self._work_dir / project.full_name
        su.bash.run(f"cp -r {project.dir} {new_project_path}")
        project.set_cloned_dir(new_project_path)

        runtime_out_dir = self._maven_out_path / "runtime_logs"
        out_dir = runtime_out_dir / project.full_name
        su.io.mkdir(out_dir)

        project_results = []
        each_sample_result = []
        # set up environment
        maven_proj = MavenProject.from_project(project)
        self.checkout_and_compile_project(maven_proj, project)
        for module_i, _ in tqdm(
            enumerate(maven_proj.modules),
            desc="Modules",
            disable=self._silence_low_level_tqdm,
        ):
            if module_i not in self._proj_to_modules[project.full_name]:
                continue
            module_results, esrs_module = self._eval_module_runtime_metrics(
                maven_module=maven_proj.modules[module_i],
                module_llm_output=self._proj_mod_to_result[project.full_name][module_i],
            )
            project_results += module_results
            each_sample_result += esrs_module

        # remove copied dir to save space
        su.io.rmdir(new_project_path, force=True)
        return project_results, each_sample_result

    def _eval_module_runtime_metrics(
        self,
        maven_module: MavenModule,
        module_llm_output: list[DataLLMOuput],
    ) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
        # prepare work dir and out dir
        out_metrics = []
        each_method = []
        work_dir = su.io.mktmp_dir("etestgen")

        for dlo in tqdm(
            module_llm_output, desc="Methods", disable=self._silence_low_level_tqdm
        ):
            try:
                metrics, each_sample = self._eval_sample_metrics(
                    work_dir=work_dir,
                    maven_module=maven_module,
                    llm_output=dlo,
                )
                if len(metrics) > 0:
                    out_metrics.append(metrics)
                    each_method.append({"id": dlo.id, "result": each_sample})
            except FileNotFoundError:
                logger.warning(f"file not found error at {dlo.id}")
        su.io.rmdir(work_dir)
        return out_metrics, each_method

    def _eval_sample_metrics(
        self,
        work_dir: Path,
        maven_module: MavenModule,
        llm_output: DataLLMOuput,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        sample_metrics = defaultdict(list)
        if self._test_type == "ebts":
            tests = self._id2data[llm_output.id].ebts
        elif self._test_type == "nebts":
            tests = self._id2data[llm_output.id].nebts
        else:
            raise ValueError(f"{self._test_type} is not a valid test type")
        if len(tests) == 0:
            return {}, []
        run_path = work_dir / "run"
        su.io.mkdir(run_path, fresh=True)
        test_paths = self._prepare_tests(run_path=run_path, tests=tests)

        classpath = os.pathsep.join(
            [
                maven_module.main_classpath,
                maven_module.test_classpath,
                maven_module.dependency_classpath,
            ]
        )

        each_sample = []
        for code in tqdm(
            llm_output.extract_code(),
            desc="Samples",
            disable=self._silence_low_level_tqdm,
        ):
            runtime_metrics, each_test = self._eval_code_metrics(
                run_path=run_path,
                test_paths=test_paths,
                maven_module=maven_module,
                classpath=classpath,
                code=code,
                data_id=llm_output.id,
            )

            each_sample.append(each_test)
            for k, v in runtime_metrics.items():
                sample_metrics[k].append(v)

        # aggregate topk metrics
        sum_metrics = summarize_topk_metrics(sample_metrics)
        return sum_metrics, each_sample

    def _prepare_tests(
        self,
        run_path: Path,
        tests: list[TestMethod],
    ) -> dict[str, Path]:
        out = {}
        for gold_test in tests:
            package = ".".join(gold_test.cname.split(".")[0:-1])
            csname = "adhoc_" + gold_test.cname.split(".")[-1] + gold_test.mname
            test_name = package + "." + csname
            test_path = run_path / package.replace(".", "/") / f"{csname}.java"
            ccontext = gold_test.ccontext
            test_file_content = ccontext.replace(  # type: ignore
                TEST_PLACEHOLDER, gold_test.raw_code
            ).replace("adhoc_" + gold_test.cname.split(".")[-1], csname)

            Tool.ensure_tool_versions()
            Tool.require_compiled()
            new_test_file_content = self.add_throws_keyword(test_file_content)
            su.io.dump(test_path, new_test_file_content, su.io.Fmt.txt)
            out[test_name] = test_path
        return out

    def _eval_code_metrics(
        self,
        run_path: Path,
        test_paths: dict[str, Path],
        maven_module: MavenModule,
        classpath: str,
        code: str,
        data_id: str,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        mut_key = self._id2data[data_id].mut_key
        mut_file_path = os.path.join(
            maven_module.main_srcpath,
            mut_key.split("#")[0].split("$")[0].replace(".", "/") + ".java",
        )
        with open(mut_file_path) as mut_file_r:
            mut_context_lines = mut_file_r.readlines()

        mut_context_gold = "".join(mut_context_lines)
        mut_context_up = "".join(
            mut_context_lines[: self._id2data[data_id].start_line - 1]
        )
        mut_context_down = "".join(mut_context_lines[self._id2data[data_id].end_line :])
        new_mut_context = mut_context_up + code + mut_context_down
        self._write_in_chuncks(new_mut_context, mut_file_path)

        out = {
            "compiled": 0,
            "pass-ratio": 0.0,
            "all-pass": 0,
        }
        # compile the module with new method
        rr_module = self.compile_module(maven_module)
        module_result = {
            "success": rr_module.returncode == 0,
            "stdout": rr_module.stdout,
            "stderr": rr_module.stderr,
        }
        if rr_module.returncode != 0:
            self._write_in_chuncks(mut_context_gold, mut_file_path)
            return out, {
                "summary": out,
                "module_result": module_result,
                "each_test": [],
            }

        out["compiled"] = 1
        pass_cnt = 0
        each_test_results = []
        with su.io.cd(run_path):
            # compile the test
            for tname, tpath in test_paths.items():
                rr_comp = su.bash.run(f"javac -cp {classpath} {tpath}")
                if rr_comp.returncode == 0:
                    try:
                        rr_run = su.bash.run(
                            f"java -cp .:{Tool.rt_jar}:{classpath} -ea org.junit.runner.JUnitCore {tname}",
                            timeout=TIMEOUT,
                        )

                    except su.bash.subprocess.TimeoutExpired:
                        each_test_results.append(
                            {
                                "compiled": True,
                                "passed": False,
                                "stdout": "Timeout",
                                "stderr": "Timeout",
                            }
                        )
                        continue
                    if rr_run.returncode == 0:
                        pass_cnt += 1
                        each_test_results.append(
                            {
                                "compiled": True,
                                "passed": True,
                                "stdout": rr_run.stdout,
                                "stderr": rr_run.stderr,
                            }
                        )
                    else:
                        each_test_results.append(
                            {
                                "compiled": True,
                                "passed": False,
                                "stdout": rr_run.stdout,
                                "stderr": rr_run.stderr,
                            }
                        )
                else:
                    print(rr_comp.stderr)
                    each_test_results.append(
                        {
                            "compiled": False,
                            "passed": False,
                            "stdout": rr_comp.stdout,
                            "stderr": rr_comp.stderr,
                        }
                    )

        out["pass-ratio"] = pass_cnt / len(test_paths)
        out["all-pass"] = pass_cnt == len(test_paths)

        self._write_in_chuncks(mut_context_gold, mut_file_path)

        return out, {
            "summary": out,
            "module_result": module_result,
            "each_test": each_test_results,
        }

    # ------------------
    # Helper functions
    # ------------------
    #

    @staticmethod
    def add_throws_keyword(
        test_file_content: str,
    ):
        """
        Add 'throws Exception' to the generated test method.
        """
        temp_dir = su.io.mktmp_dir("etestgen")
        su.io.dump(temp_dir / "temp.java", test_file_content, su.io.Fmt.txt)
        test_config = {
            "inFile": str(temp_dir / "temp.java"),
            "outPath": str(temp_dir / "temp.java"),
        }
        test_config_path = temp_dir / "manual.config.json"
        su.io.dump(test_config_path, test_config)
        try:
            su.bash.run(
                f"java -cp {Tool.core_jar} org.etestgen.core.AddThrowModifier {test_config_path}",
                0,
            )
        except:
            # logger.warning("Failed to add throws keyword to %s", test_file_content)
            pass

        test = su.io.load(temp_dir / "temp.java", su.io.Fmt.txt)
        su.io.rmdir(temp_dir)
        return test

    @staticmethod
    def _write_in_chuncks(text: str, output_path: Path | str):
        buffer_size = 2 * 12
        chunk_size = 2**15
        with open(output_path, "wb", buffering=buffer_size) as f:
            for i in range(0, len(text), chunk_size):
                chunk = text[i : i + chunk_size]
                f.write(chunk.encode("utf-8"))

    @staticmethod
    def compile_module(maven_module: MavenModule):
        with su.io.cd(maven_module.dir):
            su.bash.run("mvn clean", 0)
            rr = su.bash.run(f"mvn test-compile {SKIPS}", timeout=TIMEOUT)
        return rr

    def checkout_and_compile_project(self, maven_proj: MavenProject, project: Project):
        """
        Checkout and compile the project.
        """
        su.io.dump(self._maven_out_path / "maven.yaml", maven_proj)
        project.checkout(project.data["sha"], forced=True)
        with su.io.cd(project.dir):
            su.bash.run("git clean -ffdx")
        maven_proj.backup_pom()
        maven_proj.hack_pom_delete_plugin("maven-dependency-plugin")
        maven_proj.hack_pom_delete_plugin("maven-checkstyle-plugin")
        maven_proj.compile()


if __name__ == "__main__":
    listener = setup_logging_queue()
    try:
        CLI(RuntimeMetrics, as_positional=False)
    finally:
        listener.stop()
