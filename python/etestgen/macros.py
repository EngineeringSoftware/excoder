from pathlib import Path
import os


class Macros:
    this_dir: Path = Path(os.path.dirname(os.path.realpath(__file__)))
    python_dir: Path = this_dir.parent
    log_file: Path = python_dir / "experiment.log"
    stack_trace_log_file: Path = python_dir / "stack.trace.experiment.log"
    debug_dir: Path = python_dir / "debug"
    project_dir: Path = python_dir.parent
    java_dir: Path = project_dir / "collector"

    # The curated subject repository lists.  These are checked-in inputs, not
    # pipeline scratch, which is why they live outside _work.
    repos_dir: Path = project_dir / "repos"

    work_dir: Path = project_dir / "_work"
    exp_dir: Path = work_dir / "exp"
    data_dir: Path = work_dir / "data"
    downloads_dir: Path = work_dir / "downloads"

    jar_dir: Path = project_dir / "jars"
    randoop_jar: str = jar_dir / "randoop-4.3.2" / "randoop-all-4.3.2.jar"
    evosuite_jar = jar_dir / "evosuite-1.2.0.jar"
    evosuitefit_jar = jar_dir / "evosuitefit-1.0.7.jar"
    junit_jar = jar_dir / "junit-platform-console-standalone-1.9.0-RC1.jar"

    SKIPS = "-Djacoco.skip -Dcheckstyle.skip -Drat.skip -Denforcer.skip -Danimal.sniffer.skip -Dmaven.javadoc.skip -Dfindbugs.skip -Dwarbucks.skip -Dmodernizer.skip -Dimpsort.skip -Dpmd.skip -Dxjc.skip -Dair.check.skip-all -Dfmt.skip -Dgpg.skip -Dlicense.skipAddThirdParty -Dlicense.skip"

    tool_time_limit: int = 600
