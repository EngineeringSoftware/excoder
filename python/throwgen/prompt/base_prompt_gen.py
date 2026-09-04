import re
from typing import Any

from etestgen.macros import Macros


class BasePromptGen:
    def __init__(self, system_file_name: str, user_file_name: str):
        prompt_dir = Macros.python_dir / "throwgen" / "prompt" / "prompt_text"
        with open(prompt_dir / system_file_name) as system_file:
            self._system: str = system_file.read()
        with open(prompt_dir / user_file_name) as user_file:
            self._user: str = user_file.read()

    @staticmethod
    def _fill_prompt(prompt: str, arguments: dict[str, str]) -> str:
        out_prompt = prompt
        for k, v in arguments.items():
            if f"~`{k}`~" not in out_prompt:
                raise KeyError(f"{k} is not an argument in the prompt")
            out_prompt = out_prompt.replace(f"~`{k}`~", v)

        left_over = re.search(r"~`[^~]*`~", out_prompt)
        if left_over is not None:
            raise KeyError(
                f"{left_over.group(0)} not found in given arguments"
            )

        return out_prompt

    def get_message(self, data: Any) -> list[dict[str, str]]:
        raise NotImplementedError("get_message not implemented")
