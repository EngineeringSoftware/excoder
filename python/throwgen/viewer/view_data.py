import seutil as su
import tqdm
from jsonargparse import CLI
from throwgen.dataset.multi_ebt_data import MultiEBTDataset
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.utils import markdown, code


class ViewData:
    def __init__(self, dataset_name: str):
        self._dataset_name = dataset_name
        dataset_path = ThrowgenMacros.mebt_data_dir / dataset_name
        self._dataset = MultiEBTDataset.from_saved(dataset_path)

    def _get_native_no_throw(self, n: int) -> str:
        cnt = 0
        out = markdown.MarkdownNode.new_empty_node(f"{self._dataset_name} asserts", 1)
        with tqdm.tqdm(
            total=n, desc="getting native no throw method with assert"
        ) as pbar:
            for data in self._dataset:
                if cnt >= n:
                    break
                if "throw" not in data.mut:
                    cov_code = data.mut_no_throw
                    for i, cov in enumerate(data.coverage):
                        for c_line in cov:
                            cov_code = code.add_comment(cov_code, c_line, f"EBT #{i}") + "\n"
                    code_sec = out.get_new_subsection(data.id)
                    code_sec.replace_body(markdown.code_block(cov_code, "java"))
                    cnt += 1
                    pbar.update(1)

        return str(out)

    def save_to_file(self, method: str, kwargs: dict):
        out_dir = ThrowgenMacros.viewer_dir / "dataview" / self._dataset_name
        su.io.mkdir(out_dir)
        with open(out_dir / f"{method}.md", "w") as out_file:
            out_str = getattr(self, f"_{method}")(**kwargs)
            out_file.write(out_str)


if __name__ == "__main__":
    CLI(ViewData, as_positional=False)
