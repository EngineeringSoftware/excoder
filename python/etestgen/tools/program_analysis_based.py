from jsonargparse import CLI
from etestgen.macros import Macros
from etestgen.utils import configure_tests
from pathlib import Path
from tqdm import tqdm
from seutil.maven import MavenProject
import seutil as se
import time
import os
import traceback
import subprocess
import glob
import re


class GenerateTests:
    def generate_tests_with_one_seed(
        self,
        project_name: str,
        test_type: str = "randoop",
        output_dir: str = None,
        log_dir: str = None,
        seed: int = 42,
        dep_file_path: str = None,
        classpath_list_path: str = None,
    ):
        if test_type == "randoop":
            res = self.generate_randoop_tests(
                project_name,
                seed,
                output_dir,
                log_dir,
                Macros.tool_time_limit,
                dep_file_path,
                classpath_list_path,
            )
            self.fix_randoop_generated_tests_helper(project_name, output_dir)
        elif test_type == "evosuite" or test_type == "evosuitefit":
            res = self.generate_evosuite_tests(
                project_name,
                seed,
                test_type,
                output_dir,
                log_dir,
                Macros.tool_time_limit,
                dep_file_path,
                classpath_list_path,
            )
        else:
            res = f"Unknown test type: {test_type}"
        print(f"When seed is {seed}, {res}")

    def generate_randoop_tests(
        self,
        project_name: str,
        seed: int,
        output_dir: str,
        log_dir: str = None,
        time_limit: int = 100,
        dep_file_path: str = None,
        classpath_file_path: str = None,
    ):
        print("run randoop...")
        res = {}
        res["seed"] = seed
        if log_dir is None:
            randoop_log_dir = Macros.log_dir / "randoop"
        else:
            randoop_log_dir = log_dir
        se.io.mkdir(randoop_log_dir)
        log_path = f"{randoop_log_dir}/{project_name}-randoop.log"
        error_log_path = f"{randoop_log_dir}/run-randoop.log"

        randoop_tests_dir = Macros.downloads_dir / project_name / "randoop-tests"
        se.io.mkdir(randoop_tests_dir)
        try:
            with se.io.cd(randoop_tests_dir):
                print("running randoop...")
                try:
                    classpath_list = se.io.load(classpath_file_path, se.io.Fmt.txtList)
                    if project_name == "statefulj_statefulj":
                        classpath_list.remove(
                            "org.statefulj.framework.binders.jersey.StatefulJResourceConfig"
                        )
                        classpath_list.remove(
                            "org.statefulj.persistence.jpa.JPAPerister"
                        )
                        se.io.dump(
                            classpath_file_path, classpath_list, se.io.Fmt.txtList
                        )
                    total_time_limit = min(len(classpath_list) * time_limit, 10800)
                    print(f"total time limit: {total_time_limit}")
                    se.bash.run(
                        f"java -cp {Macros.randoop_jar}:$(< {dep_file_path}) randoop.main.Main gentests --time-limit={total_time_limit} --usethreads=true --randomseed={seed} --classlist={classpath_file_path} &> {log_path}",
                        0,
                        timeout=total_time_limit + 1800,
                    )
                    se.bash.run(f"chmod -R 777 {Macros.downloads_dir}/{project_name}")
                except (subprocess.TimeoutExpired, Exception) as e:
                    se.io.dump(
                        f"{error_log_path}",
                        [f"{e}"],
                        se.io.Fmt.txtList,
                        append=True,
                    )
                java_files = se.bash.run("find . -name 'RegressionTest*.java'").stdout
                if java_files.strip():
                    res["randoop"] = True
                    se.io.mkdir(Path(output_dir).parent)
                    se.bash.run(f"cp -r {randoop_tests_dir} {output_dir}")
                else:
                    res["randoop"] = False
        except Exception as e:
            print(traceback.format_exc())
            res["randoop"] = False
            se.io.dump(
                f"{error_log_path}",
                [f"{e}"],
                se.io.Fmt.txtList,
                append=True,
            )
        return res

    def fix_randoop_generated_tests_helper(
        self, project_name: str, generated_tests_dir
    ):
        generated_tests_dir = Path(generated_tests_dir)
        if not generated_tests_dir.exists():
            return
        regression_test_file = generated_tests_dir / "RegressionTest.java"

        if not regression_test_file.exists():
            print(f"fixing {project_name}...")
            # list all java files
            regression_test_java_files = generated_tests_dir.glob(
                "RegressionTest*.java"
            )
            regression_test_java_files = list(regression_test_java_files)
            if regression_test_java_files:
                # create a RegressionTest.java file
                with open(regression_test_file, "w") as f:
                    f.write(r"import org.junit.runner.RunWith;" + "\n")
                    f.write(r"import org.junit.runners.Suite;" + "\n")
                    f.write(r"@RunWith(Suite.class)" + "\n")
                    f.write(
                        r"@Suite.SuiteClasses({"
                        + ", ".join(
                            [
                                f"{file.stem}.class"
                                for file in regression_test_java_files
                            ]
                        )
                        + r"})"
                        + "\n"
                    )
                    f.write(r"public class RegressionTest {}")
        else:
            print(f"skip {project_name}...")

    def generate_evosuite_tests(
        self,
        project_name: str,
        seed: int = 0,
        tool_name: str = "evosuite",
        output_dir: str = None,
        log_dir: str = None,
        time_limit: int = 120,
        dep_file_path: str = None,
        classpath_file_path: str = None,
    ):
        print(f"run {tool_name}...")
        res = {}
        res["seed"] = seed
        if log_dir is None:
            evosuite_log_dir = Macros.log_dir / tool_name
        else:
            evosuite_log_dir = log_dir
        se.io.mkdir(evosuite_log_dir)
        log_path = f"{evosuite_log_dir}/{project_name}-{tool_name}.log"
        error_log_path = f"{evosuite_log_dir}/run-{tool_name}.log"

        try:
            if classpath_file_path is not None:
                print("find classes...")
                # classpath_list = se.io.load(classpath_file_path, se.io.Fmt.txtList)
                classpath_list = self.get_classes(project_name)
                if not classpath_list:
                    res[tool_name] = False
                    return res
                # copy project to a temp dir
                se.bash.run(f"rm -rf {Macros.downloads_dir}/{project_name}-temp")
                se.bash.run(
                    f"cp -r {Macros.downloads_dir}/{project_name} {Macros.downloads_dir}/{project_name}-temp"
                )
                for classpath in tqdm(classpath_list):
                    if project_name == "sbtourist_Journal.IO":
                        if classpath in [
                            "journal.io.util.IOHelper",
                            "journal.io.api.Journal$WriteType",
                        ]:
                            continue

                    # copy the temp dir
                    se.bash.run(f"rm -rf {Macros.downloads_dir}/{project_name}")
                    se.bash.run(
                        f"cp -r {Macros.downloads_dir}/{project_name}-temp {Macros.downloads_dir}/{project_name}"
                    )
                    if "$" in classpath:
                        classpath = classpath.replace("$", "\\$")
                    if tool_name == "evosuite":
                        command = f"java -jar {Macros.evosuite_jar} -DCP_file_path {dep_file_path} -class {classpath} -seed {seed} -Dsearch_budget={time_limit} -Duse_separate_classloader=false -Dminimize=false -Dassertion_strategy=all -Dfilter_assertions=true -Dvirtual_fs=false -Dvirtual_net=false -Dsandbox_mode=OFF -Dfilter_sandbox_tests=true -Dmax_loop_iterations=-1 &> {log_path}"
                    else:
                        command = f"java -jar {Macros.evosuitefit_jar} -DCP_file_path {dep_file_path} -class {classpath} -seed {seed} -Dcriteria=exception -Dsearch_budget={time_limit} -Duse_separate_classloader=false -Dminimize=false -Dassertion_strategy=all -Dfilter_assertions=true -Dvirtual_fs=false -Dvirtual_net=false -Dsandbox_mode=OFF -Dfilter_sandbox_tests=true -Dmax_loop_iterations=-1 &> {log_path}"
                    print(command)
                    try:
                        with se.io.cd(Macros.downloads_dir / project_name):
                            se.bash.run(command, 0, timeout=5 * time_limit)
                    except (subprocess.TimeoutExpired, Exception) as e:
                        print(traceback.format_exc())
                        res["evosuite"] = False
                        se.io.dump(
                            f"{error_log_path}",
                            [f"{e}"],
                            se.io.Fmt.txtList,
                            append=True,
                        )
                    finally:
                        self.copy_tests(project_name, output_dir)
            else:
                # target is whole project
                # TODO: this only works for single-module mave test
                # check if target/classes exists
                if not os.path.exists("target/classes"):
                    se.bash.run("mvn test-compile", 0)
                if tool_name == "evosuite":
                    command = f"java -jar {Macros.evosuite_jar} -DCP_file_path {dep_file_path} -target {Macros.downloads_dir}/{project_name}/target/classes -seed {seed} -Dsearch_budget={time_limit} -Dassertion_timeout={time_limit} -Dminimization_timeout={time_limit} -Duse_separate_classloader=false -Dminimize=false -Dassertion_strategy=all -Dfilter_assertions=true -Dfilter_sandbox_tests=true -Dvirtual_fs=false -Dvirtual_net=false -Dsandbox_mode=OFF -Dmax_loop_iterations=-1 &> {log_path}"
                else:
                    command = f"java -jar {Macros.evosuitefit_jar} -DCP_file_path {dep_file_path} -target {Macros.downloads_dir}/{project_name}/target/classes -seed {seed} -Dcriteria=exception -Dsearch_budget={time_limit} -Dassertion_timeout={time_limit} -Dminimization_timeout={time_limit} -Duse_separate_classloader=false -Dminimize=false -Dassertion_strategy=all -Dfilter_assertions=true -Dfilter_sandbox_tests=true -Dvirtual_fs=false -Dvirtual_net=false -Dsandbox_mode=OFF -Dmax_loop_iterations=-1 &> {log_path}"
                print(command)
                try:
                    with se.io.cd(Macros.downloads_dir / project_name):
                        se.bash.run(command, 0, timeout=5 * time_limit)
                except Exception as e:
                    print(traceback.format_exc())
                    res[tool_name] = False
                    se.io.dump(
                        f"{error_log_path}",
                        [f"{e}"],
                        se.io.Fmt.txtList,
                        append=True,
                    )
                finally:
                    self.copy_tests(project_name, output_dir)

            if os.path.exists(output_dir):
                res["evosuite"] = True
            else:
                res["evosuite"] = False
        except Exception as e:
            print(traceback.format_exc())
            res["evosuite"] = False
            se.io.dump(
                f"{error_log_path}",
                [f"{e}"],
                se.io.Fmt.txtList,
                append=True,
            )
        finally:
            se.bash.run(f"rm -rf {Macros.downloads_dir}/{project_name}-temp")
        return res

    def copy_tests(self, project_name: str, output_dir: str):
        # copy evosuite tests to output dir set the permission to
        # write to the project dir, sometimes generated test will
        # change the permission of the project dir
        se.bash.run(f"chmod -R 777 {Macros.downloads_dir}/{project_name}")
        if (Macros.downloads_dir / project_name / "evosuite-tests").exists():
            if not os.path.exists(output_dir):
                se.bash.run(f"mkdir {output_dir}")
            # post-process generated tests, change (timeout = 4000) to (timeout = 4000000)
            se.bash.run(
                "shopt -s globstar;sed -i 's/@Test(timeout = 4000)/@Test(timeout = 4000000)/g' evosuite-tests/**/*.java"
            )

            se.bash.run(
                f"cp -r {Macros.downloads_dir}/{project_name}/evosuite-tests/* {output_dir}"
            )

        if (Macros.downloads_dir / project_name / "evosuite-files").exists():
            if not os.path.exists(f"{output_dir}/evosuite-files"):
                se.bash.run(f"mkdir {output_dir}/evosuite-files")
            se.bash.run(
                f"cp -r {Macros.downloads_dir}/{project_name}/evosuite-files/* {output_dir}/evosuite-files"
            )

    def get_classes(self, project_name: str):
        """The classes EvoSuite should target in *project_name*.

        `ThrowgenToolAdapter._write_evosuite_class_lists` writes this file for
        every project in the dataset before generation starts, so it is always
        present on the ExCoder path.
        """
        evosuite_classes_path = Macros.exp_dir / project_name / "evosuite-classes.txt"
        if not evosuite_classes_path.exists():
            raise FileNotFoundError(
                f"No target class list at {evosuite_classes_path}; run "
                f"`python -m throwgen.tools.tool_test_adapter generate_and_extract` "
                f"rather than calling GenerateTests directly."
            )
        return se.io.load(evosuite_classes_path, se.io.Fmt.txtList)

    def get_dependencies(self, project_name: str, clazz: str, sha: str = None):
        if sha:
            self.prepare_project(project_name, sha)
        with se.io.cd(Macros.downloads_dir / project_name):
            se.bash.run("mvn clean test-compile", 0)
            deps_file = Macros.exp_dir / project_name / "evosuite-deps.txt"
            deps_command = (
                f"jdeps -cp $(< {deps_file}) -v -R -dotoutput jdepsoutput {clazz}"
            )
            se.bash.run(deps_command, 0)
            # analyze the output
            deps = set()
            classes_dot_path = "jdepsoutput/classes.dot"
            if not os.path.exists(classes_dot_path):
                return deps
            lines = se.io.load(classes_dot_path, se.io.Fmt.txtList)
            for line in lines:
                if "->" in line:
                    left_dep = self.parse_jdeps_line(line.split("->")[0])
                    # right_dep = cls.parse_jdeps_line(line.split("->")[1])
                    if left_dep:
                        deps.add(left_dep)
                    # if right_dep:
                    #     deps.add(right_dep)
            deps.add(clazz)
            return deps

    def parse_jdeps_line(self, line: str):
        dep = line.split("(")[0].strip().replace('"', "")
        if "_downloads/" in dep or dep.endswith(".jar") or dep.endswith(".class"):
            return None
        return dep

    def prepare_project(
        self,
        project_name: str,
        sha: str,
    ):
        if (Macros.downloads_dir / project_name).exists():
            se.bash.run(f"chmod -R 777 {Macros.downloads_dir}/{project_name}")
        project = se.project.Project(
            url=f"https://github.com/{project_name.replace('_', '/')}",
            full_name=project_name,
        )
        project.clone(Macros.downloads_dir)
        project.checkout(sha, forced=True)
        return project

    def dump_dependencies(
        self,
        project_name: str,
        project: se.project.Project,
        dep_file_path: str,
        classpath_list_path: str,
    ):
        configure_tests(project_name)
        maven_project = MavenProject.from_project(project)
        try:
            with se.io.cd(Macros.downloads_dir / project_name):
                # TODO: will use maven_project.install() when new seutil is released
                # maven_project.install()
                se.bash.run(f"mvn package -DskipTests {Macros.SKIPS}", 0)
                # get dependencies
                deps_list = []
                for module in maven_project.modules:
                    deps_list.append(
                        os.pathsep.join(
                            [
                                module.main_classpath,
                                module.test_classpath,
                                module.dependency_classpath,
                            ]
                        )
                    )
                # check if the class path is empty, evosuite will
                # fail if the class path is empty
                # https://github.com/EvoSuite/evosuite/issues/100
                updated_deps_list = []
                for cps in deps_list:
                    for classpath in cps.split(":"):
                        if not os.path.exists(classpath):
                            continue
                        if os.path.isdir(classpath) and not os.listdir(classpath):
                            continue
                        updated_deps_list.append(classpath)
                dependencies = os.pathsep.join(updated_deps_list)
                se.io.dump(dep_file_path, dependencies, se.io.Fmt.txt)

                # get CUT (class under tests) classpath
                if classpath_list_path:
                    classpath_list = self.find_classes()
                    se.io.dump(classpath_list_path, classpath_list, se.io.Fmt.txtList)
        except Exception as e:
            print(e)

    def find_classes(self):
        # precodition: execute under the project root
        classpath_list = []
        classes = se.bash.run("find . -name '*.class'").stdout
        for classpath in classes.splitlines():
            # do not test tests
            if "target/classes/" not in classpath:
                continue
            # remove package-info.class and module-info.class
            if classpath.endswith("package-info.class") or classpath.endswith(
                "module-info.class"
            ):
                continue
            cp = (
                classpath.split("target/classes/")[-1]
                .replace(".class", "")
                .replace(r"/", r".")
            )
            classpath_list.append(cp)
        return classpath_list

    def execute_tests(
        self,
        tool: str,
        project_name: str,
        generated_tests_dir: str,
        log_file_path: str,
        deps_file_path: str,
        time_limit: int = 600,
    ):
        self.download_jars()
        with se.io.cd(Macros.downloads_dir / project_name):
            se.bash.run(f"mvn test-compile {Macros.SKIPS}")

        if generated_tests_dir is not None:
            print(f"copying {tool} test cases...")
            copied_tests_dir = Macros.downloads_dir / project_name / f"{tool}-tests"
            if (copied_tests_dir).exists():
                se.bash.run(f"rm -rf {copied_tests_dir}")
            se.bash.run(
                f"cp -r {generated_tests_dir} {copied_tests_dir}",
                0,
            )
            # remove ErrorTest*.java from copied_tests_dir
            se.bash.run(
                f"find {copied_tests_dir} -name 'ErrorTest*.java' -delete",
                0,
            )

        # collect class names
        classes = set()
        with se.io.cd(f"{Macros.downloads_dir/project_name}"):
            for f in glob.glob(f"{tool}-tests/**/*.java", recursive=True):
                if f.endswith("Test.java"):
                    classes.add(
                        f.replace(f"{tool}-tests/", "")
                        .replace(".java", "")
                        .replace("/", ".")
                    )
        if not classes:
            return 0

        if tool == "evosuite":
            # TODO: hacky way to fix EvoSuite issue: comment out org.evosuite.runtime.GuiSupport
            with se.io.cd(f"{Macros.downloads_dir/project_name}"):
                for f in glob.glob(
                    "evosuite-tests/**/*_scaffolding.java", recursive=True
                ):
                    content = se.io.load(f, se.io.Fmt.txt)
                    se.io.dump(
                        f,
                        content.replace(
                            "org.evosuite.runtime.GuiSupport",
                            "//org.evosuite.runtime.GuiSupport",
                        ).replace(
                            "org.evosuite.runtime.jvm.ShutdownHookHandler",
                            "//org.evosuite.runtime.jvm.ShutdownHookHandler",
                        ),
                        se.io.Fmt.txt,
                    )

        ################################## Execute tests ##################################
        print("compiling and executing test cases...")
        with se.io.cd(f"{Macros.downloads_dir / project_name}"):
            jar_path = Macros.evosuite_jar if tool == "evosuite" else Macros.randoop_jar
            comp_str = f"shopt -s globstar; javac -cp {jar_path}:{Macros.junit_jar}:$(< {deps_file_path}) {tool}-tests/**/*.java"
            print(comp_str)
            try:
                se.bash.run(comp_str, 0)
            except Exception as e:
                se.io.dump(log_file_path, traceback.format_exc(), se.io.Fmt.txt)
                return -1
            try:
                with se.TimeUtils.time_limit(time_limit):
                    class_str = ""
                    for c in classes:
                        # TODO: hacky way to comment out a class that causes the tests to disappear
                        if c == "de.redsix.pdfcompare.CompareResultImpl_ESTest":
                            continue
                        class_str += f"{c} "

                    run_str = f"java -Dlogback.configurationFile={Macros.python_dir}/configs/logback.xml -cp {tool}-tests:{jar_path}:$(< {deps_file_path}) org.junit.runner.JUnitCore {class_str} &> {log_file_path}"
                    print(run_str)
                    run_res = se.bash.run(run_str)
            except se.TimeoutException:
                return -1
        return run_res.returncode

    def download_jars(self):
        if not Macros.randoop_jar.exists():
            se.bash.run(f"mkdir -p {Macros.jar_dir}", 0)
            se.bash.run(
                f"wget https://github.com/randoop/randoop/releases/download/v4.3.2/randoop-4.3.2.zip -O {Macros.jar_dir}/randoop-4.3.2.zip",
                0,
            )
            se.bash.run(
                f"unzip {Macros.jar_dir}/randoop-4.3.2.zip -d {Macros.jar_dir}", 0
            )

        if not Macros.evosuite_jar.exists():
            se.bash.run(f"mkdir -p {Macros.jar_dir}", 0)
            se.bash.run(
                f"wget https://github.com/EvoSuite/evosuite/releases/download/v1.2.0/evosuite-1.2.0.jar -O {Macros.evosuite_jar}",
                0,
            )

        if not Macros.junit_jar.exists():
            se.bash.run(
                f"wget https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/1.9.0-RC1/junit-platform-console-standalone-1.9.0-RC1.jar -O {Macros.junit_jar}",
                0,
            )

        if not Macros.evosuitefit_jar.exists():
            se.bash.run(
                f"wget https://github.com/Greg4cr/evosuitefit-exp/blob/master/lib/evosuitefit-1.0.7.jar -O {Macros.evosuitefit_jar}",
                0,
            )

if __name__ == "__main__":
    CLI(GenerateTests, as_positional=False)
