"""
Runtime evaluation metrics using tool-generated tests (Randoop / EvoSuite).

Each LLM-generated MUT implementation is compiled against the original project
and then validated by the Randoop / EvoSuite tests that were generated for that
MUT.  Results are saved under the prefix ``run-tools-``.
"""

import os
import shlex
from collections import defaultdict
from pathlib import Path
from typing import Any

import seutil as su
from etestgen.data.tool import Tool
from etestgen.macros import Macros as ExlongMacros
from etestgen.utils import summarize_topk_metrics
from jsonargparse import CLI
from seutil.maven import MavenModule
from throwgen.dataset.data import DataLLMOuput, ToolTest
from throwgen.eval.metrics.runtime_metrics import RuntimeMetrics, TIMEOUT
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.utils.multi_process_n_logging import setup_logging_queue
from tqdm import tqdm
from typing_extensions import override

logger = su.log.get_logger(__name__)


class ToolRuntimeMetrics(RuntimeMetrics):
    """
    Evaluate LLM-generated code against Randoop / EvoSuite tests that were
    collected for the corresponding MUT.
    """

    def __init__(
        self,
        llm_type: str,
        model_name: str,
        setup: str,
        dataset_name: str,
        prompt_gen_type: str,
        num_workers: int,
        max_tests_per_sample: int,
    ):
        # test_type is not used; pass a dummy value to satisfy the parent.
        super().__init__(
            llm_type,
            model_name,
            setup,
            dataset_name,
            prompt_gen_type,
            test_type="ebts",
            num_workers=num_workers,
        )
        self.max_tests_per_sample = max_tests_per_sample
        self._cache_by_sample: dict[str, list[dict[str, Any]]] = (
            self._load_each_sample_cache()
        )

    def _load_each_sample_cache(self) -> dict[str, list[dict[str, Any]]]:
        """
        Load any existing each-sample results so individual tests that were
        already evaluated can be reused instead of re-run. Returns:
            {data_id: [per_sample_dict, ...]}
        where per_sample_dict has keys ``module_result`` and ``each_test``
        (indexed by fqcn for lookup).
        """
        cache_path = (
            ThrowgenMacros.metrics_dir
            / self._dataset_name
            / f"{self._metrics_type}-{self._llm_type}-{self._model_name}-"
            f"{self._prompt_gen_type}-{self._setup}-each-sample.jsonl"
        )
        if not cache_path.exists():
            return {}
        try:
            raw: list[dict[str, Any]] = su.io.load(cache_path)  # type: ignore[assignment]
        except Exception as e:
            logger.warning(f"Could not load cache at {cache_path}: {e}")
            return {}
        cache: dict[str, list[dict[str, Any]]] = {}
        for entry in raw:
            data_id = entry.get("id")
            if not data_id:
                continue
            samples = entry.get("result", [])
            per_sample: list[dict[str, Any]] = []
            for sample in samples:
                by_fqcn = {
                    t["fqcn"]: t
                    for t in sample.get("each_test", [])
                    if "fqcn" in t
                }
                per_sample.append(
                    {
                        "module_result": sample.get("module_result"),
                        "by_fqcn": by_fqcn,
                    }
                )
            cache[data_id] = per_sample
        if cache:
            logger.info(
                f"Loaded tool-runtime cache from {cache_path.name}: "
                f"{len(cache)} data ids"
            )
        return cache

    @property
    @override
    def _metrics_type(self) -> str:
        return "run-tools"

    @override
    def _eval_sample_metrics(
        self,
        work_dir: Path,
        maven_module: MavenModule,
        llm_output: DataLLMOuput,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        data = self._id2data[llm_output.id]
        # Combined cap, Randoop counted first. EvoSuite generates far fewer
        # tests per target method than Randoop, so this ordering preserves
        # the richer Randoop signal when the cap is binding.
        tool_tests: list[ToolTest] = (
            data.randoop_tests + data.evosuite_tests
        )[: self.max_tests_per_sample]
        if not tool_tests:
            return {}, []

        run_path = work_dir / "run"
        su.io.mkdir(run_path, fresh=True)
        test_paths = self._prepare_tool_tests(run_path, tool_tests)
        if not test_paths:
            return {}, []

        # EvoSuite jar must come before dependency_classpath so its bundled
        # JUnit (4.11+) takes precedence over an older project JUnit (e.g.
        # 4.8.2) — otherwise EvoRunner fails with "Field nfr must implement
        # MethodRule" due to a MethodRule API incompatibility.
        classpath = os.pathsep.join(
            [
                maven_module.main_classpath,
                maven_module.test_classpath,
                str(ExlongMacros.evosuite_jar),
                maven_module.dependency_classpath,
            ]
        )

        sample_metrics: dict[str, list] = defaultdict(list)
        each_sample = []
        for sample_idx, code in enumerate(
            tqdm(
                llm_output.extract_code(),
                desc="Samples",
                disable=self._silence_low_level_tqdm,
            )
        ):
            runtime_metrics, each_test = self._eval_tool_code_metrics(
                run_path=run_path,
                test_paths=test_paths,
                maven_module=maven_module,
                classpath=classpath,
                code=code,
                data_id=llm_output.id,
                sample_idx=sample_idx,
            )
            each_sample.append(each_test)
            for k, v in runtime_metrics.items():
                sample_metrics[k].append(v)

        return summarize_topk_metrics(sample_metrics), each_sample

    # ------------------------------------------------------------------
    # Tool-test-specific helpers
    # ------------------------------------------------------------------

    def _prepare_tool_tests(
        self,
        run_path: Path,
        tool_tests: list[ToolTest],
    ) -> dict[str, Path]:
        """
        Copy tool test Java files (and sibling files for scaffolding) into
        *run_path*, preserving their package directory structure.

        Returns ``{fqcn: absolute_path_to_java_file}`` for each unique test
        class, skipping entries whose backing file does not exist on disk.
        """
        out: dict[str, Path] = {}
        seen_fqcn: set[str] = set()
        copied_test_roots: set[Path] = set()

        for tt in tool_tests:
            rel = Path(tt.rel_path)
            if len(rel.parts) < 2:
                continue
            src = ExlongMacros.exp_dir / rel
            if not src.exists():
                logger.warning(f"Tool test file not found: {src}")
                continue

            # The test root is project/<tool>-tests/
            test_root = ExlongMacros.exp_dir / rel.parts[0] / rel.parts[1]

            # Copy the entire test directory once (needed for scaffolding, etc.)
            if test_root not in copied_test_roots:
                copied_test_roots.add(test_root)
                if test_root.exists():
                    for java_file in test_root.rglob("*.java"):
                        within = java_file.relative_to(test_root)
                        dest = run_path / within
                        su.io.mkdir(dest.parent)
                        dest.write_text(
                            java_file.read_text(encoding="utf-8", errors="replace")
                        )

            try:
                fqcn = tt.fqcn
            except Exception:
                continue
            if fqcn in seen_fqcn:
                continue
            seen_fqcn.add(fqcn)

            # Path relative to the test root (e.g. "some/pkg/Foo.java")
            within_root = rel.relative_to(Path(rel.parts[0]) / rel.parts[1])
            out[fqcn] = run_path / within_root

        return out

    def _get_cached_sample(
        self, data_id: str, sample_idx: int
    ) -> dict[str, Any]:
        """Return cached per-sample entry (or empty dict if not cached)."""
        samples = self._cache_by_sample.get(data_id, [])
        if sample_idx < len(samples):
            return samples[sample_idx]
        return {}

    def _eval_tool_code_metrics(
        self,
        run_path: Path,
        test_paths: dict[str, Path],
        maven_module: MavenModule,
        classpath: str,
        code: str,
        data_id: str,
        sample_idx: int,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        """
        Substitute *code* for the MUT, compile the module, bulk-compile all
        tool test Java files in *run_path*, then run each test class.

        Per-test results that were already recorded in the previous
        each-sample.jsonl (matched by data_id, sample_idx, and fqcn) are
        reused instead of re-executed. If every test in *test_paths* has a
        cached result, module compilation and bulk javac are skipped
        entirely.
        """
        out = {"compiled": 0, "pass-ratio": 0.0, "all-pass": 0}

        cached_sample = self._get_cached_sample(data_id, sample_idx)
        cached_by_fqcn: dict[str, dict[str, Any]] = cached_sample.get("by_fqcn", {})
        cached_module_result: dict[str, Any] | None = cached_sample.get(
            "module_result"
        )

        cached_tests: list[dict[str, Any]] = []
        to_run_paths: dict[str, Path] = {}
        for tname, tpath in test_paths.items():
            if tname in cached_by_fqcn:
                cached_tests.append(cached_by_fqcn[tname])
            else:
                to_run_paths[tname] = tpath

        # Fast path: every test for this sample is already evaluated; skip
        # all compilation and execution.
        if not to_run_paths:
            pass_cnt = sum(1 for t in cached_tests if t.get("passed"))
            compiled_any = any(t.get("compiled") for t in cached_tests)
            module_ok = (
                cached_module_result.get("success")
                if cached_module_result
                else compiled_any
            )
            out["compiled"] = 1 if module_ok else 0
            if test_paths:
                out["pass-ratio"] = pass_cnt / len(test_paths)
                out["all-pass"] = int(pass_cnt == len(test_paths))
            logger.debug(
                f"[cache] {data_id}#sample{sample_idx}: "
                f"reused {len(cached_tests)} cached test result(s)"
            )
            return out, {
                "summary": out,
                "module_result": cached_module_result
                or {"success": bool(module_ok), "stdout": "", "stderr": ""},
                "each_test": cached_tests,
            }

        mut_key = self._id2data[data_id].mut_key
        mut_file_path = os.path.join(
            maven_module.main_srcpath,
            mut_key.split("#")[0].split("$")[0].replace(".", "/") + ".java",
        )
        with open(mut_file_path) as f:
            mut_context_lines = f.readlines()

        mut_context_gold = "".join(mut_context_lines)
        mut_context_up = "".join(
            mut_context_lines[: self._id2data[data_id].start_line - 1]
        )
        mut_context_down = "".join(
            mut_context_lines[self._id2data[data_id].end_line :]
        )
        self._write_in_chuncks(
            mut_context_up + code + mut_context_down, mut_file_path
        )

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
        new_test_results: list[dict[str, Any]] = []
        pass_cnt = sum(1 for t in cached_tests if t.get("passed"))

        with su.io.cd(run_path):
            # Bulk-compile all Java files together so scaffolding is available.
            # Use shlex.quote to handle filenames containing '$' (inner classes).
            all_java = [shlex.quote(str(p)) for p in run_path.rglob("*.java")]
            bulk_rr = su.bash.run(f"javac -cp {classpath} {' '.join(all_java)}")

            if bulk_rr.returncode != 0:
                for tname in to_run_paths:
                    new_test_results.append(
                        {
                            "fqcn": tname,
                            "compiled": False,
                            "passed": False,
                            "stdout": bulk_rr.stdout,
                            "stderr": bulk_rr.stderr,
                        }
                    )
            else:
                for tname in to_run_paths:
                    try:
                        rr_run = su.bash.run(
                            f"java -cp .:{Tool.rt_jar}:{classpath} "
                            f"-Djava.security.egd=file:/dev/./urandom "
                            f"-ea org.junit.runner.JUnitCore {tname}",
                            timeout=TIMEOUT,
                        )
                    except su.bash.subprocess.TimeoutExpired:
                        new_test_results.append(
                            {
                                "fqcn": tname,
                                "compiled": True,
                                "passed": False,
                                "stdout": "Timeout",
                                "stderr": "Timeout",
                            }
                        )
                        continue
                    if rr_run.returncode == 0:
                        pass_cnt += 1
                        new_test_results.append(
                            {
                                "fqcn": tname,
                                "compiled": True,
                                "passed": True,
                                "stdout": rr_run.stdout,
                                "stderr": rr_run.stderr,
                            }
                        )
                    else:
                        new_test_results.append(
                            {
                                "fqcn": tname,
                                "compiled": True,
                                "passed": False,
                                "stdout": rr_run.stdout,
                                "stderr": rr_run.stderr,
                            }
                        )

        # Preserve input order: walk test_paths and pull cached or new in turn.
        merged: list[dict[str, Any]] = []
        new_by_fqcn = {t["fqcn"]: t for t in new_test_results}
        for tname in test_paths:
            if tname in cached_by_fqcn:
                merged.append(cached_by_fqcn[tname])
            elif tname in new_by_fqcn:
                merged.append(new_by_fqcn[tname])

        if cached_tests:
            logger.debug(
                f"[cache] {data_id}#sample{sample_idx}: "
                f"reused {len(cached_tests)}, ran {len(new_test_results)}"
            )

        if test_paths:
            out["pass-ratio"] = pass_cnt / len(test_paths)
            out["all-pass"] = int(pass_cnt == len(test_paths))

        self._write_in_chuncks(mut_context_gold, mut_file_path)
        return out, {
            "summary": out,
            "module_result": module_result,
            "each_test": merged,
        }


if __name__ == "__main__":
    listener = setup_logging_queue()
    try:
        CLI(ToolRuntimeMetrics, as_positional=False)
    finally:
        listener.stop()
