import os
from pathlib import Path

from etestgen.macros import Macros as ExlongMacros


class Macros:
    throwgen_dir: Path = Path(os.path.dirname(os.path.realpath(__file__)))
    llm_output_dir: Path = ExlongMacros.work_dir / "results" / "llm_output"
    metrics_dir: Path = ExlongMacros.work_dir / "results" / "metrics"
    maven_out_dir: Path = ExlongMacros.work_dir / "results" / "maven_out"
    paper_dir: Path = ExlongMacros.project_dir / "papers"
    java_src_dir: Path = ExlongMacros.project_dir / "throwgen-datacollection"
    mebt_data_dir: Path = ExlongMacros.data_dir / "throwgen"
    ne2e_data_dir: Path = ExlongMacros.data_dir / "etestgen"
    # The hand-made annotation stores the qualitative analysis reads.  Nothing
    # regenerates these, which is why they live in the repository rather than
    # under _work.
    annotations_dir: Path = ExlongMacros.project_dir / "annotations"
    # Scratch output of the two viewers (rendered prompts and datasets).  Not
    # part of any pipeline, so it stays out of the repository.
    viewer_dir: Path = ExlongMacros.work_dir / "results" / "viewer"
    model_dir: Path = ExlongMacros.work_dir / "models"
