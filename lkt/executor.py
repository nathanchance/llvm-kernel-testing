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
        parts = [f".PHONY: {self.name}"]
        parts += [f"{self.name}: {key} := {value}" for key, value in self.variables.items()]
        parts.append(f"{self.name}: {' '.join(self.prereqs)}")
        parts += [f"\t{cmd}" for cmd in self.cmds]
        return '\n'.join(parts)


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

    def _transform_test_into_make(self, job: TestJob) -> MakeJob:
        # delete LLVM_IAS if it is the default
        if job.make_vars['LLVM_IAS'] == '1':
            del job.make_vars['LLVM_IAS']
        # update job make variables with executor wide make variables
        job.make_vars.update(self.make_vars)

        pretty_job_name = f"{job.make_vars['ARCH']} {' + '.join(map(str, job.configs))}"

        # base make command to run
        base_make_cmd: list[str] = ['$(MAKE_KERNEL)'] + [
            f"{var}={job.make_vars[var]}"  # ty: ignore[invalid-key]
            for var in sorted(job.make_vars)
        ]
        make_job_cmds: list[str] = [
            f"@echo >&2 'Building {pretty_job_name}...'",
            # clean up previous build output if present
            '@rm -fr $(BUILD_OUTPUT)',
        ]

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
                    f"+{initial_make_cmd_str} $(LOG_OUTPUT)",
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

            # generate .merge.config from extra_configs
            make_job_cmds.append(f"@printf '%s\\n' {' '.join(extra_configs)} >$(MERGE_CONFIG_FILE)")

            # show .merge.config in log for reproduction
            cat_cmd: str = 'cat $(MERGE_CONFIG_FILE)'
            make_job_cmds += [gen_log_cmd(cat_cmd), f"@{cat_cmd} $(LOG_OUTPUT_SILENT)"]

            merge_config_cmd: str = '$(SRC)/scripts/kconfig/merge_config.sh -m -O $(BUILD_OUTPUT) $(CONFIG_FILE) $(MERGE_CONFIG_FILE)'
            make_job_cmds += [gen_log_cmd(merge_config_cmd), f"{merge_config_cmd} $(LOG_OUTPUT_SILENT)"]

            need_olddefconfig = True

        make_targets = [
            job.image_target if self.only_boot_testing else 'all',
            *job.extra_make_targets,
        ]
        if need_olddefconfig:
            make_targets.insert(0, 'olddefconfig')
        final_make_cmd: str = ' '.join([*base_make_cmd, *make_targets])
        make_job_cmds += [gen_log_cmd(final_make_cmd), f"+{final_make_cmd} $(LOG_OUTPUT)"]

        make_job_prereqs = ['prepare']
        make_job_variables = {}
        if job.bootable:
            make_job_prereqs.append('$(BOOT_UTILS_JSON)')
            make_job_variables['BOOT_UTILS_ARCH'] = job.boot_utils_arch
            make_job_cmds += [
                gen_log_cmd('$(BOOT_KERNEL)'),
                '$(BOOT_KERNEL) $(LOG_OUTPUT_SILENT) || { cat $(LOGS)/$@.log; /bin/false; }',
            ]

        if not self.save_objects:
            make_job_cmds.append('@rm -fr $(BUILD_OUTPUT)')

        return MakeJob(
            name=pretty_job_name.replace(' ', '_').replace('_+_', '_').replace('""', '').replace('=', '_'),
            prereqs=make_job_prereqs,
            cmds=make_job_cmds,
            variables=make_job_variables,
        )

    def run(self) -> None:
        if self.build_folder.exists():
            shutil.rmtree(self.build_folder)
        self.build_folder.mkdir(parents=True)

        for matrix in self.matrices:
            for job in matrix.jobs:
                self.make_jobs.append(self._transform_test_into_make(job))

        makefile = self.build_folder.joinpath('Makefile')
        makefile_txt = f"""\
BOOT_UTILS := {self.boot_utils_folder}
BUILD := {self.build_folder}
CONFIGS := {lkt.utils.CONFIGS}
LOGS := {self.logs_folder}
RESULTS := {self.results_folder}
SRC := {self.lst.folder}
BOOT_UTILS_JSON := {self.logs_folder.parent.joinpath('.boot-utils.json')}

BUILD_OUTPUT = $(BUILD)/$@
CONFIG_FILE = $(BUILD_OUTPUT)/.config
MERGE_CONFIG_FILE = $(BUILD_OUTPUT)/.merge.config
LOG_OUTPUT = 2>&1 | tee -a $(LOGS)/$@.log
LOG_OUTPUT_SILENT = 2>&1 >>$(LOGS)/$@.log
MAKE_KERNEL = $(MAKE) -C $(SRC) -s O=$(BUILD_OUTPUT)
BOOT_KERNEL = $(BOOT_UTILS)/boot-qemu.py -a $(BOOT_UTILS_ARCH) -k $(BUILD_OUTPUT) --gh-json-file $(BOOT_UTILS_JSON)

.PHONY: all
all: {' '.join(job.name for job in self.make_jobs)}

.PHONY: prepare
prepare:
\t@rm -fr $(LOGS) $(RESULTS)
\t@mkdir -p $(LOGS) $(RESULTS)

$(BOOT_UTILS_JSON): prepare
\t@curl -LSso $(BOOT_UTILS_JSON) https://api.github.com/repos/ClangBuiltLinux/boot-utils/releases/latest || test -f $(BOOT_UTILS_JSON)

{'\n'.join(str(job) for job in self.make_jobs)}
"""
        makefile.write_text(makefile_txt, encoding='utf-8')
