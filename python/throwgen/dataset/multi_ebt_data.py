from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import seutil as su
import tqdm
from etestgen.data.data import DataNE2E
from etestgen.data.utils import load_dataset, save_dataset
from etestgen.macros import Macros
from jsonargparse import CLI
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors import NAME2EXTRACTORS
from throwgen.dataset.filters import NAME2FILTERS
from throwgen.macros import Macros as ThrowgenMacros

logger = su.log.get_logger(__name__, su.log.INFO)


class MultiEBTDataset(Iterator[DataMultiEBT]):
    def __init__(
        self,
        dataset_path: Path,
        dataset: dict[str, DataMultiEBT],
        selected_ids: list[str] | None = None,
    ):
        self._dataset_name = dataset_path.stem
        self._dataset = dataset
        if selected_ids is None:
            self._selected_ids = list(self._dataset)
        else:
            self._selected_ids = selected_ids
        self._id_iter = iter(self._selected_ids)

    @classmethod
    def from_ne2e_dataset(
        cls,
        dataset_path: Path,
        direct_throw: bool,
    ) -> "MultiEBTDataset":
        # load ne2e dataset
        ne2e_dataset = load_dataset(dataset_path, clz=DataNE2E)
        mut_key_to_ne2e: dict[str, list[DataNE2E]] = defaultdict(list)
        for data in tqdm.tqdm(ne2e_dataset, desc="Sorting throw statements"):
            mut_key_to_ne2e[data.mut_key].append(data)

        # filter out non-direct ebts
        dmebt_list: list[DataMultiEBT] = []
        for _, ne2e_list in mut_key_to_ne2e.items():
            add_to_data = True
            for ne2e_data in ne2e_list:
                if direct_throw and len(ne2e_data.e_stack_trace) > 1:
                    add_to_data = False
            if add_to_data:
                dmebt_list.append(DataMultiEBT.from_ne2e_list(ne2e_list))
        out_dataset = MultiEBTDataset(dataset_path, {d.id: d for d in dmebt_list})

        return out_dataset

    @classmethod
    def from_saved(
        cls, dataset_path: Path, selected_ids: list[str] | None = None
    ) -> "MultiEBTDataset":
        dmebt_list = load_dataset(dataset_path, clz=DataMultiEBT)
        return MultiEBTDataset(
            dataset_path, {d.id: d for d in dmebt_list}, selected_ids
        )

    def filter_dataset(self, selected_filter_names: list[str]):
        meta_data = {"dataset_name": self._dataset_name}
        filters = [
            v(meta_data) for k, v in NAME2FILTERS.items() if k in selected_filter_names
        ]
        new_selected_ids: list[str] = []
        for data in tqdm.tqdm(self, desc="Filter dataset"):
            toss_data_list: list[bool] = [f.toss_data(data) for f in filters]
            if not any(toss_data_list):
                new_selected_ids.append(data.id)
        self._selected_ids = new_selected_ids

    def extend_partial_dataset(
        self,
        selected_extractor_names: list[str] | None = None,
        setup_extractor: bool = False,
    ):
        """
        add all necessary data to a partial dataset using the selected extractors
        if no selected extractor names are given then run all extractors
        """
        selected_projs: set[str] = set()
        for data in self:
            selected_projs.add(data.project)
        if selected_extractor_names is None:
            selected_extractor_names = []
        meta_data = {"dataset_name": self._dataset_name}
        extractors = [
            v(self, meta_data)
            for k, v in NAME2EXTRACTORS.items()
            if k in selected_extractor_names
        ]
        logger.info(f"Using extractors: {selected_extractor_names}")
        if setup_extractor:
            for ext in extractors:
                ext.setup()

        for data in tqdm.tqdm(self, desc="Adding data field"):
            for ext in extractors:
                setattr(data, ext.field_name, ext.extract_field(data))

    def append(self, data: DataMultiEBT):
        self._dataset[data.id] = data
        self._selected_ids.append(data.id)

    def save(self, dataset_path: Path):
        out_dataset = [d for d in self]
        save_dataset(dataset_path, out_dataset)

    def get_by_id(self, idx: str) -> DataMultiEBT:
        return self._dataset[idx]

    def __len__(self) -> int:
        return len(self._selected_ids)

    def __next__(self) -> DataMultiEBT:
        return self._dataset[next(self._id_iter)]

    def __iter__(self) -> Iterator[DataMultiEBT]:
        self._id_iter = iter(self._selected_ids)
        return self

    def __getitem__(self, i: int) -> DataMultiEBT:
        return self._dataset[self._selected_ids[i]]


