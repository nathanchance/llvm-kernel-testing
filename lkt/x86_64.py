from pathlib import Path

from lkt.job import TestJob
from lkt.matrix import ArchMatrix
from lkt.version import ClangVersion

KERNEL_ARCH = 'x86_64'

# KCFI sanitizer
# llvmorg-16-init-2791-gcff5bef948c9 (Wed Aug 24 22:41:38 2022 +0000)
# https://github.com/llvm/llvm-project/commit/cff5bef948c91e4919de8a5fb9765e0edc13f3de
MIN_LLVM_VER_CFI = ClangVersion(16, 0, 0)


class X8664Matrix(ArchMatrix):
    def _add_defconfig_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = [
            TestJob(arch=KERNEL_ARCH, configs=['defconfig']),
            TestJob(arch=KERNEL_ARCH, configs=['defconfig', 'CONFIG_LTO_CLANG_THIN=y']),
        ]
        # cfi: Switch to -fsanitize=kcfi
        # v6.0-rc4-5-g89245600941e (Mon Sep 26 10:13:13 2022 -0700)
        # https://git.kernel.org/linus/89245600941e4e0f87d77f60ee269b5e61ef4e49
        if (
            self.env_info.clang.version >= MIN_LLVM_VER_CFI
            and '89245600941e4e0f87d77f60ee269b5e61ef4e49' in self.lst.commits
        ):
            cfi_y_config = self.lst.get_cfi_y_config()

            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['defconfig', cfi_y_config]),
                TestJob(
                    arch=KERNEL_ARCH, configs=['defconfig', cfi_y_config, 'CONFIG_LTO_CLANG_THIN=y']
                ),
            ]

        if Path(self.lst.folder, 'kernel/configs/hardening.config').exists():
            jobs.append(TestJob(arch=KERNEL_ARCH, configs=['defconfig', 'hardening.config']))

        for job in jobs:
            job.bootable = True

        return jobs

    def _add_otherconfig_jobs(self) -> list[TestJob]:  # ruff: ignore[no-self-use]
        jobs: list[TestJob] = []

        return jobs

    def _add_distroconfig_jobs(self) -> list[TestJob]:  # ruff: ignore[no-self-use]
        jobs: list[TestJob] = []

        return jobs

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        if 'def' in self.targets:
            jobs += self._add_defconfig_jobs()
        if 'other' in self.targets:
            jobs += self._add_otherconfig_jobs()
        if 'distro' in self.targets:
            jobs += self._add_distroconfig_jobs()

        return jobs
