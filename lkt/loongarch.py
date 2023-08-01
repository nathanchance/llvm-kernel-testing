#!/usr/bin/env python3

import lkt.runner

KERNEL_ARCH = 'loongarch'
CLANG_TARGET = 'loongarch64-linux-gnusf'
QEMU_ARCH = 'loongarch64'

# See https://github.com/ClangBuiltLinux/linux/issues/1787#issuecomment-1603764274 for more info
BROKEN_CONFIGS = [
    'CONFIG_MODULES=n',  # need __attribute__((model("extreme"))) in clang
    'CONFIG_CRASH_DUMP=n',  # selects RELOCATABLE
    'CONFIG_RELOCATABLE=n',  # ld.lld prepopulates GOT?
]


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

        self._clang_target = CLANG_TARGET

    def _add_defconfig_runners(self):
        runner = LoongArchLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['defconfig', *BROKEN_CONFIGS]
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        runner = LoongArchLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['defconfig', *BROKEN_CONFIGS, 'CONFIG_LTO_CLANG_THIN=y']
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

    def _add_otherconfig_runners(self):
        runner = LoongArchLLVMKernelRunner()
        # Eventually, allmodconfig instead
        runner.configs = ['allyesconfig', *BROKEN_CONFIGS]
        if 'CONFIG_WERROR' in self.lsm.configs:
            runner.configs.append('CONFIG_WERROR=n')
        self._runners.append(runner)

        runner = LoongArchLLVMKernelRunner()
        runner.configs = [
            'allyesconfig',
            *BROKEN_CONFIGS,
            'CONFIG_FTRACE=n',
            'CONFIG_GCOV_KERNEL=n',
            'CONFIG_LTO_CLANG_THIN=y',
        ]
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

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot and 'other' in self.targets:
            self._add_otherconfig_runners()

        return super().run()
