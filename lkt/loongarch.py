#!/usr/bin/env python3

from pathlib import Path
import subprocess

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion, QemuVersion

KERNEL_ARCH = 'loongarch'
CLANG_TARGET = 'loongarch64-linux-gnusf'
QEMU_ARCH = 'loongarch64'

# https://git.kernel.org/torvalds/l/65eea6b44a5dd332c50390fdaeda7e197802c484
MIN_LNX_VER = LinuxVersion(6, 5, 0)

# Building the kernel for LoongArch was not very well supported prior to LLVM
# 17.x
HARD_MIN_LLVM_VER = ClangVersion(17, 0, 0)

# QEMU older than 8.0.0 hits an assert in Loongson's EDK2 firmware:
# ASSERT [VirtNorFlashDxe] .../Platform/Loongson/LoongArchQemuPkg/Library/NorFlashQemuLib/NorFlashQemuLib.c(56): !(((INTN)(RETURN_STATUS)(FindNodeStatus)) < 0)
MIN_QEMU_VER = QemuVersion(8, 0, 0)


class LoongArchLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'vmlinuz.efi'
        self.qemu_arch = QEMU_ARCH


class LoongArchLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

        self._broken_configs = []
        self._qemu_version = QemuVersion(arch=QEMU_ARCH)

    def _add_defconfig_runners(self):
        runner = LoongArchLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['defconfig', *self._broken_configs]
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        runner = LoongArchLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['defconfig', *self._broken_configs, 'CONFIG_LTO_CLANG_THIN=y']
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

    def _add_otherconfig_runners(self):
        base_all_cfgs = [
            'allyesconfig' if 'CONFIG_MODULES=n' in self._broken_configs else 'allmodconfig',
            *self._broken_configs,
        ]
        # https://github.com/ClangBuiltLinux/linux/issues/1895
        if '2363088eba2ec' in self.lsm.commits and base_all_cfgs[0] == 'allyesconfig':
            base_all_cfgs.append('CONFIG_KCOV=n')
        if 'CONFIG_WERROR' in self.lsm.configs:
            base_all_cfgs.append('CONFIG_WERROR=n')

        runner = LoongArchLLVMKernelRunner()
        runner.configs = base_all_cfgs.copy()
        self._runners.append(runner)

        runner = LoongArchLLVMKernelRunner()
        runner.configs = [
            *base_all_cfgs,
            'CONFIG_FTRACE=n',
            'CONFIG_GCOV_KERNEL=n',
            'CONFIG_LTO_CLANG_THIN=y',
        ]
        self._runners.append(runner)

    def run(self):
        if (min_llvm_ver := self.lsm.get_min_llvm_ver(KERNEL_ARCH)) < HARD_MIN_LLVM_VER:
            min_llvm_ver = HARD_MIN_LLVM_VER
            reason = 'to build properly with LLVM=1'
        else:
            reason = 'because of scripts/min-tool-version.sh for supplied tree'

        if self._llvm_version < min_llvm_ver:
            return self._skip_all(
                f"LLVM < {min_llvm_ver}",
                f"LoongArch requires LLVM {min_llvm_ver} or newer {reason} (using '{self._llvm_version}')",
            )

        if '65eea6b44a5dd' not in self.lsm.commits:
            print_text = (
                f"LoongArch needs the following series from Linux {MIN_LNX_VER} to build properly:\n"
                '\n'
                '  * https://git.kernel.org/torvalds/l/65eea6b44a5dd332c50390fdaeda7e197802c484\n'
                '\n'
                f"Provide a kernel tree with Linux {MIN_LNX_VER}+ or one with this series to build LoongArch kernels."
            )
            return self._skip_all(f"missing 65eea6b44a5dd (from {MIN_LNX_VER})", print_text)

        loongarch_makefile_text = Path(self.lsm.folder,
                                       'arch/loongarch/Makefile').read_text(encoding='utf-8')
        if '--apply-dynamic-relocs' not in loongarch_makefile_text:
            self._broken_configs += [
                'CONFIG_CRASH_DUMP=n',  # selects RELOCATABLE
                'CONFIG_RELOCATABLE=n',  # ld.lld prepopulates GOT?
            ]

        # https://github.com/ClangBuiltLinux/linux/issues/1884
        clang_prog = 'int g __attribute((model("extreme")));'
        clang_cmd = [
            'clang',
            '--target=loongarch64',
            '-Werror=unknown-attributes',
            '-x',
            'c',
            '-fsyntax-only',
            '-',
        ]
        try:
            subprocess.run(clang_cmd, capture_output=True, check=True, input=clang_prog, text=True)
        except subprocess.CalledProcessError:
            self._broken_configs.append('CONFIG_MODULES=n')

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot and 'other' in self.targets:
            self._add_otherconfig_runners()

        if self._qemu_version < MIN_QEMU_VER:
            for runner in self._runners:
                if runner.bootable:
                    runner.bootable = False
                    runner.result[
                        'boot'] = f"skipped due to QEMU < {MIN_QEMU_VER} (found '{self._qemu_version}')"

        return super().run()
