from typing_extensions import override
from throwgen.prompt.base_prompt_gen import BasePromptGen
from throwgen.dataset.data import DataMultiEBT
from dataclasses import fields
import re

class OneFieldPromptGen(BasePromptGen):
    def __init__(self, system_file_name: str, user_file_name: str):
        super().__init__(system_file_name, user_file_name)
        field_match = re.search(r"~`([^~]*)`~", self._user)
        assert field_match is not None

        self._field_name = field_match.group(1)
        assert self._field_name in [f.name for f in fields(DataMultiEBT)]


    @override
    def get_message(self, data: DataMultiEBT) -> list[dict[str, str]]:
        field_value = {self._field_name: getattr(data, self._field_name)}
        return [
            {
                "role": "system",
                "content": self._system,
            },
            {
                "role": "user",
                "content": self._fill_prompt(self._user, field_value),
            },
        ]
