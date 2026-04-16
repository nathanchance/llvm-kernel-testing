from pathlib import Path

import lkt.runner
import lkt.utils
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'x86_64'
CLANG_TARGET = 'x86_64-linux-gnu'
QEMU_ARCH = 'x86_64'

# KCFI sanitizer
# llvmorg-16-init-2791-gcff5bef948c9 (Wed Aug 24 22:41:38 2022 +0000)
# https://github.com/llvm/llvm-project/commit/cff5bef948c91e4919de8a5fb9765e0edc13f3de
MIN_LLVM_VER_CFI = ClangVersion(16, 0, 0)


class X8664LLVMKernelRunner(lkt.runner.LLVMKernelRunner):
    def __init__(self) -> None:
        super().__init__()

        self.boot_utils_arch = KERNEL_ARCH
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

        runner = X8664LLVMKernelRunner()
        runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
        runners.append(runner)

        # cfi: Switch to -fsanitize=kcfi
        # v6.0-rc4-5-g89245600941e (Mon Sep 26 10:13:13 2022 -0700)
        # https://git.kernel.org/linus/89245600941e4e0f87d77f60ee269b5e61ef4e49
        if (
            self._llvm_version >= MIN_LLVM_VER_CFI
            and '89245600941e4e0f87d77f60ee269b5e61ef4e49' in self.lsm.commits
        ):
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
            needs_gnu_objcopy = 'aaeed6ecc1253ce1463fa1aca0b70a4ccbc9fa75' not in self.lsm.commits
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
        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
