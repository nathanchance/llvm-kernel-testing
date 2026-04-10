#!/usr/bin/env python3

from pathlib import Path
import platform

import lkt.runner
import lkt.utils
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'x86_64'
CLANG_TARGET = 'x86_64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 'x86_64'

# KCFI sanitizer
# llvmorg-16-init-2791-gcff5bef948c9 (Wed Aug 24 22:41:38 2022 +0000)
# https://github.com/llvm/llvm-project/commit/cff5bef948c91e4919de8a5fb9765e0edc13f3de
MIN_LLVM_VER_CFI = ClangVersion(16, 0, 0)

# changed binding to STB_GLOBAL
# https://github.com/ClangBuiltLinux/linux/issues/1190
# x86/lib: Change .weak to SYM_FUNC_START_WEAK for arch/x86/lib/mem*_64.S
# v5.10-rc2-1-g4d6ffa27b8e5 (Wed Nov 4 12:30:20 2020 +0100)
# https://git.kernel.org/linus/4d6ffa27b8e5116c0abb318790fd01d4e12d75e6
MIN_IAS_LNX_VER = LinuxVersion(5, 10, 0)


class X8664LLVMKernelRunner(lkt.runner.LLVMKernelRunner):
    def __init__(self) -> None:
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'bzImage'
        self.qemu_arch = QEMU_ARCH


class X8664LKTRunner(lkt.runner.LKTRunner):
    def __init__(self) -> None:
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self) -> None:
        runners: list[X8664LLVMKernelRunner] = []

        runner = X8664LLVMKernelRunner()
        runner.configs = ['defconfig']
        runners.append(runner)

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = X8664LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)
        else:
            # x86, build: allow LTO to be selected
            # v5.11-rc2-27-gb33fff07e3e3 (Tue Feb 23 12:46:58 2021 -0800)
            # https://git.kernel.org/linus/b33fff07e3e3817d94dbec7bf2040070ecd96d16
            self._skip_one(
                f"{KERNEL_ARCH} LTO builds",
                f"Linux < {LinuxVersion(5, 12, 0)} (have '{self.lsm.version}')",
            )

        # cfi: Switch to -fsanitize=kcfi
        # v6.0-rc4-5-g89245600941e (Mon Sep 26 10:13:13 2022 -0700)
        # https://git.kernel.org/linus/89245600941e4e0f87d77f60ee269b5e61ef4e49
        if self._llvm_version >= MIN_LLVM_VER_CFI and '89245600941e4' in self.lsm.commits:
            cfi_y_config = self.lsm.get_cfi_y_config()

            runner = X8664LLVMKernelRunner()
            runner.configs = ['defconfig', cfi_y_config]
            runners.append(runner)

            runner = X8664LLVMKernelRunner()
            runner.configs = ['defconfig', cfi_y_config, 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)
        else:
            # x86/Kconfig: Do not allow CONFIG_X86_X32_ABI=y with llvm-objcopy
            # v5.17-rc8-55-gaaeed6ecc125 (Tue Mar 15 10:32:48 2022 +0100)
            # https://git.kernel.org/linus/aaeed6ecc1253ce1463fa1aca0b70a4ccbc9fa75
            self._skip_one(
                f"{KERNEL_ARCH} CFI configs",
                f"either LLVM < {MIN_LLVM_VER_CFI} (using '{self._llvm_version}') or Linux < {LinuxVersion(6, 1, 0)} (have '{self.lsm.version}')",
            )

        if Path(self.folders.source, 'kernel/configs/hardening.config').exists():
            runner = X8664LLVMKernelRunner()
            runner.configs = ['defconfig', 'hardening.config']
            runners.append(runner)

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self) -> None:
        runner = X8664LLVMKernelRunner()
        runner.configs = ['allmodconfig']
        # ERROR: "__memcat_p" [drivers/hwtracing/stm/stm_core.ko] undefined!
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
            self._runners.append(runner)

    def _add_distroconfig_runners(self) -> None:
        configs: list[tuple[str, str]] = [
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
            # x86/Kconfig: Do not allow CONFIG_X86_X32_ABI=y with llvm-objcopy
            # v5.17-rc8-55-gaaeed6ecc125 (Tue Mar 15 10:32:48 2022 +0100)
            # https://git.kernel.org/linus/aaeed6ecc1253ce1463fa1aca0b70a4ccbc9fa75
            needs_gnu_objcopy = 'aaeed6ecc1253' not in self.lsm.commits
            if has_x32 and needs_gnu_objcopy:
                if 'CROSS_COMPILE' in self.make_vars:
                    runner.make_vars['OBJCOPY'] = f"{self.make_vars['CROSS_COMPILE']}objcopy"
                else:
                    runner.make_vars['OBJCOPY'] = 'objcopy'
            if self.lsm.version < (5, 7, 0):
                for sym in ('STM', 'TEST_MEMCAT_P'):
                    if lkt.utils.is_set(self.folders.source, runner.configs[0], sym):
                        runner.configs.append(f"CONFIG_{sym}=n")
            self._runners.append(runner)

    def run(self) -> list[lkt.runner.Result]:
        cross_compile: str = ''
        if platform.machine() != KERNEL_ARCH:
            # x86/boot: Add $(CLANG_FLAGS) to compressed KBUILD_CFLAGS
            # v5.12-rc4-2-gd5cbd80e302d (Fri Mar 26 11:32:55 2021 +0100)
            # https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f
            if 'd5cbd80e302df' not in self.lsm.commits:
                return self._skip_all(
                    f"missing d5cbd80e302d (from {LinuxVersion(5, 13, 0)}) on a non-x86_64 host",
                    f"Cannot cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f (from {LinuxVersion(5, 13, 0)})",
                )

            cross_compile = CROSS_COMPILE

        # Makefile: move initial clang flag handling into scripts/Makefile.clang
        # v5.14-rc5-5-g6f5b41a2f5a6 (Tue Aug 10 09:13:25 2021 +0900)
        # https://git.kernel.org/linus/6f5b41a2f5a6314614e286274eb8e985248aac60
        if '6f5b41a2f5a63' not in self.lsm.commits and cross_compile:
            self.make_vars['CROSS_COMPILE'] = cross_compile
        if self.lsm.version < MIN_IAS_LNX_VER:
            self.make_vars['LLVM_IAS'] = '0'

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
