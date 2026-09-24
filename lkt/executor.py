import os
import shutil
import time
from pathlib import Path

import lkt.utils
from lkt.env import EnvInfo
from lkt.job import MakeJob, TestJob
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree

KNOWN_SUBSYS_WERROR_CONFIGS = ('DRM_WERROR',)


def using_kvm(boot_utils_arch: str, boot_utils_folder: Path) -> bool:
    if lkt.utils.MACHINE == 'aarch64':
        if boot_utils_arch in {'arm', 'arm32_v7'}:
            can_use_kvm = lkt.utils.run_check_rc_zero(
                Path(boot_utils_folder, 'utils/aarch64_32_bit_el1_supported')
            )
        else:
            can_use_kvm = boot_utils_arch in {'arm64', 'arm64be'}
    elif lkt.utils.MACHINE == 'x86_64':
        can_use_kvm = boot_utils_arch in {'x86', 'x86_64'}
    else:
        can_use_kvm = False
    return can_use_kvm and lkt.utils.HAVE_DEV_KVM_ACCESS


def gen_log_cmd(cmd_str: str) -> str:
    return f"@echo '$$ {cmd_str}' $(LOG_OUTPUT_SILENT)"


def pretty_name_to_make_name(pretty_job_name: str) -> str:
    return pretty_job_name.replace(' ', '_').replace('_+_', '_').replace('""', '').replace('=', '_')


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
        verbose: bool = False,
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
        self.verbose: bool = verbose

        self.duration: str = ''

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
            'PRETTY_JOB_NAME': f"{job.make_vars['ARCH']} {' + '.join(map(str, job.configs))}",
        }
        make_job_cmds: list[str] = [
            # clean up previous build output if present
            '@rm -fr $(BUILD_OUTPUT)',
            # create results directory
            '@mkdir -p $(RESULTS)/$@',
            # save build name
            "@echo '$(PRETTY_JOB_NAME)' >$(NAME_RESULT)",
        ]
        make_job_name = pretty_name_to_make_name(make_job_variables['PRETTY_JOB_NAME'])
        if job.skip_build_reason:
            make_job_variables['SKIP_BUILD_REASON'] = job.skip_build_reason
            make_job_cmds += [
                # log skip reason into result
                '@echo "skipped due to $(SKIP_BUILD_REASON)" >$(BUILD_RESULT)',
                # show skipped build to user
                '@echo >&2 "Skipping $(PRETTY_JOB_NAME) due to $(SKIP_BUILD_REASON)..."',
            ]
            return MakeJob(
                name=make_job_name,
                prereqs=make_job_prereqs,
                cmds=make_job_cmds,
                variables=make_job_variables,
            )

        failed_build_handling = f"; if [ $${{PIPESTATUS[0]}} -ne 0 ]; then echo failed >$(BUILD_RESULT);{' echo skipped >$(BOOT_RESULT);' if job.bootable else ''} exit 1; fi"
        make_job_variables['MAKE_VARIABLES'] = ' '.join(
            f"{var}={job.make_vars[var]}"  # ty: ignore[invalid-key]
            for var in sorted(job.make_vars)
        )
        make_job_cmds.append("@echo >&2 'Building $(PRETTY_JOB_NAME)...'")

        # sift configurations
        base_config: lkt.utils.PathString = job.configs[0]
        requested_fragments: list[str] = []
        requested_options: list[str] = []
        if base_config == 'allmodconfig':
            requested_options.append('CONFIG_WERROR=n')
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
        if 'CONFIG_WERROR=n' in requested_options:
            # We do not want to have to maintain these in the callers but it is
            # important to note them in the build logs, so we add them here.
            # We should not add configurations that do not exist in the
            # tree that we are testing.
            requested_options += [
                f"{full_cfg}=n"
                for val in KNOWN_SUBSYS_WERROR_CONFIGS
                if (full_cfg := f"CONFIG_{val}") in self.lst.configs
            ]
        make_job_variables['REQUESTED_CONFIGS'] = ' '.join(requested_options)
        extra_configs = requested_options.copy()
        need_olddefconfig = False

        if isinstance(base_config, str):
            make_job_variables['INITIAL_MAKE_TARGETS'] = ' '.join(
                [base_config, *requested_fragments]
            )
            if extra_configs:
                # generate .config file for merge_config.sh
                initial_make_cmd_str: str = ' '.join([*base_make_cmd, '$(INITIAL_MAKE_TARGETS)'])
                make_job_cmds += [
                    gen_log_cmd(initial_make_cmd_str),
                    f"+{initial_make_cmd_str} $(LOG_OUTPUT){failed_build_handling}",
                ]
            else:
                base_make_cmd.append('$(INITIAL_MAKE_TARGETS)')
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
        make_job_variables['FINAL_MAKE_TARGETS'] = ' '.join(make_targets)
        final_make_cmd = ' '.join([*base_make_cmd, '$(FINAL_MAKE_TARGETS)'])
        make_job_cmds += [
            gen_log_cmd(final_make_cmd),
            f"+{final_make_cmd} $(LOG_OUTPUT){failed_build_handling}",
            '@echo successful >$(BUILD_RESULT)',
        ]
        if need_olddefconfig:
            chk_cmd = '$(CHKCFG) $(CONFIG_FILE) $(REQUESTED_CONFIGS)'
            make_job_cmds += [
                gen_log_cmd(chk_cmd),
                f"@{chk_cmd} $(LOG_OUTPUT)",
            ]

        # handle skipped boot if reason is provided
        if job.skip_boot_reason:
            make_job_variables['SKIP_BOOT_REASON'] = job.skip_boot_reason
            make_job_cmds += [
                # log skip reason into result
                "@echo 'skipped due to $(SKIP_BOOT_REASON)' >$(BOOT_RESULT)",
                # show skipped build to user
                "@echo >&2 'Skipping $(PRETTY_JOB_NAME) boot due to $(SKIP_BOOT_REASON)...'",
            ]
        # boot kernel if requested
        elif job.bootable:
            make_job_prereqs.append('$(BOOT_UTILS_JSON)')
            make_job_variables['BOOT_UTILS_ARCH'] = job.boot_utils_arch
            if using_kvm(job.boot_utils_arch, self.boot_utils_folder):
                make_job_variables['ADDITIONAL_BOOT_QEMU_ARGS'] = '-m 2G'
            make_job_cmds += [
                gen_log_cmd('$(BOOT_KERNEL)'),
                '$(BOOT_KERNEL) $(LOG_OUTPUT_SILENT) || { echo failed >$(BOOT_RESULT); exit 1; }',
                '@echo successful >$(BOOT_RESULT)',
            ]

        if not self.save_objects:
            make_job_cmds.append('@rm -fr $(BUILD_OUTPUT)')

        return MakeJob(
            name=make_job_name,
            prereqs=make_job_prereqs,
            cmds=make_job_cmds,
            variables=make_job_variables,
        )

    def generate_makefile(self) -> Path:
        test_jobs: list[TestJob] = [
            job
            for matrix in self.matrices
            for job in matrix.jobs
            if not self.only_boot_testing or (job.bootable and job.image_target)
        ]
        make_jobs: list[MakeJob] = [self._transform_test_into_make(job) for job in test_jobs]

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
BOOT_KERNEL = $(BOOT_UTILS)/boot-qemu.py -a $(BOOT_UTILS_ARCH) -k $(BUILD_OUTPUT) --gh-json-file $(BOOT_UTILS_JSON) $(ADDITIONAL_BOOT_QEMU_ARGS)

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

        makefile = self.generate_makefile()
        start = time.time()
        make_cmd = ['make', '-f', makefile, f"-kj{os.cpu_count()}"]
        if not self.verbose:
            make_cmd.append('-s')
        lkt.utils.run(make_cmd, show_cmd=True)
        self.duration = lkt.utils.get_time_diff(start)
