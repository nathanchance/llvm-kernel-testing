#!/usr/bin/env python3

from pathlib import Path

import lkt.runner

KERNEL_ARCH = 'i386'
CLANG_TARGET = 'i386-linux-gnu'
QEMU_ARCH = 'i386'


class I386LLVMKernelRunner(lkt.runner.LLVMKernelRunner):
    def __init__(self) -> None:
        super().__init__()

        self.boot_arch: str = 'x86'
        self.image_target: str = 'bzImage'
        self.qemu_arch: str = QEMU_ARCH


class I386LKTRunner(lkt.runner.LKTRunner):
    def __init__(self) -> None:
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self) -> None:
        runners = []

        runner = I386LLVMKernelRunner()
        runner.configs = ['defconfig']
        runners.append(runner)

        runner = I386LLVMKernelRunner()
        runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
        runners.append(runner)

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self) -> None:
        for config_target in ('allmodconfig', 'allnoconfig', 'tinyconfig'):
            runner = I386LLVMKernelRunner()
            runner.configs = [config_target]
            if config_target == 'allmodconfig':
                runner.configs += self._disable_broken_configs_with_fortify()
            self._runners.append(runner)

    def _add_distroconfig_runners(self) -> None:
        runner = I386LLVMKernelRunner()
        runner.configs = [Path(self.folders.configs, 'opensuse/i386.config')]
        runner.configs += self._disable_broken_configs_with_fortify()
        self._runners.append(runner)

        runner = I386LLVMKernelRunner()
        runner.configs = [Path(self.folders.configs, 'alpine/x86.config')]
        runner.configs += self._disable_broken_configs_with_fortify()
        self._runners.append(runner)

    # Fedora i686 config minus CONFIG_FORTIFY_SOURCE error in arch/x86/include/asm/checksum_32.h
    # https://github.com/ClangBuiltLinux/linux/issues/1442
    def _disable_broken_configs_with_fortify(self) -> list[str]:
        broken_configs = []

        sec_kconf_text = Path(self.folders.source, 'security/Kconfig').read_text(encoding='utf-8')
        fortify_broken = (
            'https://bugs.llvm.org/show_bug.cgi?id=50322' in sec_kconf_text
            or 'https://llvm.org/pr50322' in sec_kconf_text
            or 'https://github.com/llvm/llvm-project/issues/53645' in sec_kconf_text
        )

        if fortify_broken:
            # i386 "error: builtin functions must be directly called" in fs/bcachefs/replicas.c
            # https://github.com/ClangBuiltLinux/linux/issues/1932
            if 'CONFIG_BCACHEFS_FS' in self.lsm.configs:
                replicas_text = Path(self.folders.source, 'fs/bcachefs/replicas.c').read_text(
                    encoding='utf-8'
                )
                # bcachefs: Don't pass memcmp() as a pointer
                # v6.7-rc7-299-g0124f42da70c (Sun Jan 21 13:27:04 2024 -0500)
                # https://git.kernel.org/linus/0124f42da70c513dc371b73688663c54e5a9666f
                if 'bch2_memcmp' not in replicas_text:
                    broken_configs.append('CONFIG_BCACHEFS_FS=n')

            # Fedora i686 config minus CONFIG_FORTIFY_SOURCE error in arch/x86/include/asm/checksum_32.h
            # https://github.com/ClangBuiltLinux/linux/issues/1442
            if self._llvm_version < (15, 0, 0):
                broken_configs += [
                    'CONFIG_IP_NF_TARGET_SYNPROXY=n',
                    'CONFIG_IP6_NF_TARGET_SYNPROXY=n',
                    'CONFIG_NFT_SYNPROXY=n',
                ]

        return broken_configs

    def run(self) -> list[lkt.runner.Result]:
        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
