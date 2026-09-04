import os
from pathlib import Path
from typing import Any

import seutil as su
from etestgen.data.tool import Tool
from etestgen.macros import Macros
from jsonargparse import CLI
from seutil.maven import MavenModule
from throwgen.eval.metrics.runtime_metrics import TIMEOUT, RuntimeMetrics
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override
from throwgen.utils.multi_process_n_logging import (pool_w_log,
                                                    setup_logging_queue)

logger = su.log.get_logger(__name__, su.log.INFO)
class CoverageCollector(RuntimeMetrics):
    def __init__(
        self,
        llm_type: str,
        model_name: str,
        setup: str,
        dataset_name: str,
        prompt_gen_type: str,
        num_workers: int = 1,
    ):
        super().__init__(
            llm_type,
            model_name,
            setup,
            dataset_name,
            prompt_gen_type,
            num_workers=num_workers,
        )
        with su.io.cd(ThrowgenMacros.java_src_dir):
            rr = su.bash.run("mvn clean compile assembly:single")
            if rr.returncode != 0:
                raise OSError(f"mvn build ends in error:\n\n{rr.stderr}")
        self._agent_path = (
            ThrowgenMacros.java_src_dir
            / "target"
            / "throwgen-datacollection-1.0-SNAPSHOT-jar-with-dependencies.jar"
        )

    @property
    @override
    def _metrics_type(self) -> str:
        return "coverage"

    @override
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

        out = {"place_holder": 0.0}
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

        each_test_results = []
        with su.io.cd(run_path):
            # compile the test
            for tname, tpath in test_paths.items():
                rr_comp = su.bash.run(f"javac -cp {classpath} {tpath}")
                if rr_comp.returncode == 0:
                    try:
                        class_name, method_name, desc = mut_key.split("#")
                        class_name = class_name.split("$")[0].replace(".", "/")
                        rr_run = su.bash.run(
                            "java "
                            + f'"-javaagent:{self._agent_path}={class_name},{method_name},{desc}"'
                            + f" -cp .:{self._agent_path}:{Tool.rt_jar}:{classpath}"
                            + f" -ea org.junit.runner.JUnitCore {tname}",
                            timeout=TIMEOUT,
                        )
                    except su.bash.subprocess.TimeoutExpired:
                        each_test_results.append(
                            {
                                "compiled": True,
                                "strerr": "Timeout",
                                "stdout": "Timeout",
                            }
                        )
                        continue

                    single_result = {
                        "compiled": True,
                        "stderr": rr_run.stderr,
                        "stdout": rr_run.stdout,
                    }
                    if os.path.isfile("output.txt"):
                        with open("output.txt") as coverage_file:
                            single_result["coverage"] = coverage_file.read()
                        su.io.rm("output.txt")
                    each_test_results.append(single_result)

                else:
                    each_test_results.append(
                        {
                            "compiled": False,
                            "stdout": rr_comp.stdout,
                            "stdout": rr_comp.stderr,
                        }
                    )

        self._write_in_chuncks(mut_context_gold, mut_file_path)
        return out, {
            "summary": out,
            "module_result": module_result,
            "each_test": each_test_results,
        }


if __name__ == "__main__":
    listener = setup_logging_queue()
    try:
        CLI(CoverageCollector, as_positional=False)
    finally:
        listener.stop()
