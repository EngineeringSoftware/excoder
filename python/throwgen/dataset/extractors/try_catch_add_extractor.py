import seutil as su
from throwgen.dataset.extractors.mut_no_throw_extractor import \
    MUTNoThrowExtractor
from throwgen.macros import Macros as ThrowgenMacros
from typing_extensions import override


class TryCatchAddExtractor(MUTNoThrowExtractor):
    @override
    def _remove_throw(self, code: str, id: str) -> str:
        code = super()._remove_throw(code, id)
        with su.io.cd(ThrowgenMacros.java_src_dir):
            with open(f"{id}.java", "w") as throw_mut_file:
                throw_mut_file.write(code)
            rr = su.bash.run(
                "java -cp "
                + "target/throwgen-datacollection-1.0-SNAPSHOT-jar-with-dependencies.jar "
                + f"org.throwgen.core.TryCatchAdder {id}.java no_throw.java"
            )
            if rr.returncode != 0:
                raise OSError(f"Remove throw error in {id}.java\n\n{rr.stderr}")
            su.bash.run(f"rm {id}.java")
            with open("no_throw.java") as no_throw_file:
                classed_out = no_throw_file.read()
            su.bash.run("rm no_throw.java")

        return classed_out

    @override
    def _extract_method(self, code: str) -> str:
        try:
            return super()._extract_method(code)
        except ValueError:
            return ""
