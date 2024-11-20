#!/usr/bin/env python3

from pathlib import Path
import platform

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'arm64'
CLANG_TARGET = 'aarch64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 'aarch64'

# https://github.com/ClangBuiltLinux/linux/issues/1106
MIN_IAS_LNX_VER = LinuxVersion(5, 9, 0)


class Arm64LLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'Image.gz'
        self.qemu_arch = QEMU_ARCH


class Arm64LKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self):
        runners = []

        if Path(self.folders.source, 'arch/arm64/configs/virt.config').exists():
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['virtconfig']
            runners.append(runner)

        runner = Arm64LLVMKernelRunner()
        runner.configs = ['defconfig']
        runners.append(runner)

        # LLVM 15: https://git.kernel.org/linus/146a15b873353f8ac28dc281c139ff611a3c4848
        # LLVM 13: https://git.kernel.org/linus/e9c6deee00e9197e75cd6aa0d265d3d45bd7cc28
        min_be_llvm_ver = ClangVersion(15 if '146a15b873353' in self.lsm.commits else 13, 0, 0)
        if self._llvm_version >= min_be_llvm_ver:
            runner = Arm64LLVMKernelRunner()
            runner.boot_arch = 'arm64be'
            runner.configs = ['defconfig', 'CONFIG_CPU_BIG_ENDIAN=y']
            runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} big endian defconfig",
                f"LLVM < {min_be_llvm_ver} (using '{self._llvm_version}')",
            )

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)
        else:
            # https://git.kernel.org/linus/112b6a8e038d793d016e330f53acb9383ac504b3
            self._skip_one(
                f"{KERNEL_ARCH} LTO builds",
                f"Linux < {LinuxVersion(5, 12, 0)} (have '{self.lsm.version}')",
            )

        if 'CONFIG_CFI_CLANG' in self.lsm.configs:
            if '89245600941e4' in self.lsm.commits:
                runner = Arm64LLVMKernelRunner()
                runner.configs = [
                    'defconfig',
                    'CONFIG_CFI_CLANG=y',
                    'CONFIG_SHADOW_CALL_STACK=y',
                ]
                runners.append(runner)

            runner = Arm64LLVMKernelRunner()
            runner.configs = [
                'defconfig',
                'CONFIG_CFI_CLANG=y',
                'CONFIG_LTO_CLANG_THIN=y',
                'CONFIG_SHADOW_CALL_STACK=y',
            ]
            runners.append(runner)
        elif 'CONFIG_SHADOW_CALL_STACK' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_SHADOW_CALL_STACK=y']
            runners.append(runner)
        else:
            # https://git.kernel.org/linus/5287569a790d2546a06db07e391bf84b8bd6cf51
            self._skip_one(
                f"{KERNEL_ARCH} CFI/SCS builds",
                f"Linux < {LinuxVersion(5, 8, 0)} (have '{self.lsm.version}')",
            )

        if Path(self.folders.source, 'kernel/configs/hardening.config').exists():
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'hardening.config']
            runners.append(runner)

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self):
        runner = Arm64LLVMKernelRunner()
        runner.configs = ['allmodconfig']
        if 'd8e85e144bbe1' not in self.lsm.commits:
            runner.configs.append('CONFIG_CPU_BIG_ENDIAN=n')
        self._runners.append(runner)

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = [
                'allmodconfig',
                'CONFIG_GCOV_KERNEL=n',
                'CONFIG_KASAN=n',
                'CONFIG_LTO_CLANG_THIN=y',
            ]
            self._runners.append(runner)

        for config_target in ('allnoconfig', 'tinyconfig'):
            runner = Arm64LLVMKernelRunner()
            runner.configs = [config_target]
            self._runners.append(runner)

    def _add_distroconfig_runners(self):
        configs = [
            ('alpine', 'aarch64'),
            ('archlinux', 'aarch64'),
            ('debian', KERNEL_ARCH),
            ('fedora', 'aarch64'),
            ('opensuse', KERNEL_ARCH),
        ]
        for distro, config_name in configs:
            runner = Arm64LLVMKernelRunner()
            runner.bootable = True
            runner.configs = [Path(self.folders.configs, distro, f"{config_name}.config")]
            if distro == 'fedora' and self.lsm.version < (5, 7, 0):
                for sym, val in (('STM', 'y'), ('TEST_MEMCAT_P', 'n')):
                    if lkt.utils.is_set(self.folders.source, runner.configs[0], sym):
                        runner.configs.append(f"CONFIG_{sym}={val}")
            self._runners.append(runner)

    def run(self):
        cross_compile = '' if platform.machine() == 'aarch64' else CROSS_COMPILE
        if '6f5b41a2f5a63' not in self.lsm.commits and cross_compile:
            self.make_vars['CROSS_COMPILE'] = cross_compile
        if self.lsm.version < MIN_IAS_LNX_VER:
            self.make_vars['LLVM_IAS'] = 0

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
