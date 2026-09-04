from collections.abc import Callable
from typing import Any

import numpy as np
import seutil as su
from etestgen.eval.compute_test_coverage import TestMethod
from etestgen.macros import Macros
from jsonargparse import CLI
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.multi_ebt_data import MultiEBTDataset
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.utils.code import body_statements, is_only_throw
from tqdm import tqdm

logger = su.log.get_logger(__name__, su.log.INFO)

# Must match _MAX_TOOL_TESTS in scripts/throwgen/piplines/run_experiment_pipeline.sh
# so the reported stats reflect exactly what the runtime-eval saw.
# Combined cap over (randoop + evosuite); Randoop is counted first.
TOOL_TEST_CAP_PER_SAMPLE = 400


class BaseStatsCollector:
    def __init__(self, name: str):
        self._name = name

    def process_one_data(self, data: DataMultiEBT):
        raise NotImplementedError("process_one_data not implemented")

    def get_final_metrics(self) -> dict[str, float]:
        raise NotImplementedError("get_final_metrics not implemented")


class CounterCollector(BaseStatsCollector):
    def __init__(
        self,
        name: str,
        target_field: str,
        field_trans: Callable[[Any], str | list[str]] | None = None,
    ):
        super().__init__(name)

        logger.info(f"Added {name} counter collector on {target_field}")
        self._target_field = target_field
        self._field_trans = field_trans
        self._count_set = set()

    def process_one_data(self, data: DataMultiEBT):
        cnt_item = getattr(data, self._target_field)
        if self._field_trans is not None:
            trans_item = self._field_trans(cnt_item)
            if isinstance(trans_item, list):
                for i in trans_item:
                    self._count_set.add(i)
            else:
                self._count_set.add(trans_item)
        else:
            self._count_set.add(cnt_item)

    def get_final_metrics(self) -> dict[str, float]:
        return {f"{self._name}": len(self._count_set)}


class PredicateCountCollector(BaseStatsCollector):
    """Counts the data points satisfying a predicate.

    Unlike CounterCollector this counts occurrences rather than distinct
    values, and unlike PerDataCollector it sees the whole data point.
    """

    def __init__(self, name: str, predicate: Callable[[DataMultiEBT], bool]):
        super().__init__(name)

        logger.info(f"Added {name} predicate count collector")
        self._predicate = predicate
        self._count = 0

    def process_one_data(self, data: DataMultiEBT):
        if self._predicate(data):
            self._count += 1

    def get_final_metrics(self) -> dict[str, float]:
        return {self._name: self._count}


class PerDataCollector(BaseStatsCollector):
    def __init__(
        self,
        name: str,
        target_field: str,
        field_trans: Callable[[Any], float],
        aggregators: dict[str, Callable[[list[float]], Any]],
    ):
        super().__init__(name)

        logger.info(f"Added {name} per data collector on {target_field}")
        self._target_field = target_field
        self._field_trans = field_trans
        self._raw_stats = []
        self._aggregators = aggregators

    def process_one_data(self, data: DataMultiEBT):
        self._raw_stats.append(self._field_trans(getattr(data, self._target_field)))

    def get_final_metrics(self) -> dict[str, float]:
        out_dict = {}
        for a_name, agg in self._aggregators.items():
            out_dict[f"{self._name}-{a_name}"] = agg(self._raw_stats)

        return out_dict


class CollectDataStats:
    def __init__(
        self,
        dataset_name: str,
        collectors: list[BaseStatsCollector],
    ):
        self._dataset_path = ThrowgenMacros.mebt_data_dir / dataset_name
        self._dataset = MultiEBTDataset.from_saved(
            ThrowgenMacros.mebt_data_dir / dataset_name
        )
        self._collectors = collectors

    def _collect_stats(self) -> dict[str, float]:
        for data in tqdm(self._dataset, desc="Collecting stats"):
            for collector in self._collectors:
                collector.process_one_data(data)

        out_stat = {}
        for collector in self._collectors:
            out_stat.update(collector.get_final_metrics())
        return out_stat

    def generate_stats(self):
        stats = self._collect_stats()
        su.io.dump(
            self._dataset_path / "dataset_stats.json",
            stats,
            su.io.Fmt.jsonPretty,
        )


def get_fun_var_info_len(class_info: dict[str, list[str]]) -> float:
    total = 0
    for _, v in class_info.items():
        total += len(v)
    return total


def get_exception_type(ebts: list[TestMethod]) -> list[str]:
    return [ebt.exception for ebt in ebts if ebt.exception is not None]


def non_zero_avg_agg(x: list[float]) -> np.floating:
    return np.mean([i for i in x if i > 0])


def larger_than_20_agg(x: list[float]) -> float:
    return len([i for i in x if i > 20]) * 100 / len(x)


def is_only_throw_mut(data: DataMultiEBT) -> bool:
    """Whether the MUT body is a single throw statement and nothing else."""
    try:
        return is_only_throw(data.mut)
    except ValueError:
        logger.warning(f"Could not parse mut of {data.id}, not counting as only-throw")
        return False


def has_empty_no_throw(data: DataMultiEBT) -> bool:
    """Whether removing the exception-raising code leaves an empty body.

    A superset of is_only_throw_mut: methods that are nothing but throwing
    guard clauses also empty out.
    """
    try:
        stmts = body_statements(data.mut_no_throw)
    except ValueError:
        logger.warning(f"Could not parse mut_no_throw of {data.id}, not counting")
        return False
    return stmts is not None and len(stmts) == 0


