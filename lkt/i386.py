from pathlib import Path

from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree
from lkt.utils import CONFIGS

KERNEL_ARCH = 'i386'
CLANG_TARGET = 'i386-linux-gnu'
QEMU_ARCH = 'i386'


class I386Matrix(ArchMatrix):
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
                    job.make_targets.append('bzImage')

        if self.only_boot_testing:
            return jobs

        if 'other' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['allmodconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['allnoconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['tinyconfig']),
            ]

        if 'distro' in self.targets:
            jobs += [
                TestJob(
                    arch=KERNEL_ARCH,
                    bootable=True,
                    configs=[Path(CONFIGS, 'alpine/x86.config')],
                ),
                TestJob(
                    arch=KERNEL_ARCH,
                    bootable=True,
                    configs=[Path(CONFIGS, 'opensuse/i386.config')],
                ),
            ]

        return jobs
