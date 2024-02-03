#!/usr/bin/env python3

import shutil

import lkt.runner
from lkt.version import LinuxVersion

KERNEL_ARCH = 'mips'
CLANG_TARGET = 'mips-linux-gnu'

# https://github.com/ClangBuiltLinux/linux/issues/763
# Technically, that issue was resolved in 5.14 but we check 5.15 to allow
# setting CROSS_COMPILE and LLVM_IAS=0 in the same block (as CROSS_COMPILE is
# not required with the integrated assembler starting in 5.15)
MIN_IAS_LNX_VER = LinuxVersion(5, 15, 0)


class MipsLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = 'mipsel'
        self.image_target = 'vmlinux'
        self.qemu_arch = 'mipsel'


class MipsLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

        for cross_compile in ['mips64-linux-gnu-', f"{CLANG_TARGET}-", 'mipsel-linux-gnu-']:
            if shutil.which(f"{cross_compile}as"):
                self._cross_compile = cross_compile

        self._be_vars = {}

    def _add_defconfig_runners(self):
        runners = []

        extra_configs = []
        if 'c47c7ab9b5363' not in self.lsm.commits:
            extra_configs.append('CONFIG_BLK_DEV_INITRD=y')

        runner = MipsLLVMKernelRunner()
        runner.configs = ['malta_defconfig', *extra_configs]
        runners.append(runner)

        runner = MipsLLVMKernelRunner()
        runner.configs = [
            'malta_defconfig',
            'CONFIG_RELOCATABLE=y',
            'CONFIG_RELOCATION_TABLE_SIZE=0x00200000',
            'CONFIG_RANDOMIZE_BASE=y',
            *extra_configs,
        ]
        runners.append(runner)

        runner = MipsLLVMKernelRunner()
        runner.boot_arch = 'mips'
        runner.configs = [
            'malta_defconfig',
            'CONFIG_CPU_BIG_ENDIAN=y',
            *extra_configs,
        ]
        runner.make_vars.update(self._be_vars)
        runner.qemu_arch = 'mips'
        runners.append(runner)

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

        if self.only_test_boot:
            return

        generic_cfgs = ['32r1', '32r1el', '32r2', '32r2el']
        if self._llvm_version >= (12, 0, 0):
            generic_cfgs += ['32r6', '32r6el']
        for generic_cfg in generic_cfgs:
            runner = MipsLLVMKernelRunner()
            if '32r1' in generic_cfg:
                runner.make_vars['CROSS_COMPILE'] = self._cross_compile
                runner.override_make_vars['LLVM_IAS'] = 0
            if 'el' not in generic_cfg:
                runner.make_vars.update(self._be_vars)
            runner.configs = [f"{generic_cfg}_defconfig"]
            self._runners.append(runner)

    def _add_otherconfig_runners(self):
        for cfg_target in ['allnoconfig', 'tinyconfig']:
            runner = MipsLLVMKernelRunner()
            runner.configs = [cfg_target]
            runner.make_vars.update(self._be_vars)
            self._runners.append(runner)

    def run(self):
        if self.lsm.version < MIN_IAS_LNX_VER:
            self.make_vars['CROSS_COMPILE'] = self._cross_compile
            self.make_vars['LLVM_IAS'] = 0

        if 'e91946d6d93ef' in self.lsm.commits and self._llvm_version < (13, 0, 0):
            self._be_vars['LD'] = f"{self._cross_compile}ld"

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot and 'other' in self.targets:
            self._add_otherconfig_runners()

        return super().run()
