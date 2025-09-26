#!/usr/bin/env python3

from pathlib import Path
import platform

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'arm64'
CLANG_TARGET = 'aarch64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 'aarch64'

# https://github.com/ClangBuiltLinux/linux/issues/1106
MIN_IAS_LNX_VER = LinuxVersion(5, 9, 0)


def can_build_arm64_big_endian(lsm, llvm_version):
    arm64_kconfig_txt = Path(lsm.folder, 'arch/arm64/Kconfig').read_text(encoding='utf-8')

    # Detect if big endian support is present and working in the kernel
    # https://git.kernel.org/arm64/c/1cf89b6bf660c2e9fa137b3e160c7b1001937a78
    # Look for three states:
    # 1. That commit as it exists in the arm64 tree
    # 2. That commit with https://lore.kernel.org/aNU-sG84vqPj7p7G@sirena.org.uk/ addressed
    # 3. A future where CONFIG_CPU_BIG_ENDIAN does not even exist
    state_one = 'config CPU_BIG_ENDIAN\n\tbool "Build big-endian kernel"\n\t# https://github.com/llvm/llvm-project/commit/1379b150991f70a5782e9a143c2ba5308da1161c\n\tdepends on (AS_IS_GNU || AS_VERSION >= 150000) && BROKEN\n\thelp'
    state_two = 'config CPU_BIG_ENDIAN\n\tbool "Build big-endian kernel"\n\tdepends on BROKEN\n\thelp'
    be_broken = state_one in arm64_kconfig_txt or state_two in arm64_kconfig_txt
    be_exists = 'config CPU_BIG_ENDIAN' in arm64_kconfig_txt

    # LLVM 15: https://git.kernel.org/linus/146a15b873353f8ac28dc281c139ff611a3c4848
    return llvm_version >= ClangVersion(15, 0, 0) and not be_broken and be_exists


class Arm64LLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'Image.gz'
        self.qemu_arch = QEMU_ARCH


class Arm64LKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self):
        runners = []

        if Path(self.folders.source, 'arch/arm64/configs/virt.config').exists():
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['virtconfig']
            runners.append(runner)

        runner = Arm64LLVMKernelRunner()
        runner.configs = ['defconfig']
        runners.append(runner)

        if can_build_arm64_big_endian(self.lsm, self._llvm_version):
            runner = Arm64LLVMKernelRunner()
            runner.boot_arch = 'arm64be'
            runner.configs = ['defconfig', 'CONFIG_CPU_BIG_ENDIAN=y']
            runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} big endian defconfig",
                f"LLVM < 15.0.0 (using '{self._llvm_version}') or no big endian support in Linux",
            )

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)
        else:
            # https://git.kernel.org/linus/112b6a8e038d793d016e330f53acb9383ac504b3
            self._skip_one(
                f"{KERNEL_ARCH} LTO builds",
                f"Linux < {LinuxVersion(5, 12, 0)} (have '{self.lsm.version}')",
            )

        if self.lsm.arch_supports_kcfi(KERNEL_ARCH):
            cfi_y_config = self.lsm.get_cfi_y_config()
            if '89245600941e4' in self.lsm.commits:
                runner = Arm64LLVMKernelRunner()
                runner.configs = [
                    'defconfig',
                    cfi_y_config,
                    'CONFIG_SHADOW_CALL_STACK=y',
                ]
                runners.append(runner)

            runner = Arm64LLVMKernelRunner()
            runner.configs = [
                'defconfig',
                cfi_y_config,
                'CONFIG_LTO_CLANG_THIN=y',
                'CONFIG_SHADOW_CALL_STACK=y',
            ]
            runners.append(runner)
        elif 'CONFIG_SHADOW_CALL_STACK' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_SHADOW_CALL_STACK=y']
            runners.append(runner)
        else:
            # https://git.kernel.org/linus/5287569a790d2546a06db07e391bf84b8bd6cf51
            self._skip_one(
                f"{KERNEL_ARCH} CFI/SCS builds",
                f"Linux < {LinuxVersion(5, 8, 0)} (have '{self.lsm.version}')",
            )

        if Path(self.folders.source, 'kernel/configs/hardening.config').exists():
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'hardening.config']
            runners.append(runner)

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self):
        runner = Arm64LLVMKernelRunner()
        runner.configs = ['allmodconfig']
        if 'd8e85e144bbe1' not in self.lsm.commits:
            runner.configs.append('CONFIG_CPU_BIG_ENDIAN=n')
        self._runners.append(runner)

        if 'CONFIG_LTO_CLANG_THIN' in self.lsm.configs:
            runner = Arm64LLVMKernelRunner()
            runner.configs = [
                'allmodconfig',
                'CONFIG_GCOV_KERNEL=n',
                'CONFIG_KASAN=n',
                'CONFIG_LTO_CLANG_THIN=y',
            ]
            self._runners.append(runner)

        for config_target in ('allnoconfig', 'tinyconfig'):
            runner = Arm64LLVMKernelRunner()
            runner.configs = [config_target]
            self._runners.append(runner)

    def _add_distroconfig_runners(self):
        configs = [
            ('alpine', 'aarch64'),
            ('archlinux', 'aarch64'),
            ('debian', KERNEL_ARCH),
            ('fedora', 'aarch64'),
            ('opensuse', KERNEL_ARCH),
        ]
        for distro, config_name in configs:
            runner = Arm64LLVMKernelRunner()
            runner.bootable = True
            runner.configs = [Path(self.folders.configs, distro, f"{config_name}.config")]
            if distro == 'fedora' and self.lsm.version < (5, 7, 0):
                for sym, val in (('STM', 'y'), ('TEST_MEMCAT_P', 'n')):
                    if lkt.utils.is_set(self.folders.source, runner.configs[0], sym):
                        runner.configs.append(f"CONFIG_{sym}={val}")
            self._runners.append(runner)

    def run(self):
        cross_compile = '' if platform.machine() == 'aarch64' else CROSS_COMPILE
        if '6f5b41a2f5a63' not in self.lsm.commits and cross_compile:
            self.make_vars['CROSS_COMPILE'] = cross_compile
        if self.lsm.version < MIN_IAS_LNX_VER:
            self.make_vars['LLVM_IAS'] = 0

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
