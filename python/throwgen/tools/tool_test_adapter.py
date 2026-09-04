"""
Adapter that bridges the throwgen DataMultiEBT dataset with the etestgen
tool test generation pipeline (Randoop / EvoSuite).

The etestgen pipeline (GenerateTests) is tied to its own repo/class lists
loaded from hardcoded paths.  This adapter:
  1. Reads a throwgen dataset to discover which projects and classes are
     needed.
  2. Writes per-project evosuite-classes.txt files that limit EvoSuite to
     the classes actually present in the dataset (GenerateTests.get_classes
     checks for this file first before falling back to the global list).
  3. Drives generate → collect → parse project-by-project using the
     lower-level GenerateTests methods, bypassing load_test_projects().
  4. Writes the parsed exception JSON to the paths that RandoopTestExtractor
     and EvosuiteTestExtractor expect.

Usage (CLI):
    python -m throwgen.tools.tool_test_adapter \
        --dataset_name=<name> \
        --tool=all          # randoop | evosuite | all
"""

import glob
from collections import defaultdict
from pathlib import Path
import seutil as su
from etestgen.data.utils import load_dataset
from etestgen.macros import Macros as ExlongMacros
from etestgen.tools.program_analysis_based import GenerateTests
from jsonargparse import CLI
from throwgen.dataset.data import DataMultiEBT
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__)


