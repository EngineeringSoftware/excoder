import json
import re
from collections.abc import Iterator
from typing import Any

import seutil as su
from throwgen.dataset.data import DataMultiEBT
from throwgen.dataset.extractors.base_extractor import BaseExtractor
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override


class MUTNoThrowExtractor(BaseExtractor):
    @override
    def __init__(self, all_data: Iterator[DataMultiEBT], meta_data: dict[str, Any]):
        super().__init__(all_data, meta_data)
        self._class_header: str | None = None
        self._preprocessed = False
        self._dataset_name = meta_data["dataset_name"]
        # The remover prints one line per throw statement it took out; Table II's
        # throw counts are tallied from this dump by count_data_perks.
        self._throw_rm_path = (
            ThrowgenMacros.mebt_data_dir / self._dataset_name / "throw-rm-output.jsonl"
        )
        su.io.mkdir(self._throw_rm_path.parent)
        open(self._throw_rm_path, "w").close()
        with su.io.cd(ThrowgenMacros.java_src_dir):
            rr = su.bash.run("mvn clean compile assembly:single")
            if rr.returncode != 0:
                raise OSError(f"mvn build ends in error:\n\n{rr.stdout}")

    @property
    @override
    def field_name(self) -> str:
        return "mut_no_throw"

    def _preprocess_code(self, code: str) -> str:
        if re.search(r"\sdefault\s", " " + code) is None or "public final" in code:
            self._class_header = "class temp"
        else:
            self._class_header = "interface temp"
        self._preprocessed = True
        return self._class_header + " {" + code + "}"

    def _extract_method(self, code: str) -> str:
        assert self._class_header is not None and self._preprocessed
        method_match = re.search(
            self._class_header + r" {([\s\S]*)}", code, re.MULTILINE
        )
        if method_match is not None:
            return method_match.group(1)
        else:
            raise ValueError("no method found")

    @override
    def extract_field(self, data: DataMultiEBT) -> str:
        self._preprocessed = False
        classed_out = self._remove_throw(self._preprocess_code(data.mut), data.id)
        return self._extract_method(classed_out)

    def _remove_throw(self, code: str, id: str) -> str:
        with su.io.cd(ThrowgenMacros.java_src_dir):
            with open(f"{id}.java", "w") as throw_mut_file:
                throw_mut_file.write(code)
            rr = su.bash.run(
                "java -cp "
                + "target/throwgen-datacollection-1.0-SNAPSHOT-jar-with-dependencies.jar "
                + f"org.throwgen.core.ThrowRemover {id}.java no_throw.java"
            )
            if rr.returncode != 0:
                raise OSError(f"Remove throw error in {id}.java\n\n{rr.stderr}")
            with open(self._throw_rm_path, "a") as tro_file:
                tro_file.write(json.dumps({"id": id, "out": rr.stdout}) + "\n")
            su.bash.run(f"rm {id}.java")
            with open("no_throw.java") as no_throw_file:
                classed_out = no_throw_file.read()
            su.bash.run("rm no_throw.java")

        return classed_out