def separate_dataset(
    first_dataset_name: str, second_dataset_name: str, out_dataset_name: str
):
    first_dataset_path = ThrowgenMacros.mebt_data_dir / first_dataset_name
    second_dataset_path = ThrowgenMacros.mebt_data_dir / second_dataset_name
    out_dataset = MultiEBTDataset.from_saved(first_dataset_path)
    second_dataset = MultiEBTDataset.from_saved(second_dataset_path)
    out_id = []
    for data in out_dataset:
        if data.id not in second_dataset._selected_ids:
            out_id.append(data.id)
    out_dataset._selected_ids = out_id
    out_dataset.save(ThrowgenMacros.mebt_data_dir / out_dataset_name)


def filter_dataset(
    base_dataset_name: str,
    out_dataset_name: str,
    selected_filter_names: list[str],
):
    base_dataset_path = ThrowgenMacros.mebt_data_dir / base_dataset_name
    out_dataset_path = ThrowgenMacros.mebt_data_dir / out_dataset_name
    mebt_dataset = MultiEBTDataset.from_saved(base_dataset_path)
    mebt_dataset.filter_dataset(selected_filter_names)
    mebt_dataset.save(out_dataset_path)


def merge_dataset(
    first_dataset_name: str, second_dataset_name: str, out_dataset_name: str
):
    first_dataset_path = ThrowgenMacros.mebt_data_dir / first_dataset_name
    second_dataset_path = ThrowgenMacros.mebt_data_dir / second_dataset_name
    out_dataset = MultiEBTDataset.from_saved(first_dataset_path)
    second_dataset = MultiEBTDataset.from_saved(second_dataset_path)
    for data in second_dataset:
        out_dataset.append(data)
    out_dataset.save(ThrowgenMacros.mebt_data_dir / out_dataset_name)


def update_dataset(
    base_dataset_name: str,
    out_dataset_name: str,
    setup_extractor: bool = False,
    selected_extractor_names: list[str] | None = None,
):
    base_dataset_path = ThrowgenMacros.mebt_data_dir / base_dataset_name
    out_dataset_path = ThrowgenMacros.mebt_data_dir / out_dataset_name
    mebt_dataset = MultiEBTDataset.from_saved(base_dataset_path)
    mebt_dataset.extend_partial_dataset(
        setup_extractor=setup_extractor,
        selected_extractor_names=selected_extractor_names,
    )
    mebt_dataset.save(out_dataset_path)


def generate_dataset_from_ne2e(
    ne2e_dataset_name: str,
    out_dataset_name: str,
    setup_extractor: bool = False,
    direct_throw: bool = True,
    selected_extractor_names: list[str] | None = None,
):
    ne2e_dataset_path = ThrowgenMacros.ne2e_data_dir / ne2e_dataset_name
    out_dataset_path = ThrowgenMacros.mebt_data_dir / out_dataset_name
    mebt_dataset = MultiEBTDataset.from_ne2e_dataset(ne2e_dataset_path, direct_throw)
    mebt_dataset.extend_partial_dataset(
        setup_extractor=setup_extractor,
        selected_extractor_names=selected_extractor_names,
    )
    mebt_dataset.save(out_dataset_path)


if __name__ == "__main__":
    su.log.setup(Macros.log_file, su.log.INFO)
    CLI(
        [
            generate_dataset_from_ne2e,
            update_dataset,
            filter_dataset,
            merge_dataset,
            separate_dataset,
        ],
        as_positional=False,
    )