class ThrowgenToolAdapter:
    # Paths consumed by the throwgen extractors
    RANDOOP_OUT = ExlongMacros.exp_dir / "tool-results" / "randoop-exceptions.json"
    EVOSUITE_OUT = ExlongMacros.exp_dir / "tool-results" / "evosuite-exceptions.json"

    def __init__(self, dataset_name: str):
        self.dataset_name = dataset_name
        self._gt = GenerateTests()

        # Load the throwgen dataset
        dataset_path = ThrowgenMacros.mebt_data_dir / dataset_name
        raw_dataset = load_dataset(dataset_path, clz=DataMultiEBT)

        # Build project → {class_name, ...} and project → sha mappings
        self._project_classes: dict[str, set[str]] = defaultdict(set)
        for d in raw_dataset:  # type: ignore[union-attr]
            cls = d.mut_key.split("#")[0]  # type: ignore[union-attr]
            self._project_classes[d.project].add(cls)  # type: ignore[union-attr]

        self._project_sha: dict[str, str] = self._load_project_shas()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def generate_and_extract(self, tool: str = "all"):
        """Full pipeline: generate tests, collect & parse exceptions, write output."""
        tools = ["randoop", "evosuite"] if tool == "all" else [tool]

        self._gt.download_jars()
        self._write_evosuite_class_lists()

        for t in tools:
            self._run_tool_pipeline(t)

        for t in tools:
            self._parse_and_save(t)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_project_shas(self) -> dict[str, str]:
        """Build project_name → sha from the global filtered repos.json."""
        repos_file = ExlongMacros.repos_dir / "filtered" / "repos.json"
        if not repos_file.exists():
            logger.warning(f"Repos file not found: {repos_file}; SHAs will be missing.")
            return {}
        repos: list[dict] = su.io.load(repos_file)  # type: ignore[assignment]
        return {r["full_name"]: r["sha"] for r in repos}

    def _write_evosuite_class_lists(self):
        """
        Write evosuite-classes.txt for each project so GenerateTests.get_classes()
        returns only the classes present in the throwgen dataset instead of the
        global rq2-public-target-classes list.
        """
        for project, classes in self._project_classes.items():
            out_path: Path = ExlongMacros.exp_dir / project / "evosuite-classes.txt"
            su.io.mkdir(out_path.parent)
            su.io.dump(out_path, sorted(classes), su.io.Fmt.txtList)
            logger.info(f"Wrote {len(classes)} classes for {project} → {out_path}")

    def _has_generated_tests(self, tool: str, project: str) -> bool:
        """Return True if *.java test files already exist for this project."""
        generated_tests_dir = ExlongMacros.exp_dir / project / f"{tool}-tests"
        if not generated_tests_dir.exists():
            return False
        return bool(list(generated_tests_dir.rglob("*.java")))

    def _run_tool_pipeline(self, tool: str):
        """Generate tests and collect exceptions for all throwgen projects."""
        log_dir = ExlongMacros.debug_dir / tool
        su.io.mkdir(log_dir)

        for project in self._project_classes:
            sha = self._project_sha.get(project)
            if sha is None:
                logger.warning(f"No SHA found for {project}; skipping.")
                continue

            generated_tests_dir = ExlongMacros.exp_dir / project / f"{tool}-tests"
            if self._has_generated_tests(tool, project):
                logger.info(f"[{tool}] Tests already exist for {project}; skipping generation.")
            else:
                try:
                    deps_file = str(ExlongMacros.exp_dir / project / f"{tool}-deps.txt")
                    classpath_list_file = str(ExlongMacros.exp_dir / project / "classpath-list.txt")
                    su.io.mkdir(ExlongMacros.exp_dir / project)

                    logger.info(f"[{tool}] Preparing {project} @ {sha}")
                    p = self._gt.prepare_project(project, sha)
                    self._gt.dump_dependencies(project, p, deps_file, classpath_list_file)

                    # For randoop, restrict to only the classes present in the dataset
                    if tool == "randoop":
                        dataset_classes = sorted(self._project_classes[project])
                        randoop_classes_file = str(ExlongMacros.exp_dir / project / "randoop-classes.txt")
                        su.io.dump(randoop_classes_file, dataset_classes, su.io.Fmt.txtList)
                        logger.info(f"[randoop] Using {len(dataset_classes)} dataset classes for {project}")
                        classpath_list_file = randoop_classes_file

                    self._gt.generate_tests_with_one_seed(
                        project, tool, str(generated_tests_dir), str(log_dir), 42, deps_file, classpath_list_file
                    )
                except Exception as e:
                    logger.warning(f"[{tool}] Test generation failed for {project}: {e}")
                    continue

            # Collect exceptions
            exceptions_log = ExlongMacros.exp_dir / project / f"{tool}-exceptions.log"
            if exceptions_log.exists():
                su.bash.run(f"rm {exceptions_log}")

            if not generated_tests_dir.exists():
                logger.warning(f"[{tool}] No tests generated for {project}; skipping collection.")
                continue

            logger.info(f"[{tool}] Collecting exceptions for {project}")
            try:
                sha = self._project_sha.get(project, "")
                p = self._gt.prepare_project(project, sha)
                su.bash.run(f"chmod -R 777 {ExlongMacros.downloads_dir / project}")
                su.bash.run(
                    f"cp -r {generated_tests_dir} {ExlongMacros.downloads_dir / project}"
                )

                # Compile/install the analysis module so org.analysis.App is on the classpath
                analysis_dir = ExlongMacros.java_dir / "analysis"
                with su.io.cd(analysis_dir):
                    su.bash.run("mvn install -DskipTests", 0)

                for file_path in glob.glob(
                    f"{ExlongMacros.downloads_dir}/{project}/{tool}-tests/**/*.java",
                    recursive=True,
                ):
                    if file_path.endswith("scaffolding.java"):
                        continue
                    fp = file_path.replace("$", "\\$")
                    with su.io.cd(analysis_dir):
                        su.bash.run(
                            f'mvn exec:java -Dexec.mainClass="org.analysis.App" '
                            f'-Dexec.args="collect-exception {fp} {fp} {exceptions_log}"',
                            0,
                        )

                deps_file = ExlongMacros.exp_dir / project / f"{tool}-deps.txt"
                run_log = ExlongMacros.exp_dir / project / f"{tool}-tests.log"
                self._gt.execute_tests(tool, project, None, str(run_log), str(deps_file))  # type: ignore[arg-type]
            except Exception as e:
                logger.warning(f"[{tool}] Exception collection failed for {project}: {e}")

    def _find_test_file(self, project: str, tool: str, class_name: str) -> str:
        """
        Find the Java file for *class_name* inside the tool test directory.
        Returns the path relative to ExlongMacros.exp_dir, or "" if not found.
        """
        test_dir = ExlongMacros.exp_dir / project / f"{tool}-tests"
        if not test_dir.exists():
            return ""
        matches = [
            p for p in test_dir.rglob(f"{class_name}.java")
            if not p.name.endswith("scaffolding.java")
        ]
        if not matches:
            return ""
        return str(matches[0].relative_to(ExlongMacros.exp_dir))

    def _parse_and_save(self, tool: str):
        """
        Parse exception logs for all throwgen projects and write to the path
        that the throwgen extractor reads from.

        Each entry includes:
          project, etest_method, exception, mut_key, stack_trace, rel_path
        where rel_path is the test Java file's path relative to exp_dir (empty
        string when the file cannot be located on disk).
        """
        res_list = []
        for project in self._project_classes:
            exceptions_log = ExlongMacros.exp_dir / project / f"{tool}-exceptions.log"
            if not exceptions_log.exists():
                continue
            exceptions: list[str] = su.io.load(exceptions_log, su.io.Fmt.txtList)  # type: ignore[assignment]
            for exception in exceptions:  # type: ignore[union-attr]
                lines = exception.split("##")
                if len(lines) < 2:
                    continue
                tokens = lines[0].split("#")
                if len(tokens) != 3:
                    continue
                # lines[1] is the first stack frame (class#method#line).
                # Skip entries where the stack trace is empty (e.g. all frames
                # were org.junit frames and were filtered out), because we can't
                # determine the MUT without at least class#method.
                mut_key = lines[1].strip()
                if len(mut_key.split("#")) < 2:
                    continue
                # tokens[0] may be a fully-qualified name (e.g. "com.pkg.Foo_ESTest");
                # the file on disk is just "Foo_ESTest.java" so use the simple name.
                class_name = tokens[0].split(".")[-1]
                rel_path = self._find_test_file(project, tool, class_name)
                if not rel_path:
                    logger.debug(
                        f"[{tool}] Test file not found for {class_name} in {project}"
                    )
                res_list.append({
                    "project": project,
                    "etest_method": "#".join(tokens[:2]),
                    "exception": tokens[2],
                    "mut_key": mut_key,
                    "stack_trace": "\n".join(lines[1:]),
                    "rel_path": rel_path,
                })

        out_path = self.RANDOOP_OUT if tool == "randoop" else self.EVOSUITE_OUT
        su.io.mkdir(out_path.parent)
        su.io.dump(out_path, res_list, su.io.Fmt.jsonPretty)
        logger.info(f"[{tool}] Wrote {len(res_list)} exceptions → {out_path}")