def generate_dataset_stats(dataset_name: str):
    """
    main entry point to generate dataset stats
    """

    # all counter collectors
    class_collector = CounterCollector(
        name="num-class",
        target_field="mut_key",
        field_trans=lambda s: s.split("#")[0],
    )
    method_collector = CounterCollector(
        name="num-methods",
        target_field="mut_key",
    )
    exception_type_collector = CounterCollector(
        name="exception-type",
        target_field="ebts",
        field_trans=get_exception_type,
    )
    project_collector = CounterCollector(name="num-projects", target_field="project")

    only_throw_collector = PredicateCountCollector(
        name="only-throw-mut", predicate=is_only_throw_mut
    )
    empty_no_throw_collector = PredicateCountCollector(
        name="empty-no-throw", predicate=has_empty_no_throw
    )

    # some aggregators
    avg_agg = np.mean
    sum_agg = np.sum

    def percentile_agg(x: list[float]):
        return {p * 25: np.percentile(x, p * 25) for p in range(5)}

    # all per data collectors
    throw_collector = PerDataCollector(
        name="throw-statements",
        target_field="mut",
        field_trans=lambda x: x.count("throw "),
        aggregators={
            "avg": avg_agg,
            "sum": sum_agg,
            "percentile": percentile_agg,
        },
    )
    lines_collector = PerDataCollector(
        name="method-lines",
        target_field="mut",
        field_trans=lambda x: len(x.split("\n")),
        aggregators={
            "avg": avg_agg,
            "percentile": percentile_agg,
            "larger-than-20": larger_than_20_agg,
        },
    )
    etest_collector = PerDataCollector(
        name="etest",
        target_field="ebts",
        field_trans=len,
        aggregators={
            "avg": avg_agg,
            "percentile": percentile_agg,
            "sum": sum_agg,
        },
    )

    class_info_collector = PerDataCollector(
        name="class-info",
        target_field="class_info",
        field_trans=get_fun_var_info_len,
        aggregators={
            "non-zero-avg": non_zero_avg_agg,
            "avg": avg_agg,
        },
    )

    method_info_collector = PerDataCollector(
        name="method-info",
        target_field="method_info",
        field_trans=lambda x: sum([get_fun_var_info_len(v) for v in x["type_list"]]),
        aggregators={"non-zero-avg": non_zero_avg_agg, "avg": avg_agg},
    )

    # Report Randoop/EvoSuite counts under the same cap that runtime-eval uses:
    # tool_runtime_metrics takes the first TOOL_TEST_CAP_PER_SAMPLE entries of
    # (randoop_tests + evosuite_tests), so Randoop is counted first and
    # EvoSuite fills the remaining budget.
    def capped_randoop_count(data: DataMultiEBT) -> float:
        return min(len(data.randoop_tests), TOOL_TEST_CAP_PER_SAMPLE)

    def capped_evosuite_count(data: DataMultiEBT) -> float:
        remaining = TOOL_TEST_CAP_PER_SAMPLE - min(
            len(data.randoop_tests), TOOL_TEST_CAP_PER_SAMPLE
        )
        return min(len(data.evosuite_tests), remaining)

    randoop_collector = PerDataCollector(
        name="randoop-tests",
        target_field="randoop_tests",
        field_trans=lambda _: 0.0,  # overridden below
        aggregators={
            "avg": avg_agg,
            "sum": sum_agg,
            "percentile": percentile_agg,
        },
    )
    evosuite_collector = PerDataCollector(
        name="evosuite-tests",
        target_field="evosuite_tests",
        field_trans=lambda _: 0.0,  # overridden below
        aggregators={
            "avg": avg_agg,
            "sum": sum_agg,
            "percentile": percentile_agg,
        },
    )
    randoop_collector.process_one_data = (  # type: ignore[method-assign]
        lambda data: randoop_collector._raw_stats.append(capped_randoop_count(data))
    )
    evosuite_collector.process_one_data = (  # type: ignore[method-assign]
        lambda data: evosuite_collector._raw_stats.append(capped_evosuite_count(data))
    )

    # Combined total under the single cap, emitted as a macro.
    tool_tests_combined_collector = PerDataCollector(
        name="tool-tests",
        target_field="randoop_tests",  # overridden below
        field_trans=lambda _: 0.0,
        aggregators={"sum": sum_agg, "avg": avg_agg},
    )
    tool_tests_combined_collector.process_one_data = (  # type: ignore[method-assign]
        lambda data: tool_tests_combined_collector._raw_stats.append(
            capped_randoop_count(data) + capped_evosuite_count(data)
        )
    )

    # not finally collect data
    cds = CollectDataStats(
        dataset_name=dataset_name,
        collectors=[
            class_collector,
            method_collector,
            project_collector,
            throw_collector,
            lines_collector,
            etest_collector,
            exception_type_collector,
            only_throw_collector,
            empty_no_throw_collector,
            randoop_collector,
            evosuite_collector,
            tool_tests_combined_collector,
            # class_info_collector,
            # method_info_collector,
        ],
    )
    cds.generate_stats()


if __name__ == "__main__":
    su.log.setup(Macros.log_file)
    CLI(generate_dataset_stats, as_positional=False)
