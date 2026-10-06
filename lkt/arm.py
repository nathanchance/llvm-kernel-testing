from pathlib import Path

from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree
from lkt.utils import CONFIGS
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'arm'
CLANG_TARGET = 'arm-linux-gnueabi'
QEMU_ARCH = 'arm'

# Add generic KCFI operand bundle lowering
# llvmorg-16-init-11473-gcacd3e73d7f8 (Tue Nov 22 23:01:18 2022 +0000)
# https://github.com/llvm/llvm-project/commit/cacd3e73d7f87ef3593443271ab3f170d0360934
MIN_LLVM_VER_CFI = ClangVersion(16, 0, 0)


class ArmMatrix(ArchMatrix):
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

    def _add_defconfig_jobs(self) -> list[TestJob]:
        dtb_pfx = 'aspeed/' if Path(self.lst.folder, 'arch/arm/boot/dts/aspeed').is_dir() else ''
        jobs: list[TestJob] = [
            TestJob(
                arch=KERNEL_ARCH,
                configs=['multi_v5_defconfig'],
                boot_utils_arch='arm32_v5',
                extra_make_targets=[f"{dtb_pfx}aspeed-bmc-opp-palmetto.dtb"]
                if self.only_boot_testing
                else [],
            ),
            TestJob(
                arch=KERNEL_ARCH,
                configs=['aspeed_g5_defconfig'],
                boot_utils_arch='arm32_v6',
                extra_make_targets=[f"{dtb_pfx}aspeed-bmc-opp-romulus.dtb"]
                if self.only_boot_testing
                else [],
            ),
            TestJob(arch=KERNEL_ARCH, configs=['multi_v7_defconfig']),
            TestJob(arch=KERNEL_ARCH, configs=['multi_v7_defconfig', 'CONFIG_THUMB2_KERNEL=y']),
        ]

        if not self.lst.arch_supports_kcfi(KERNEL_ARCH):
            cfi_skip_reason = f"Linux < {LinuxVersion(6, 10, 0)} (have '{self.lst.version}')"
        elif self.env_info.clang.version < MIN_LLVM_VER_CFI:
            cfi_skip_reason = f"LLVM < {MIN_LLVM_VER_CFI} (using '{self.env_info.clang.version}')"
        else:
            cfi_skip_reason = ''
        jobs.append(
            TestJob(
                arch=KERNEL_ARCH,
                configs=['multi_v7_defconfig', self.lst.get_cfi_y_config()],
                skip_build_reason=cfi_skip_reason,
            )
        )

        for job in jobs:
            job.bootable = True
            if self.only_boot_testing:
                job.make_targets.append('zImage')

        return jobs

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        if 'def' in self.targets:
            jobs += self._add_defconfig_jobs()

        if self.only_boot_testing:
            return jobs

        if 'other' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['allmodconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['allnoconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['tinyconfig']),
            ]

        if 'distro' in self.targets:
            configs: list[tuple[str, str]] = [
                ('alpine', 'armv7'),
                ('archlinux', 'armv7'),
                ('debian', 'armmp'),
                ('opensuse', 'armv7hl'),
            ]
            for distro, config_name in configs:
                jobs.append(
                    TestJob(
                        arch=KERNEL_ARCH,
                        bootable=True,
                        configs=[Path(CONFIGS, distro, f"{config_name}.config")],
                    )
                )

        return jobs
