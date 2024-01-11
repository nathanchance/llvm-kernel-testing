#!/usr/bin/env python3

from pathlib import Path
import platform

import lkt.runner

KERNEL_ARCH = 'i386'
CLANG_TARGET = 'i386-linux-gnu'
CROSS_COMPILE = 'x86_64-linux-gnu-'
QEMU_ARCH = 'i386'


class I386LLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = 'x86'
        self.image_target = 'bzImage'
        self.qemu_arch = QEMU_ARCH


class I386LKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__()

        self.make_vars['ARCH'] = KERNEL_ARCH
        self.make_vars['LLVM_IAS'] = 1

        self._clang_target = CLANG_TARGET

    def _add_defconfig_runners(self):
        runners = []

        runner = I386LLVMKernelRunner()
        runner.configs = ['defconfig']
        runners.append(runner)

        if '583bfd484bcc8' in self.lsm.commits:
            runner = I386LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self):
        for config_target in ['allmodconfig', 'allnoconfig', 'tinyconfig']:
            runner = I386LLVMKernelRunner()
            runner.configs = [config_target]
            if config_target == 'allmodconfig':
                runner.configs += self._disable_broken_configs_with_fortify()
                if 'CONFIG_WERROR' in self.lsm.configs:
                    runner.configs.append('CONFIG_WERROR=n')
            self._runners.append(runner)

    def _add_distroconfig_runners(self):
        for distro in ['debian', 'opensuse']:
            runner = I386LLVMKernelRunner()
            runner.configs = [Path(self.folders.configs, distro, "i386.config")]
            runner.configs += self._disable_broken_configs_with_fortify()
            runner.lsm = self.lsm
            self._runners.append(runner)

    # https://github.com/ClangBuiltLinux/linux/issues/1442
    def _disable_broken_configs_with_fortify(self):
        broken_configs = []

        sec_kconf_text = Path(self.folders.source, 'security/Kconfig').read_text(encoding='utf-8')
        fortify_broken = 'https://bugs.llvm.org/show_bug.cgi?id=50322' in sec_kconf_text or \
                         'https://llvm.org/pr50322' in sec_kconf_text or \
                         'https://github.com/llvm/llvm-project/issues/53645' in sec_kconf_text

        if fortify_broken:
            # https://github.com/ClangBuiltLinux/linux/issues/1932
            if 'CONFIG_BCACHEFS_FS' in self.lsm.configs:
                broken_configs.append('CONFIG_BCACHEFS_FS=n')

            # https://github.com/ClangBuiltLinux/linux/issues/1442
            if self._llvm_version < (15, 0, 0):
                broken_configs += [
                    'CONFIG_IP_NF_TARGET_SYNPROXY=n',
                    'CONFIG_IP6_NF_TARGET_SYNPROXY=n',
                    'CONFIG_NFT_SYNPROXY=n',
                ]

        return broken_configs

    def run(self):
        if self.lsm.version < (5, 9, 0):
            return self._skip(
                'missing 158807de5822',
                'i386 kernels do not build properly prior to Linux 5.9: https://github.com/ClangBuiltLinux/linux/issues/194',
            )
        if self._llvm_version >= (12, 0, 0) and 'bb73d07148c40' not in self.lsm.commits:
            return self._skip(
                'missing bb73d07148c4 with LLVM > 12.0.0',
                'x86 kernels do not build properly with LLVM 12.0.0+ without R_386_PLT32 handling: https://github.com/ClangBuiltLinux/linux/issues/1210',
            )

        if platform.machine() != 'x86_64':
            if 'd5cbd80e302df' not in self.lsm.commits:
                return self._skip(
                    'missing d5cbd80e302d on a non-x86_64 host',
                    'Cannot cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f',
                )
            if '6f5b41a2f5a63' not in self.lsm.commits:
                self.make_vars['CROSS_COMPILE'] = CROSS_COMPILE

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
