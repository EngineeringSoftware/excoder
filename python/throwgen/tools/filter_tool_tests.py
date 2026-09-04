"""
Filter tool tests in a throwgen dataset, keeping only test classes that pass
when run against the gold MUT implementation (dummy eval results).

Reads:
  <metrics_dir>/<dataset>/run-tools-dummy-dummy-mut-dummy-each-sample.jsonl

Updates in-place:
  <data_dir>/<dataset>/randoop_tests.jsonl
  <data_dir>/<dataset>/evosuite_tests.jsonl

Run after the sanity-check step in generate_tool_tests.sh.
"""

import json
import logging
from pathlib import Path

import seutil as su
from jsonargparse import CLI
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__)


def filter_tool_tests(dataset_name: str) -> None:
    data_dir = ThrowgenMacros.mebt_data_dir / dataset_name
    metrics_dir = ThrowgenMacros.metrics_dir / dataset_name
    results_file = (
        metrics_dir / "run-tools-dummy-dummy-mut-dummy-each-sample.jsonl"
    )

    if not results_file.exists():
        raise FileNotFoundError(
            f"Dummy eval results not found: {results_file}\n"
            "Run the sanity-check step first."
        )

    # Build map: id -> set of FQCNs that were tested AND failed on gold.
    # Only explicitly-failing FQCNs are removed: if a test class was never run
    # (e.g. because of the per-sample cap in tool_runtime_metrics), keep it.
    failing: dict[str, set[str]] = {}
    for line in results_file.open():
        r = json.loads(line)
        rid = r["id"]
        each_test = r["result"][0]["each_test"]
        failing[rid] = {
            t["fqcn"] for t in each_test if not t.get("passed") and "fqcn" in t
        }

    # Load dataset IDs (one per line, JSON-encoded strings).
    ids = [json.loads(l) for l in (data_dir / "id.jsonl").open()]

    total_kept = 0
    total_removed = 0

    for field in ("randoop_tests", "evosuite_tests"):
        tests_file = data_dir / f"{field}.jsonl"
        lines = tests_file.read_text().splitlines(keepends=True)
        assert len(lines) == len(ids), (
            f"Line count mismatch in {tests_file}: {len(lines)} vs {len(ids)} IDs"
        )

        kept = removed = 0
        new_lines = []
        for rid, line in zip(ids, lines):
            tests = json.loads(line)
            bad_fqcns = failing.get(rid, set())
            if not bad_fqcns:
                new_lines.append(line)
                kept += len(tests)
                continue

            filtered = [
                t for t in tests
                if t.get("etest_method", "").split("#")[0] not in bad_fqcns
            ]
            removed += len(tests) - len(filtered)
            kept += len(filtered)
            new_lines.append(json.dumps(filtered) + "\n")

        tests_file.write_text("".join(new_lines))
        logger.info(f"{field}: kept {kept}, removed {removed}")
        total_kept += kept
        total_removed += removed

    logger.info(
        f"Total: kept {total_kept} test entries, removed {total_removed}"
    )


if __name__ == "__main__":
    from throwgen.utils.multi_process_n_logging import setup_logging_queue
    listener = setup_logging_queue()
    try:
        CLI(filter_tool_tests, as_positional=False)
    finally:
        listener.stop()
