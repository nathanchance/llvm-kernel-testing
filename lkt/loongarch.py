#!/usr/bin/env python3

from pathlib import Path
import lkt.runner

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

        # See https://github.com/ClangBuiltLinux/linux/issues/1787#issuecomment-1603764274 for more info
        self._broken_configs = [
            'CONFIG_MODULES=n',  # need __attribute__((model("extreme"))) in clang
        ]
        self._clang_target = CLANG_TARGET
        self._qemu_version = lkt.utils.create_qemu_version(f"qemu-system-{QEMU_ARCH}")

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
        runner = LoongArchLLVMKernelRunner()
        # Eventually, allmodconfig instead
        runner.configs = ['allyesconfig', *self._broken_configs]
        # https://github.com/ClangBuiltLinux/linux/issues/1895
        if '2363088eba2ec' in self.lsm.commits:
            runner.configs.append('CONFIG_KCOV=n')
        if 'CONFIG_WERROR' in self.lsm.configs:
            runner.configs.append('CONFIG_WERROR=n')
        self._runners.append(runner)

        runner = LoongArchLLVMKernelRunner()
        runner.configs = [
            'allyesconfig',
            *self._broken_configs,
            'CONFIG_FTRACE=n',
            'CONFIG_GCOV_KERNEL=n',
            'CONFIG_LTO_CLANG_THIN=y',
        ]
        # https://github.com/ClangBuiltLinux/linux/issues/1895
        if '2363088eba2ec' in self.lsm.commits:
            runner.configs.append('CONFIG_KCOV=n')
        if 'CONFIG_WERROR' in self.lsm.configs:
            runner.configs.append('CONFIG_WERROR=n')
        self._runners.append(runner)

    def run(self):
        if self._llvm_version < (17, 0, 0):
            return self._skip(
                'LLVM < 17.0.0',
                'LoongArch requires LLVM 17.0.0 or newer to build properly with LLVM=1')

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

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot and 'other' in self.targets:
            self._add_otherconfig_runners()

        # QEMU older than 8.0.0 hits an assert in Loongson's EDK2 firmware:
        # ASSERT [VirtNorFlashDxe] .../Platform/Loongson/LoongArchQemuPkg/Library/NorFlashQemuLib/NorFlashQemuLib.c(56): !(((INTN)(RETURN_STATUS)(FindNodeStatus)) < 0)
        if self._qemu_version < (8, 0, 0):
            found_ver = '.'.join(str(val) for val in self._qemu_version)
            for runner in self._runners:
                if runner.bootable:
                    runner.bootable = False
                    runner.result[
                        'boot'] = f"skipped due to qemu older than 8.0.0 (found {found_ver})"

        return super().run()
