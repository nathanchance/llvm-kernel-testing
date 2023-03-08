#!/usr/bin/env python3

from pathlib import Path
import platform

import lkt.runner

KERNEL_ARCH = 'arm64'
CLANG_TARGET = 'aarch64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"


class Arm64LLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'Image.gz'


class Arm64LKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__()

        self.make_vars['ARCH'] = KERNEL_ARCH

        self._clang_target = CLANG_TARGET

    def _add_defconfig_runners(self):
        runners = []

        if Path(self.folders.source, 'arch/arm64/configs/virt.config').exists():
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['virtconfig']
            runners.append(runner)

        runner = Arm64LLVMKernelRunner()
        runner.configs = ['defconfig']
        runners.append(runner)

        if self._llvm_version >= (13, 0, 0):
            runner = Arm64LLVMKernelRunner()
            runner.boot_arch = 'arm64be'
            runner.configs = ['defconfig', 'CONFIG_CPU_BIG_ENDIAN=y']
            runners.append(runner)

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)

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

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self):
        runner = Arm64LLVMKernelRunner()
        runner.configs = ['allmodconfig']
        if 'd8e85e144bbe1' not in self.lsm.commits:
            runner.configs.append('CONFIG_CPU_BIG_ENDIAN=n')
        if 'CONFIG_WERROR' in self.lsm.configs:
            runner.configs.append('CONFIG_WERROR=n')
        self._runners.append(runner)

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = [
                'allmodconfig',
                'CONFIG_GCOV_KERNEL=n',
                'CONFIG_KASAN=n',
                'CONFIG_LTO_CLANG_THIN=y',
            ]
            if 'CONFIG_WERROR' in self.lsm.configs:
                runner.configs.append('CONFIG_WERROR=n')
            self._runners.append(runner)

        for config_target in ['allnoconfig', 'tinyconfig']:
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
                for sym in ['STM', 'TEST_MEMCAT_P']:
                    if lkt.utils.is_set(self.folders.source, runner.configs[0], sym):
                        runner.configs.append(f"CONFIG_{sym}=n")
            runner.lsm = self.lsm
            self._runners.append(runner)

    def run(self):
        cross_compile = '' if platform.machine() == 'aarch64' else CROSS_COMPILE
        if self.lsm.version >= (5, 10, 0):
            self.make_vars['LLVM_IAS'] = 1
            if '6f5b41a2f5a63' not in self.lsm.commits and cross_compile:
                self.make_vars['CROSS_COMPILE'] = cross_compile
        elif cross_compile:
            self.make_vars['CROSS_COMPILE'] = cross_compile

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
