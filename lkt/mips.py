import shutil

import lkt.runner

KERNEL_ARCH = 'mips'
CLANG_TARGET = 'mips-linux-gnu'


class MipsLLVMKernelRunner(lkt.runner.LLVMKernelRunner):
    def __init__(self) -> None:
        super().__init__()

        self.boot_utils_arch: str = 'mipsel'
        self.image_target: str = 'vmlinux'
        self.qemu_arch: str = 'mipsel'


class MipsLKTRunner(lkt.runner.LKTRunner):
    def __init__(self) -> None:
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

        for cross_compile in ('mips64-linux-gnu-', f"{CLANG_TARGET}-", 'mipsel-linux-gnu-'):
            if shutil.which(f"{cross_compile}as"):
                self._cross_compile = cross_compile

        self._be_vars: lkt.runner.MakeVars = {}

    def _add_defconfig_runners(self) -> None:
        runners = []

        extra_configs: list[str] = []
        if 'c47c7ab9b53635860c6b48736efdd22822d726d7' not in self.lsm.commits:
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
        runner.boot_utils_arch = 'mips'
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

        generic_cfgs: list[str] = ['32r1', '32r1el', '32r2', '32r2el']
        if self._llvm_version >= (12, 0, 0):
            generic_cfgs += ['32r6', '32r6el']
        for generic_cfg in generic_cfgs:
            runner = MipsLLVMKernelRunner()
            if '32r1' in generic_cfg:
                runner.make_vars['CROSS_COMPILE'] = self._cross_compile
                runner.override_make_vars['LLVM_IAS'] = '0'
            if 'el' not in generic_cfg:
                runner.make_vars.update(self._be_vars)
            runner.configs = [f"{generic_cfg}_defconfig"]
            self._runners.append(runner)

    def _add_otherconfig_runners(self) -> None:
        for cfg_target in ('allnoconfig', 'tinyconfig'):
            runner = MipsLLVMKernelRunner()
            runner.configs = [cfg_target]
            runner.make_vars.update(self._be_vars)
            self._runners.append(runner)

    def run(self) -> list[lkt.runner.Result]:
        if self._llvm_version < (13, 0, 0):
            self._be_vars['LD'] = f"{self._cross_compile}ld"

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot and 'other' in self.targets:
            self._add_otherconfig_runners()

        return super().run()
