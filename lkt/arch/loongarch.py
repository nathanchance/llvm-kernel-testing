from pathlib import Path

from ..core.env import EnvInfo
from ..core.job import TestJob
from ..core.matrix import ArchMatrix
from ..core.source import LinuxSourceTree
from ..core.version import ClangVersion, LinuxVersion, QemuVersion
from ..utils import CONFIGS

KERNEL_ARCH = 'loongarch'
CLANG_TARGET = 'loongarch64-linux-gnusf'
QEMU_ARCH = 'loongarch64'

# https://git.kernel.org/torvalds/l/65eea6b44a5dd332c50390fdaeda7e197802c484
MIN_LNX_VER = LinuxVersion(6, 5, 0)

# Building the kernel for LoongArch was not very well supported prior to LLVM
# 18.x
HARD_MIN_LLVM_VER = ClangVersion(18, 0, 0)

# QEMU older than 8.0.0 hits an assert in Loongson's EDK2 firmware:
# ASSERT [VirtNorFlashDxe] .../Platform/Loongson/LoongArchQemuPkg/Library/NorFlashQemuLib/NorFlashQemuLib.c(56): !(((INTN)(RETURN_STATUS)(FindNodeStatus)) < 0)
MIN_QEMU_VER = QemuVersion(8, 0, 0)


class LoongArchMatrix(ArchMatrix):
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

        if 'def' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['defconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['defconfig', 'CONFIG_LTO_CLANG_THIN=y']),
            ]
            for job in jobs:
                job.bootable = True
                if self.only_boot_testing:
                    job.make_targets.append('vmlinuz.efi')

        if not self.only_boot_testing:
            if 'other' in self.targets:
                jobs += [
                    TestJob(arch=KERNEL_ARCH, configs=['allmodconfig']),
                    TestJob(
                        arch=KERNEL_ARCH,
                        configs=[
                            'allmodconfig',
                            'CONFIG_FTRACE=n',
                            'CONFIG_GCOV_KERNEL=n',
                            'CONFIG_LTO_CLANG_THIN=y',
                        ],
                    ),
                ]

            if 'distro' in self.targets:
                jobs.append(
                    TestJob(
                        arch=KERNEL_ARCH,
                        # For some reason, booting fails on 6.6; use 6.12 (the next LTS series) as a baseline for booting
                        bootable=self.lst.version >= LinuxVersion(6, 12, 0),
                        configs=[Path(CONFIGS, 'alpine/loongarch64.config')],
                    )
                )

        if (clang_ver := self.env_info.clang.version) < HARD_MIN_LLVM_VER:
            for job in jobs:
                job.skip_build_reason = f"LLVM < {HARD_MIN_LLVM_VER} (using '{clang_ver}')"
        elif '65eea6b44a5dd332c50390fdaeda7e197802c484' not in self.lst.commits:
            for job in jobs:
                job.skip_build_reason = (
                    f"missing 65eea6b44a5dd from Linux {MIN_LNX_VER} (have '{self.lst.version}')"
                )

        if (qemu_ver := self.env_info.qemu[QEMU_ARCH].version) < MIN_QEMU_VER:
            for job in jobs:
                if job.bootable:
                    job.bootable = False
                    job.skip_boot_reason = f"QEMU < {MIN_QEMU_VER} (found '{qemu_ver}')"

        return jobs
