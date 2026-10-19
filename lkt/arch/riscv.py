from pathlib import Path

from ..core.env import EnvInfo
from ..core.job import TestJob
from ..core.matrix import ArchMatrix
from ..core.source import LinuxSourceTree
from ..core.version import ClangVersion, LinuxVersion
from ..utils import CONFIGS

KERNEL_ARCH = 'riscv'
CLANG_TARGET = 'riscv64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 'riscv64'

# Merge patch series "riscv: KCFI support"
# v6.5-rc1-46-g7f7d3ea6eb00 (Thu Aug 31 00:18:32 2023 -0700)
# https://git.kernel.org/linus/7f7d3ea6eb000bd329a6f2fe3f1c7596c4e783e1
MIN_LLVM_VER_CFI = ClangVersion(17, 0, 0)
# riscv: Allow CONFIG_CFI_CLANG to be selected
# v6.5-rc1-6-g74f8fc31feb4 (Wed Aug 23 14:16:41 2023 -0700)
# https://git.kernel.org/linus/74f8fc31feb4b756814ec0720f48ccdc1175f774
LNX_VER_CFI = LinuxVersion(6, 6, 0)

# RISC-V: build: Allow LTO to be selected
# v6.8-rc1-2-g021d23428bdb (Mon Jan 22 10:06:29 2024 -0800)
# https://git.kernel.org/linus/021d23428bdbae032294e8f4a29cb53cb50ae71c
EXPECTED_LNX_VER_LTO = LinuxVersion(6, 9, 0)
# The first version to support linker relaxation
BROKEN_LTO_START = ClangVersion(15, 0, 0)
# [lld][RISCV] Handle relaxation reductions of more than 65536 bytes
# llvmorg-17-init-11453-g9d37ea95df1b (Tue May 16 14:59:36 2023 -0700)
# https://github.com/llvm/llvm-project/commit/9d37ea95df1b84cca9b5e954d8964c976a5e303e
BROKEN_LTO_END = ClangVersion(17, 0, 0)

# [CodeGen][RISCV] Change Shadow Call Stack Register to X3
# llvmorg-17-init-7844-gaa1d2693c256 (Wed Apr 12 21:06:22 2023 +0000)
# https://github.com/llvm/llvm-project/commit/aa1d2693c25622ea4a8ee2b622ba2a617e18ef88
MIN_LLVM_VER_SCS = ClangVersion(17, 0, 0)
# riscv: Implement Shadow Call Stack
# v6.6-rc1-4-gd1584d791a29 (Fri Oct 27 14:43:08 2023 -0700)
# https://git.kernel.org/linus/d1584d791a297aa8ed93503382a682a6ecfc4218
EXPECTED_LNX_VER_SCS = LinuxVersion(6, 7, 0)


class RISCVMatrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            lst, env_info, targets, CLANG_TARGET, QEMU_ARCH, only_boot_testing, **kwargs
        )

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        riscv_kconfig_txt = self.lst.read_text('arch/riscv/Kconfig')
        llvm_ver = self.env_info.clang.version
        lnx_ver = self.lst.version

        if llvm_ver < MIN_LLVM_VER_CFI:
            cfi_skip_reason = f"LLVM < {MIN_LLVM_VER_CFI} (using '{llvm_ver}')"
        elif not self.lst.arch_supports_kcfi(KERNEL_ARCH):
            cfi_skip_reason = f"Linux < {LNX_VER_CFI} (have '{lnx_ver}')"
        else:
            cfi_skip_reason = ''

        if 'ARCH_SUPPORTS_LTO_CLANG' not in riscv_kconfig_txt:
            lto_skip_reason = f"Linux < {EXPECTED_LNX_VER_LTO} (have '{lnx_ver}')"
            lto_allmod_skip_reason = lto_skip_reason
        elif BROKEN_LTO_START <= llvm_ver < BROKEN_LTO_END:
            lto_skip_reason = ''
            lto_allmod_skip_reason = (
                f"LLVM between {BROKEN_LTO_START} and {BROKEN_LTO_END} (using '{llvm_ver}')"
            )
        else:
            lto_skip_reason = ''
            lto_allmod_skip_reason = ''

        if llvm_ver < MIN_LLVM_VER_SCS:
            scs_skip_reason = f"LLVM < {MIN_LLVM_VER_SCS} (using '{llvm_ver}')"
        elif 'ARCH_SUPPORTS_SHADOW_CALL_STACK' not in riscv_kconfig_txt:
            scs_skip_reason = f"Linux < {EXPECTED_LNX_VER_SCS} (using '{lnx_ver}')"
        else:
            scs_skip_reason = ''

        cfi_y_config = self.lst.get_cfi_y_config()

        if 'def' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['defconfig']),
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=['defconfig', 'CONFIG_LTO_CLANG_THIN=y'],
                    skip_build_reason=lto_skip_reason,
                ),
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=['defconfig', cfi_y_config, 'CONFIG_SHADOW_CALL_STACK=y'],
                    skip_build_reason=scs_skip_reason or cfi_skip_reason,
                ),
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=[
                        'defconfig',
                        cfi_y_config,
                        'CONFIG_SHADOW_CALL_STACK=y',
                        'CONFIG_LTO_CLANG_THIN=y',
                    ],
                    skip_build_reason=scs_skip_reason or cfi_skip_reason or lto_skip_reason,
                ),
            ]
            if scs_skip_reason:
                jobs.append(
                    TestJob(
                        arch=KERNEL_ARCH,
                        configs=['defconfig', cfi_y_config],
                        skip_build_reason=cfi_skip_reason,
                    )
                )

            for job in jobs:
                job.bootable = True
                if self.only_boot_testing:
                    job.make_targets.append('Image')

        if self.only_boot_testing:
            return jobs

        if 'other' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['allmodconfig']),
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=['allmodconfig', 'CONFIG_GCOV_KERNEL=n', 'CONFIG_LTO_CLANG_THIN=y'],
                    skip_build_reason=lto_allmod_skip_reason,
                ),
            ]

        if 'distro' in self.targets:
            extra_make_targets = ['Image']
            for distro in ('alpine', 'debian', 'fedora', 'opensuse'):
                config_file = Path(CONFIGS, distro, 'riscv64.config')
                job = TestJob(arch=KERNEL_ARCH, configs=[config_file])
                # riscv: set default pm_power_off to NULL
                # v5.15-rc1-6-gf2928e224d85 (Mon Oct 4 14:16:57 2021 -0700)
                # https://git.kernel.org/linus/f2928e224d85e7cc139009ab17cefdfec2df5d11
                job.bootable = 'f2928e224d85e7cc139009ab17cefdfec2df5d11' in self.lst.commits
                if not job.bootable:
                    job.skip_boot_reason = f"lack of f2928e224d85e (from {LinuxVersion(5, 16, 0)})"
                # Nothing is explicitly wrong with this configuration option but it
                # changes the default image target, which boot-utils does not expect,
                # so explicitly add the bootable image target to the end of the command
                if self.lst.is_config_set(config_file, 'EFI_ZBOOT'):
                    job.extra_make_targets = extra_make_targets
                jobs.append(job)

        return jobs
