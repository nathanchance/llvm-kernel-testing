from ..core.env import EnvInfo
from ..core.job import TestJob
from ..core.matrix import ArchMatrix
from ..core.source import LinuxSourceTree

KERNEL_ARCH = 'mips'
CLANG_TARGET = 'mips-linux-gnu'


class MipsMatrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(lst, env_info, targets, CLANG_TARGET, 'mips', only_boot_testing, **kwargs)

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        extra_configs: list[str] = []
        if 'c47c7ab9b53635860c6b48736efdd22822d726d7' not in self.lst.commits:
            extra_configs.append('CONFIG_BLK_DEV_INITRD=y')

        if 'def' in self.targets:
            jobs.append(
                TestJob(
                    arch=KERNEL_ARCH,
                    bootable=True,
                    configs=['malta_defconfig', 'CONFIG_CPU_BIG_ENDIAN=y', *extra_configs],
                    make_targets=['vmlinux'] if self.only_boot_testing else [],
                )
            )
            if not self.only_boot_testing:
                jobs.extend(
                    TestJob(arch=KERNEL_ARCH, configs=[f"32r{isa_ver}_defconfig"])
                    for isa_ver in ('2', '6')
                )

        if not self.only_boot_testing and 'other' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['allnoconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['tinyconfig']),
            ]

        return jobs


class MipsELMatrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            lst, env_info, targets, CLANG_TARGET, 'mipsel', only_boot_testing, **kwargs
        )

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        extra_configs: list[str] = []
        if 'c47c7ab9b53635860c6b48736efdd22822d726d7' not in self.lst.commits:
            extra_configs.append('CONFIG_BLK_DEV_INITRD=y')

        if 'def' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['malta_defconfig', *extra_configs]),
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=[
                        'malta_defconfig',
                        'CONFIG_RELOCATABLE=y',
                        'CONFIG_RELOCATION_TABLE_SIZE=0x00200000',
                        'CONFIG_RANDOMIZE_BASE=y',
                        *extra_configs,
                    ],
                ),
            ]
            for job in jobs:
                job.bootable = True
                job.boot_utils_arch = 'mipsel'
                if self.only_boot_testing:
                    job.make_targets.append('vmlinux')
            if self.only_boot_testing:
                return jobs
            for isa_ver in ('2', '6'):
                jobs.append(TestJob(arch=KERNEL_ARCH, configs=[f"32r{isa_ver}el_defconfig"]))

        return jobs
