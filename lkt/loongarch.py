#!/usr/bin/env python3

from pathlib import Path
import subprocess

import lkt.runner
import lkt.version

KERNEL_ARCH = 'loongarch'
CLANG_TARGET = 'loongarch64-linux-gnusf'
QEMU_ARCH = 'loongarch64'


class LoongArchLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'vmlinuz.efi'
        self.qemu_arch = QEMU_ARCH


class LoongArchLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__()

        self.make_vars['ARCH'] = KERNEL_ARCH
        self.make_vars['LLVM_IAS'] = 1

        self._broken_configs = []
        self._clang_target = CLANG_TARGET
        self._qemu_version = lkt.version.QemuVersion(arch=QEMU_ARCH)

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
            'allyesconfig' if 'CONFIG_MODULES' in self._broken_configs else 'allmodconfig',
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
        hard_min_llvm_ver = lkt.version.Version(17, 0, 0)
        if (min_llvm_ver := self.lsm.get_min_llvm_ver(KERNEL_ARCH)) < hard_min_llvm_ver:
            min_llvm_ver = hard_min_llvm_ver
            reason = 'to build properly with LLVM=1'
        else:
            reason = 'because of scripts/min-tool-version.sh for supplied tree'

        if self._llvm_version < min_llvm_ver:
            return self._skip(f"LLVM < {min_llvm_ver}",
                              f"LoongArch requires LLVM {min_llvm_ver} or newer {reason}")

        if '65eea6b44a5dd' not in self.lsm.commits:
            print_text = (
                'LoongArch needs the following series from Linux 6.5 to build properly:\n'
                '\n'
                '  * https://git.kernel.org/torvalds/l/65eea6b44a5dd332c50390fdaeda7e197802c484\n'
                '\n'
                'Provide a kernel tree with Linux 6.5+ or one with this series to build LoongArch kernels.'
            )
            return self._skip('missing 65eea6b44a5dd', print_text)

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

        # QEMU older than 8.0.0 hits an assert in Loongson's EDK2 firmware:
        # ASSERT [VirtNorFlashDxe] .../Platform/Loongson/LoongArchQemuPkg/Library/NorFlashQemuLib/NorFlashQemuLib.c(56): !(((INTN)(RETURN_STATUS)(FindNodeStatus)) < 0)
        if self._qemu_version < (min_qemu_ver := lkt.version.Version(8, 0, 0)):
            for runner in self._runners:
                if runner.bootable:
                    runner.bootable = False
                    runner.result[
                        'boot'] = f"skipped due to qemu older than {min_qemu_ver} (found {self._qemu_version})"

        return super().run()
