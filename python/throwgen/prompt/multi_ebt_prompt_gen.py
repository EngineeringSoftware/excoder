from textwrap import dedent

from throwgen.dataset.data import DataMultiEBT
from throwgen.prompt.base_prompt_gen import BasePromptGen
from throwgen.utils import markdown
from typing_extensions import override


class MultiEBTPrompt(BasePromptGen):
    def _get_multi_ebt_args(self, data: DataMultiEBT) -> dict[str, str]:
        mut_name = data.mut_key.split("#")[1]  # type: ignore
        mut_no_throw = markdown.code_block(dedent(data.mut_no_throw).strip(), "java")
        exceptions_set = set()
        etests = ""
        for i, item in enumerate(data.ebts):
            exceptions_set.add(item.exception)
            etests += f"- EBT #{i}\n"
            etests += markdown.code_block(item.raw_code, "java") + "\n\n"
        exceptions = ", ".join(exceptions_set)

        out = {
            "mut_name": mut_name,
            "exceptions": exceptions.strip(),
            "mut_no_throw": mut_no_throw.strip(),
            "etests": etests,
            "class_name": data.mut_key.split("#")[0],
        }

        return out

    @override
    def get_message(self, data: DataMultiEBT) -> list[dict[str, str]]:
        user_args = self._get_multi_ebt_args(data)
        return [
            {
                "role": "system",
                "content": self._system,
            },
            {
                "role": "user",
                "content": self._fill_prompt(self._user, user_args),
            },
        ]
