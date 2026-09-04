from functools import lru_cache

import seutil as su
from etestgen.macros import Macros
from seutil.project import Project

REPOS_DIR = Macros.repos_dir / "filtered"

#: The repositories the experiments run on.
EVAL_REPOS_FILE = REPOS_DIR / "repos.json"

#: The repositories the validation set is mined from.  A project may appear in
#: both files, occasionally pinned to a different commit in each.
VAL_REPOS_FILE = REPOS_DIR / "repos_val.json"


@lru_cache(maxsize=1)
def load_all_projects() -> list[Project]:
    """Every subject repository, from whichever list it appears in.

    The validation funnel runs the same filters and extractors as the
    evaluation funnel, so anything that resolves a project by name has to see
    both lists or it will silently drop the validation rows.  Where a project
    is in both, the evaluation pin wins -- that is the checkout the extractors
    have already been run against.
    """
    projects: list[Project] = su.io.load(EVAL_REPOS_FILE, clz=list[Project])  # type: ignore
    seen = {proj.full_name for proj in projects}
    if VAL_REPOS_FILE.exists():
        val: list[Project] = su.io.load(VAL_REPOS_FILE, clz=list[Project])  # type: ignore
        projects += [proj for proj in val if proj.full_name not in seen]
    return projects
