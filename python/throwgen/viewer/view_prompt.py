from typing import Literal, cast

import seutil as su
from jsonargparse import CLI
from throwgen.dataset.multi_ebt_data import MultiEBTDataset
from throwgen.llm.base_experiment import BaseExperiment
from throwgen.macros import Macros as ThrowgenMacros
from throwgen.prompt.add_on_prompt_gen import AddOnPrompt
from throwgen.utils import markdown
import numpy as np

PromptOutType = Literal["stdout", "file"]
FULL_PROMPT_NUM = 10


class ViewPrompt:
    def __init__(self, dataset_name: str, prompt_gen_type: str):
        self._dataset_name = dataset_name
        self._prompt_gen_type = prompt_gen_type
        dataset_path = ThrowgenMacros.mebt_data_dir / dataset_name
        self._dataset = MultiEBTDataset.from_saved(dataset_path)
        self._prompt_gen = BaseExperiment.PROMPT[prompt_gen_type]["gen"](
            *BaseExperiment.PROMPT[prompt_gen_type]["file"]
        )

    def prompt_to_stdout(self, data_id: str):
        print(self._get_prompt(data_id))

    def prompt_to_file(self, data_id: str):
        out_path = (
            ThrowgenMacros.viewer_dir
            / "prompts"
            / f"{self._dataset_name}-{data_id}-{self._prompt_gen_type}.md"
        )
        su.io.mkdir(out_path.parent)
        with open(out_path, "w") as out_file:
            out_file.write(self._get_prompt(data_id))

    def full_prompt_to_file(self):
        out_path = (
            ThrowgenMacros.viewer_dir
            / "prompts"
            / f"{self._dataset_name}-full-prompt-{self._prompt_gen_type}.md"
        )
        su.io.mkdir(out_path.parent)
        full_prompt = self._get_full_prompt()
        if full_prompt is not None:
            with open(out_path, "w") as out_file:
                out_file.write(full_prompt)
        else:
            print("No full prompt find")

    def _get_full_prompt(self) -> str | None:
        prompt_gen = cast(AddOnPrompt, self._prompt_gen)
        all_avail = []
        for data in self._dataset:
            availability = prompt_gen.data_availability(data)
            all_avail.append(np.mean(availability))
            if np.mean(availability) > 0.79:
                return self._get_prompt(data.id)
        print(np.max(all_avail))
        return None

    def _get_prompt(self, data_id: str) -> str:
        data = self._dataset.get_by_id(data_id)

        messages = self._prompt_gen.get_message(data)

        # format message to a markdown
        out = (
            markdown.title(
                f"Dataset: {self._dataset_name} "
                + f"id: {data_id} "
                + f"prompt: {self._prompt_gen_type}",
                1,
            )
            + "\n"
        )
        out += markdown.title("System", 2) + "\n"
        out += messages[0]["content"]
        out += markdown.title("User", 2) + "\n"
        out += messages[1]["content"]

        return out


if __name__ == "__main__":
    CLI(ViewPrompt, as_positional=False)