def generate_and_extract(dataset_name: str, tool: str = "all"):
    """
    Run the full tool test pipeline for a throwgen dataset and write
    the parsed exception JSON files for use by the throwgen extractors.

    :param dataset_name: Name of the throwgen dataset.
    :param tool: Tool(s) to run: randoop | evosuite | all.
    """
    su.log.setup(ExlongMacros.log_file, su.log.INFO)
    adapter = ThrowgenToolAdapter(dataset_name)
    adapter.generate_and_extract(tool)


def parse_only(dataset_name: str, tool: str = "all"):
    """
    Re-parse existing per-project exception logs and rewrite the exceptions
    JSON files consumed by the throwgen extractors.  Skips test generation
    and collection — useful when the output JSON is corrupt/truncated but the
    per-project *.log files are intact.

    :param dataset_name: Name of the throwgen dataset.
    :param tool: Tool(s) to parse: randoop | evosuite | all.
    """
    su.log.setup(ExlongMacros.log_file, su.log.INFO)
    adapter = ThrowgenToolAdapter(dataset_name)
    tools = ["randoop", "evosuite"] if tool == "all" else [tool]
    for t in tools:
        adapter._parse_and_save(t)


if __name__ == "__main__":
    CLI([generate_and_extract, parse_only], as_positional=False)
