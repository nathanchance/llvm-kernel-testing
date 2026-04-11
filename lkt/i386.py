#!/usr/bin/env python3

from pathlib import Path

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

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

        # x86, lto: Enable Clang LTO for 32-bit as well
        # v5.13-rc2-3-g583bfd484bcc (Mon Jun 14 09:12:41 2021 -0700)
        # https://git.kernel.org/linus/583bfd484bcc85e9371e7205fa9e827c18ae34fb
        if '583bfd484bcc8' in self.lsm.commits:
            runner = I386LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} LTO builds",
                f"Linux < {LinuxVersion(5, 14, 0)} (have '{self.lsm.version}')",
            )

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
        if (
            self._llvm_version >= (min_llvm_ver := ClangVersion(12, 0, 0))
            # x86/build: Treat R_386_PLT32 relocation as R_386_PC32
            # v5.11-rc1-3-gbb73d07148c4 (Thu Jan 28 12:24:06 2021 +0100)
            # https://git.kernel.org/linus/bb73d07148c405c293e576b40af37737faf23a6a
            and 'bb73d07148c40' not in self.lsm.commits
        ):
            return self._skip_all(
                f"missing bb73d07148c4 (from {LinuxVersion(5, 12, 0)}) with LLVM > {min_llvm_ver} (using '{self._llvm_version}')",
                f"x86 kernels do not build properly with LLVM {min_llvm_ver}+ without R_386_PLT32 handling: https://github.com/ClangBuiltLinux/linux/issues/1210",
            )

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
