import os
import shutil
from pathlib import Path

import lkt.utils
from lkt.env import EnvInfo
from lkt.job import MakeJob, TestJob
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree


def gen_log_cmd(cmd_str: str) -> str:
    return f"@echo '$$ {cmd_str}' $(LOG_OUTPUT_SILENT)"


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

    def _transform_test_into_make(self, job: TestJob) -> MakeJob:
        # delete LLVM_IAS if it is the default
        if job.make_vars['LLVM_IAS'] == '1':
            del job.make_vars['LLVM_IAS']
        # update job make variables with executor wide make variables
        job.make_vars.update(self.make_vars)

        # base make command to run
        base_make_cmd: list[str] = ['$(MAKE_KERNEL) $(MAKE_VARIABLES)']

        # initial make job information
        make_job_prereqs = ['prepare']
        make_job_variables: dict[str, str] = {
            'MAKE_VARIABLES': ' '.join(
                f"{var}={job.make_vars[var]}"  # ty: ignore[invalid-key]
                for var in sorted(job.make_vars)
            ),
            'PRETTY_JOB_NAME': f"{job.make_vars['ARCH']} {' + '.join(map(str, job.configs))}",
        }
        make_job_cmds: list[str] = [
            # clean up previous build output if present
            '@rm -fr $(BUILD_OUTPUT)',
            # create results directory
            '@mkdir -p $(RESULTS)/$@',
            # print initial information about build
            "@echo >&2 'Building $(PRETTY_JOB_NAME)...'",
            "@echo '$(PRETTY_JOB_NAME)' >$(NAME_RESULT)",
        ]
        failed_preamble = f"; if [ $${{PIPESTATUS[0]}} -ne 0 ]; then echo failed >$(BUILD_RESULT);{' echo skipped >$(BOOT_RESULT);' if job.bootable else ''} exit 1; fi"

        # sift configurations
        base_config: lkt.utils.PathString = job.configs[0]
        requested_fragments: list[str] = []
        requested_options: list[str] = []
        for item in job.configs[1:]:
            if not isinstance(item, str):
                msg = f"{item} is not a string?"
                raise TypeError(msg)
            if item.endswith('.config'):
                requested_fragments.append(item)
            elif item.startswith('CONFIG_'):
                if '=' not in item:
                    msg = f"{item} does not contain '='?"
                    raise ValueError(msg)
                requested_options.append(item)
            else:
                msg = f"Cannot handle {item}?"
                raise ValueError(msg)
        make_job_variables['REQUESTED_CONFIGS'] = ' '.join(requested_options)
        extra_configs = requested_options.copy()
        need_olddefconfig = False

        if isinstance(base_config, str):
            if extra_configs:
                # generate .config file for merge_config.sh
                initial_make_cmd_str: str = ' '.join(
                    [*base_make_cmd, base_config, *requested_fragments]
                )
                make_job_cmds += [
                    gen_log_cmd(initial_make_cmd_str),
                    f"+{initial_make_cmd_str} $(LOG_OUTPUT){failed_preamble}",
                ]
            else:
                base_make_cmd += [base_config, *requested_fragments]
        else:
            msg = f"Unsupported base configuration: {base_config}"
            raise TypeError(msg)

        if extra_configs:
            # Certain configuration options are choices and Kconfig warns when
            # choices are overridden. Disable the default choice when a choice
            # is present.
            if 'CONFIG_LTO_CLANG_THIN=y' in extra_configs:
                extra_configs.append('CONFIG_LTO_NONE=n')
            if 'CONFIG_CPU_BIG_ENDIAN=y' in extra_configs:
                extra_configs.append('CONFIG_CPU_LITTLE_ENDIAN=n')
            if 'CONFIG_CPU_LITTLE_ENDIAN=y' in extra_configs:
                extra_configs.append('CONFIG_CPU_BIG_ENDIAN=n')

            make_job_variables['EXTRA_CONFIGS'] = ' '.join(extra_configs)

            # generate .merge.config from extra_configs
            make_job_cmds.append("@printf '%s\\n' $(EXTRA_CONFIGS) >$(MERGE_CONFIG_FILE)")

            # show .merge.config in log for reproduction
            cat_cmd: str = 'cat $(MERGE_CONFIG_FILE)'
            make_job_cmds += [gen_log_cmd(cat_cmd), f"@{cat_cmd} $(LOG_OUTPUT_SILENT)"]

            # run merge_config.sh
            merge_config_cmd: str = (
                '$(MERGE_CONFIG_SH) -m -O $(BUILD_OUTPUT) $(CONFIG_FILE) $(MERGE_CONFIG_FILE)'
            )
            make_job_cmds += [
                gen_log_cmd(merge_config_cmd),
                f"{merge_config_cmd} $(LOG_OUTPUT_SILENT)",
            ]

            need_olddefconfig = True

        # build kernel and additional targets
        make_targets = [
            job.image_target if self.only_boot_testing else 'all',
            *job.extra_make_targets,
        ]
        if need_olddefconfig:
            make_targets.insert(0, 'olddefconfig')
        final_make_cmd = ' '.join([*base_make_cmd, *make_targets])
        make_job_cmds += [
            gen_log_cmd(final_make_cmd),
            f"+{final_make_cmd} $(LOG_OUTPUT){failed_preamble}",
            '@echo success >$(BUILD_RESULT)',
        ]
        if need_olddefconfig:
            chk_cmd = '$(CHKCFG) $(CONFIG_FILE) $(REQUESTED_CONFIGS)'
            make_job_cmds += [
                gen_log_cmd(chk_cmd),
                f"@{chk_cmd} $(LOG_OUTPUT)",
            ]

        if job.bootable:
            make_job_prereqs.append('$(BOOT_UTILS_JSON)')
            make_job_variables['BOOT_UTILS_ARCH'] = job.boot_utils_arch
            make_job_cmds += [
                gen_log_cmd('$(BOOT_KERNEL)'),
                '$(BOOT_KERNEL) $(LOG_OUTPUT_SILENT) || { echo failed >$(BOOT_RESULT); exit 1; }',
                '@echo success >$(BOOT_RESULT)',
            ]

        if not self.save_objects:
            make_job_cmds.append('@rm -fr $(BUILD_OUTPUT)')

        return MakeJob(
            name=make_job_variables['PRETTY_JOB_NAME']
            .replace(' ', '_')
            .replace('_+_', '_')
            .replace('""', '')
            .replace('=', '_'),
            prereqs=make_job_prereqs,
            cmds=make_job_cmds,
            variables=make_job_variables,
        )

    def _generate_makefile(self) -> Path:
        make_jobs: list[MakeJob] = [
            self._transform_test_into_make(job) for matrix in self.matrices for job in matrix.jobs
        ]

        makefile = self.build_folder.joinpath('Makefile')
        makefile_txt = f"""\
SHELL := /bin/bash

# Folders
BOOT_UTILS := {self.boot_utils_folder}
BUILD := {self.build_folder}
CONFIGS := {lkt.utils.CONFIGS}
LOGS := {self.logs_folder}
RESULTS := {self.results_folder}
SRC := {self.lst.folder}

# Files
BOOT_UTILS_JSON := {self.logs_folder.parent.joinpath('.boot-utils.json')}
CHKCFG := {lkt.utils.CONFIGS.parent.joinpath('scripts/check_olddefconfig.py')}
MERGE_CONFIG_SH := $(SRC)/scripts/kconfig/merge_config.sh

# Recursive macros
BUILD_OUTPUT = $(BUILD)/$@
CONFIG_FILE = $(BUILD_OUTPUT)/.config
MERGE_CONFIG_FILE = $(BUILD_OUTPUT)/.merge.config

BUILD_RESULT = $(RESULTS)/$@/build
BOOT_RESULT = $(RESULTS)/$@/boot
NAME_RESULT = $(RESULTS)/$@/name

LOG_OUTPUT = 2>&1 | tee -a $(LOGS)/$@.log
LOG_OUTPUT_SILENT = 2>&1 >>$(LOGS)/$@.log

MAKE_KERNEL = $(MAKE) -C $(SRC) -s O=$(BUILD_OUTPUT)
BOOT_KERNEL = $(BOOT_UTILS)/boot-qemu.py -a $(BOOT_UTILS_ARCH) -k $(BUILD_OUTPUT) --gh-json-file $(BOOT_UTILS_JSON)

# Rules
.PHONY: all
all: {' '.join(job.name for job in make_jobs)}

.PHONY: prepare
prepare:
\t@rm -fr $(LOGS) $(RESULTS)
\t@mkdir -p $(LOGS) $(RESULTS)

$(BOOT_UTILS_JSON): prepare
\t@curl -LSso $(BOOT_UTILS_JSON) https://api.github.com/repos/ClangBuiltLinux/boot-utils/releases/latest || test -f $(BOOT_UTILS_JSON)

{'\n'.join(str(job) for job in make_jobs)}
"""
        makefile.write_text(makefile_txt, encoding='utf-8')
        return makefile

    def run(self) -> None:
        lkt.utils.header('Running test matrix', end='')

        if self.build_folder.exists():
            shutil.rmtree(self.build_folder)
        self.build_folder.mkdir(parents=True)

        makefile = self._generate_makefile()
        lkt.utils.run(['make', '-f', makefile, f"-kj{os.cpu_count()}"], show_cmd=True)
