#!/usr/bin/env python3

from pathlib import Path
import platform

import lkt.runner
import lkt.utils
from lkt.version import ClangVersion

KERNEL_ARCH = 'x86_64'
CLANG_TARGET = 'x86_64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 'x86_64'

# https://github.com/llvm/llvm-project/commit/cff5bef948c91e4919de8a5fb9765e0edc13f3de
MIN_LLVM_VER_CFI = ClangVersion(16, 0, 0)


class X8664LLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'bzImage'
        self.qemu_arch = QEMU_ARCH


class X8664LKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__()

        self.make_vars['ARCH'] = KERNEL_ARCH

        self._clang_target = CLANG_TARGET

    def _add_defconfig_runners(self):
        runners = []

        runner = X8664LLVMKernelRunner()
        runner.configs = ['defconfig']
        runners.append(runner)

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = X8664LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)

        if self._llvm_version >= MIN_LLVM_VER_CFI and '89245600941e4' in self.lsm.commits:
            runner = X8664LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_CFI_CLANG=y']
            runners.append(runner)

            runner = X8664LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_CFI_CLANG=y', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)
        else:
            self._results.append({
                'name':
                f"{KERNEL_ARCH} CFI configs",
                'build':
                'skipped',
                'reason':
                f"either LLVM < {MIN_LLVM_VER_CFI} ('{self._llvm_version}') or lack of support in Linux",
            })

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self):
        runner = X8664LLVMKernelRunner()
        runner.configs = ['allmodconfig']
        if 'CONFIG_WERROR' in self.lsm.configs:
            runner.configs.append('CONFIG_WERROR=n')
        # https://github.com/ClangBuiltLinux/linux/issues/515
        if self.lsm.version < (5, 7, 0):
            runner.configs += ['CONFIG_STM=n', 'CONFIG_TEST_MEMCAT_P=n']
        self._runners.append(runner)

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = X8664LLVMKernelRunner()
            runner.configs = [
                'allmodconfig',
                'CONFIG_GCOV_KERNEL=n',
                'CONFIG_KASAN=n',
                'CONFIG_LTO_CLANG_THIN=y',
            ]
            if 'CONFIG_WERROR' in self.lsm.configs:
                runner.configs.append('CONFIG_WERROR=n')
            self._runners.append(runner)

    def _add_distroconfig_runners(self):
        configs = [
            ('alpine', KERNEL_ARCH),
            ('archlinux', KERNEL_ARCH),
            ('debian', 'amd64'),
            ('fedora', KERNEL_ARCH),
            ('opensuse', KERNEL_ARCH),
        ]
        for distro, config_name in configs:
            runner = X8664LLVMKernelRunner()
            runner.bootable = True
            runner.configs = [Path(self.folders.configs, distro, f"{config_name}.config")]
            has_x32 = lkt.utils.is_set(self.folders.source, runner.configs[0], 'X86_X32_ABI')
            needs_gnu_objcopy = 'aaeed6ecc1253' not in self.lsm.commits
            if has_x32 and needs_gnu_objcopy:
                if 'CROSS_COMPILE' in self.make_vars:
                    runner.make_vars['OBJCOPY'] = f"{self.make_vars['CROSS_COMPILE']}objcopy"
                else:
                    runner.make_vars['OBJCOPY'] = 'objcopy'
            if self.lsm.version < (5, 7, 0):
                for sym in ['STM', 'TEST_MEMCAT_P']:
                    if lkt.utils.is_set(self.folders.source, runner.configs[0], sym):
                        runner.configs.append(f"CONFIG_{sym}=n")
            runner.lsm = self.lsm
            self._runners.append(runner)

    def run(self):
        cross_compile = None
        if platform.machine() != KERNEL_ARCH:
            if 'd5cbd80e302df' not in self.lsm.commits:
                return self._skip_all(
                    'missing d5cbd80e302d on a non-x86_64 host',
                    'Cannot cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f',
                )

            cross_compile = CROSS_COMPILE

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
