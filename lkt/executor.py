import shutil
from pathlib import Path

import lkt.utils
from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree


class MakeJob:
    def __init__(
        self, name: str, prereqs: list[str], cmds: list[str], variables: dict[str, str]
    ) -> None:
        self.cmds: list[str] = cmds
        self.name: str = name
        self.prereqs: list[str] = prereqs
        self.variables: dict[str, str] = variables

    def __str__(self) -> str:
        parts = [f"{self.name}: {key} := {value}" for key, value in self.variables]
        parts.append(f"{self.name}: {' '.join(self.prereqs)}")
        parts += [f"\t{cmd}" for cmd in self.cmds]
        return '\n'.join(parts)


class Executor:
    def __init__(
        self,
        matrices: list[ArchMatrix],
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        boot_utils_folder: Path,
        build_folder: Path,
        output_folder: Path,
        only_boot_testing: bool = False,
        save_objects: bool = False,
    ) -> None:
        self.matrices: list[ArchMatrix] = matrices
        self.lst: LinuxSourceTree = lst
        self.env_info: EnvInfo = env_info
        self.boot_utils_folder: Path = boot_utils_folder
        self.build_folder: Path = build_folder
        self.logs_folder: Path = Path(output_folder, 'logs')
        self.make_jobs: list[MakeJob] = []
        self.make_vars: lkt.utils.MakeVars = {}
        self.only_boot_testing: bool = only_boot_testing
        self.results_folder: Path = Path(output_folder, 'results')
        self.save_objects: bool = save_objects

        makefile_txt = self.lst.folder.joinpath('Makefile').read_text(encoding='utf-8')
        if 'HOSTLDFLAGS += -fuse-ld=lld' not in makefile_txt:
            self.make_vars['HOSTLDFLAGS'] = '-fuse-ld=lld'

        clang_prefix = self.env_info.clang.location.parent
        found_libclang: Path | None = None
        # upstream
        if (libclang := clang_prefix.joinpath('lib/libclang.so')).exists():
            found_libclang = libclang
        # debian
        elif possible_libclangs := list(clang_prefix.glob('lib/libclang-*.so.1')):
            found_libclang = possible_libclangs[0]
        if found_libclang:
            self.make_vars['LIBCLANG_PATH'] = found_libclang.as_posix()

    def _transform_job(self, job: TestJob) -> MakeJob:
        if job.make_vars['LLVM_IAS'] == '1':
            del job.make_vars['LLVM_IAS']
        job.make_vars.update(self.make_vars)

        make_vars = [f"{var}={job.make_vars[var]}" for var in sorted(job.make_vars)]  # ty: ignore[invalid-key]
        base_make_cmd = f"$(MAKE_KERNEL) {' '.join(make_vars)}"

        make_targets = [
            job.image_target if self.only_boot_testing else 'all',
            *job.extra_make_targets,
        ]

        pretty_job_name = f"{job.make_vars['ARCH']} {' + '.join(map(str, job.configs))}"

        make_job_name = pretty_job_name.replace(' ', '_').replace('_+_', '_').replace('""', '')
        make_job_prereqs = ['prepare']
        make_job_cmds = [
            "@rm -fr $(BUILD_OUTPUT)",
            f"@echo '$$ {base_make_cmd}' $(LOG_OUTPUT)",
            f"+{base_make_cmd}",
        ]
        make_job_variables = {}

        return MakeJob(
            name=make_job_name,
            prereqs=make_job_prereqs,
            cmds=make_job_cmds,
            variables=make_job_variables,
        )

    def run(self) -> None:
        if self.build_folder.exists():
            shutil.rmtree(self.build_folder)
        self.build_folder.mkdir(parents=True)

        makefile = self.build_folder.joinpath('Makefile')
        makefile_header = f"""\
BOOT_UTILS := {self.boot_utils_folder}
BUILD := {self.build_folder}
CONFIGS := {lkt.utils.CONFIGS}
LOGS := {self.logs_folder}
RESULTS := {self.results_folder}
BOOT_UTILS_JSON := {self.logs_folder.parent.joinpath('.boot-utils.json')}

BUILD_OUTPUT = $(BUILD)/$@
LOG_OUTPUT = 2>&1 >>$(LOGS)/$@.log
MAKE_KERNEL = $(MAKE) -C $(SRC_FOLDER) -s O=$(BUILD_OUTPUT)
BOOT_KERNEL = $(BOOT_UTILS)/boot-qemu.py -a $(BOOT_UTILS_ARCH) -k $(BUILD_OUTPUT) --gh-json-file $(BOOT_UTILS_JSON)"""
