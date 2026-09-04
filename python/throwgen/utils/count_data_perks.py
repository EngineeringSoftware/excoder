import json
import re
from collections import defaultdict
from jsonargparse import CLI
import seutil as su
from throwgen.macros import Macros as ThrowgenMacros


def count_throw(dataset_name: str):
    with open(
        ThrowgenMacros.mebt_data_dir / dataset_name / "throw-rm-output.jsonl",
    ) as tro_file:
        count = defaultdict(lambda: 0)
        for line in tro_file:
            output = json.loads(line)["out"]
            throw_types = set(re.findall(r"!\[(\w+-throw)\]!", output))
            for tt in throw_types:
                count[tt] += 1

    total = 0
    for _, v in count.items():
        total += v
    count["total-throw"] = total
    su.io.dump(
        ThrowgenMacros.mebt_data_dir / dataset_name / "throw-count.json",
        count,
        fmt=su.io.fmts.jsonPretty,
    )

def count_no_throw_error(dataset_name: str):
    with open(
        ThrowgenMacros.mebt_data_dir / dataset_name / "removed-compile-fail-samples.jsonl",
    ) as tro_file:
        count = defaultdict(lambda: 0)
        unreported = 0
        for line in tro_file:
            data = json.loads(line)
            failure = data['failure'].replace(" ", "-")
            count[failure] += 1
            if "unreported exception" in data.get("error_message", ""):
                unreported += 1

    total = 0
    for _, v in count.items():
        total += v
    count["total-rm-comp-fail"] = total
    # A method can fail to compile with more than one error, so we count the
    # data points reporting an unreported exception separately (after the
    # total) to avoid double counting them.
    count["unreported-exception"] = unreported
    # The "incompatible types" failures share their root cause with the
    # "missing return" ones (the removal left a branch without a return
    # statement), so we report them together as the data points that fail to
    # compile for that reason alone.
    count["missing-return-only"] = total - unreported
    su.io.dump(
        ThrowgenMacros.mebt_data_dir / dataset_name / "removed-compile-fail.json",
        count,
        fmt=su.io.fmts.jsonPretty,
    )


if __name__ == "__main__":
    CLI([count_throw, count_no_throw_error], as_positional=False)
