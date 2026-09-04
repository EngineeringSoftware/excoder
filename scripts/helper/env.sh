#!/usr/bin/env bash
# Repository layout and Python environment.  Every pipeline sources this, so
# none of them depend on direnv or on the caller's working directory.

_env_sh_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export REPO_DIR="$(cd "${_env_sh_dir}/../.." && pwd)"
export SCRIPT_DIR="${REPO_DIR}/scripts"
export THROWGEN_SCRIPT_DIR="${SCRIPT_DIR}"
export PYTHON_DIR="${REPO_DIR}/python"
export WORK_DIR="${REPO_DIR}/_work"
export REPOS_DIR="${REPO_DIR}/repos"
export PAPER_DIR="${REPO_DIR}/papers"
export PYTHONPATH="${PYTHON_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

unset _env_sh_dir

# ---------------------------------------------------------------------------
# Mock mode: with THROWGEN_MOCK=1 (set by --mock) the pipelines print what they
# would run instead of running it.
# ---------------------------------------------------------------------------
: "${THROWGEN_MOCK:=0}"
export THROWGEN_MOCK

# run <cmd...> -- execute, or echo when mocking.
run() {
    if [[ "$THROWGEN_MOCK" == "1" ]]; then
        echo "[mock] $*"
        return 0
    fi
    "$@"
}

# expect_dataset <name>... -- in mock mode, assert the dataset is present.
expect_dataset() {
    local ok=0 name
    for name in "$@"; do
        if [[ -d "${WORK_DIR}/data/throwgen/${name}" ]]; then
            echo "[mock]   ✓ dataset present: ${name}"
        else
            echo "[mock]   ✗ dataset MISSING: ${name}" >&2
            ok=1
        fi
    done
    return $ok
}
