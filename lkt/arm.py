#!/usr/bin/env python3

from pathlib import Path
import re
import shutil

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'arm'
CLANG_TARGET = 'arm-linux-gnueabi'
QEMU_ARCH = 'arm'

# https://github.com/ClangBuiltLinux/linux/issues?q=is%3Aissue+label%3A%22%5BARCH%5D+arm32%22+label%3A%22%5BTOOL%5D+integrated-as%22+label%3A%22%5BBUG%5D+linux%22+
MIN_IAS_LNX_VER = LinuxVersion(5, 13, 0)
# https://github.com/ClangBuiltLinux/linux/issues?q=is%3Aissue+label%3A%22%5BARCH%5D+arm32%22+label%3A%22%5BTOOL%5D+integrated-as%22+label%3A%22%5BFIXED%5D%5BLLVM%5D+13%22+
MIN_IAS_LLVM_VER = ClangVersion(13, 0, 0)

# https://github.com/llvm/llvm-project/commit/cacd3e73d7f87ef3593443271ab3f170d0360934
MIN_LLVM_VER_CFI = ClangVersion(16, 0, 0)


def disable_be(linux):
    text = Path(linux, 'arch/arm/mm/Kconfig').read_text(encoding='utf-8')
    first_pattern = 'bool "Build big-endian kernel"'
    second_pattern = 'depends on ARCH_SUPPORTS_BIG_ENDIAN'
    return not re.search(f"({first_pattern}|{second_pattern})\n\tdepends on !LD_IS_LLD", text)


class ArmLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = 'arm32_v7'
        self.image_target = 'zImage'
        self.qemu_arch = QEMU_ARCH


class ArmLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self):
        runners = []
        defconfigs = [
            ('multi_v5_defconfig', 'arm32_v5'),
            ('aspeed_g5_defconfig', 'arm32_v6'),
            ('multi_v7_defconfig', 'arm32_v7'),
        ]
        for config_target, boot_arch in defconfigs:
            runner = ArmLLVMKernelRunner()
            runner.boot_arch = boot_arch
            runner.configs = [config_target]
            if self.only_test_boot:
                # https://git.kernel.org/linus/724ba6751532055db75992fc6ae21c3e322e94a7
                dtb_prefix = 'aspeed/' if Path(self.folders.source,
                                               'arch/arm/boot/dts/aspeed').is_dir() else ''
                if config_target == 'multi_v5_defconfig':
                    runner.make_targets.append(f"{dtb_prefix}aspeed-bmc-opp-palmetto.dtb")
                elif config_target == 'aspeed_g5_defconfig':
                    runner.make_targets.append(f"{dtb_prefix}aspeed-bmc-opp-romulus.dtb")
            runners.append(runner)

        # https://github.com/ClangBuiltLinux/linux/issues/325
        if '9d417cbe36eee' in self.lsm.commits or 'CONFIG_HAVE_FUTEX_CMPXCHG' not in self.lsm.configs:
            runner = ArmLLVMKernelRunner()
            runner.configs = ['multi_v7_defconfig', 'CONFIG_THUMB2_KERNEL=y']
            runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} multi_v7_defconfig + Thumb2",
                f"either lack of 9d417cbe36eee (from {LinuxVersion(5, 15, 0)}) or presence of CONFIG_HAVE_FUTEX_CMPXCHG",
            )

        arm_kconfig_text = Path(self.folders.source, 'arch/arm/Kconfig').read_text(encoding='utf-8')
        arm_supports_kcfi = 'select ARCH_SUPPORTS_CFI_CLANG' in arm_kconfig_text
        if self._llvm_version >= MIN_LLVM_VER_CFI and arm_supports_kcfi:
            runner = ArmLLVMKernelRunner()
            runner.configs = ['multi_v7_defconfig', 'CONFIG_CFI_CLANG=y']
            runners.append(runner)
        else:
            # https://git.kernel.org/rmk/c/1a4fec49efe5273eb2fcf575175a117745f76f97
            self._skip_one(
                f"{KERNEL_ARCH} CFI configs",
                f"either LLVM < {MIN_LLVM_VER_CFI} (using '{self._llvm_version}') or Linux < {LinuxVersion(6, 10, 0)} (have '{self.lsm.version}')",
            )

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self):
        for config_target in ['allmodconfig', 'allnoconfig', 'tinyconfig']:
            runner = ArmLLVMKernelRunner()
            runner.configs = [config_target]
            if config_target == 'allmodconfig':
                if disable_be(self.folders.source):
                    runner.configs.append('CONFIG_CPU_BIG_ENDIAN=n')
                if 'CONFIG_WERROR' in self.lsm.configs:
                    runner.configs.append('CONFIG_WERROR=n')
            self._runners.append(runner)

    def _add_distroconfig_runners(self):
        configs = [
            ('alpine', 'armv7'),
            ('archlinux', 'armv7'),
            ('debian', 'armmp'),
            ('fedora', 'armv7hl'),
            ('opensuse', 'armv7hl'),
        ]
        for distro, config_name in configs:
            runner = ArmLLVMKernelRunner()
            runner.bootable = distro != 'fedora'
            runner.configs = [Path(self.folders.configs, distro, f"{config_name}.config")]
            self._runners.append(runner)

    def run(self):
        for cross_compile in ['arm-linux-gnu-', 'arm-linux-gnueabihf-', f"{CLANG_TARGET}-"]:
            if shutil.which(f"{cross_compile}as"):
                break

        if '6f5b41a2f5a63' not in self.lsm.commits:
            self.make_vars['CROSS_COMPILE'] = cross_compile
        if self._llvm_version < MIN_IAS_LLVM_VER or self.lsm.version < MIN_IAS_LNX_VER:
            self.make_vars['LLVM_IAS'] = 0

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
