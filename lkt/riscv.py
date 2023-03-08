#!/usr/bin/env python3

from pathlib import Path

import lkt.runner

KERNEL_ARCH = 'riscv'
CLANG_TARGET = 'riscv64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"


class RISCVLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = 'riscv'
        self.image_target = 'Image'


class RISCVLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__()

        self.make_vars['ARCH'] = KERNEL_ARCH

        self._clang_target = CLANG_TARGET

    def _add_defconfig_runners(self):
        runner = RISCVLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['defconfig']
        if self._llvm_version < (13, 0, 0):
            text = Path(self.folders.source, 'arch/riscv/Kconfig').read_text(encoding='utf-8')
            if 'config EFI' in text:
                runner.configs.append('CONFIG_EFI=n')
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

    def _add_otherconfig_runners(self):
        runner = RISCVLLVMKernelRunner()
        runner.configs = ['allmodconfig']
        if 'CONFIG_WERROR' in self.lsm.configs:
            runner.configs.append('CONFIG_WERROR=n')
        self._runners.append(runner)

    def _add_distroconfig_runners(self):
        configs = [
            ('alpine', 'riscv64'),
            ('opensuse', 'riscv64'),
        ]
        for distro, config_name in configs:
            runner = RISCVLLVMKernelRunner()
            runner.bootable = 'f2928e224d85e' in self.lsm.commits
            if not runner.bootable:
                runner.result['boot'] = 'skipped due to lack of f2928e224d85e'
            runner.configs = [Path(self.folders.configs, distro, f"{config_name}.config")]
            runner.lsm = self.lsm
            self._runners.append(runner)

    def run(self):
        if self.lsm.version < (5, 7, 0):
            print_text = (
                'RISC-V needs the following fixes from Linux 5.7 to build properly:\n'
                '\n'
                '        * https://git.kernel.org/linus/52e7c52d2ded5908e6a4f8a7248e5fa6e0d6809a\n'
                '        * https://git.kernel.org/linus/fdff9911f266951b14b20e25557278b5b3f0d90d\n'
                '        * https://git.kernel.org/linus/abc71bf0a70311ab294f97a7f16e8de03718c05a\n'
                '\n'
                'Provide a kernel tree with Linux 5.7 or newer to build RISC-V kernels.')
            return self._skip('missing 52e7c52d2ded, fdff9911f266, and/or abc71bf0a703', print_text)

        if self._llvm_version >= (13, 0, 0):
            self.make_vars['LLVM_IAS'] = 1
            if '6f5b41a2f5a63' not in self.lsm.commits:
                self.make_vars['CROSS_COMPILE'] = CROSS_COMPILE
        else:
            self.make_vars['CROSS_COMPILE'] = CROSS_COMPILE

        if (self._llvm_version < (13, 0, 0) or 'ec3a5cb61146c' not in self.lsm.commits
                or self.lsm.version <= (5, 10, 999)):
            self.make_vars['LD'] = f"{CROSS_COMPILE}ld"

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if (not self.only_test_boot and self.lsm.version > (5, 8, 0)
                and 'ec3a5cb61146c' in self.lsm.commits):
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
