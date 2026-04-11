#!/usr/bin/env python3

from pathlib import Path

import lkt.runner
from lkt.source import LinuxSourceManager
import lkt.utils
from lkt.version import ClangVersion

KERNEL_ARCH = 'arm64'
CLANG_TARGET = 'aarch64-linux-gnu'
QEMU_ARCH = 'aarch64'


def can_build_arm64_big_endian(lsm: LinuxSourceManager, llvm_version: ClangVersion) -> bool:
    arm64_kconfig_txt = Path(lsm.folder, 'arch/arm64/Kconfig').read_text(encoding='utf-8')

    # Detect if big endian support is present and working in the kernel
    # arm64: Kconfig: Make CPU_BIG_ENDIAN depend on BROKEN
    # v6.17-rc1-3-g1cf89b6bf660 (Wed Sep 24 16:25:45 2025 +0100)
    # https://git.kernel.org/linus/1cf89b6bf660c2e9fa137b3e160c7b1001937a78
    # Look for three states:
    # 1. That commit as it exists in the arm64 tree
    # 2. That commit with https://lore.kernel.org/aNU-sG84vqPj7p7G@sirena.org.uk/ addressed
    # 3. A future where CONFIG_CPU_BIG_ENDIAN does not even exist
    state_one = 'config CPU_BIG_ENDIAN\n\tbool "Build big-endian kernel"\n\t# https://github.com/llvm/llvm-project/commit/1379b150991f70a5782e9a143c2ba5308da1161c\n\tdepends on (AS_IS_GNU || AS_VERSION >= 150000) && BROKEN\n\thelp'
    state_two = (
        'config CPU_BIG_ENDIAN\n\tbool "Build big-endian kernel"\n\tdepends on BROKEN\n\thelp'
    )
    be_broken = state_one in arm64_kconfig_txt or state_two in arm64_kconfig_txt
    be_exists = 'config CPU_BIG_ENDIAN' in arm64_kconfig_txt

    # arm64: Restrict CPU_BIG_ENDIAN to GNU as or LLVM IAS 15.x or newer
    # v6.6-rc3-8-g146a15b87335 (Thu Oct 26 16:33:20 2023 +0100)
    # https://git.kernel.org/linus/146a15b873353f8ac28dc281c139ff611a3c4848
    return llvm_version >= ClangVersion(15, 0, 0) and not be_broken and be_exists


class Arm64LLVMKernelRunner(lkt.runner.LLVMKernelRunner):
    def __init__(self) -> None:
        super().__init__()

        self.boot_arch: str = KERNEL_ARCH
        self.image_target: str = 'Image.gz'
        self.qemu_arch: str = QEMU_ARCH


class Arm64LKTRunner(lkt.runner.LKTRunner):
    def __init__(self) -> None:
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self) -> None:
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

        runner = Arm64LLVMKernelRunner()
        runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
        runners.append(runner)

        if self.lsm.arch_supports_kcfi(KERNEL_ARCH):
            cfi_y_config = self.lsm.get_cfi_y_config()
            # cfi: Switch to -fsanitize=kcfi
            # v6.0-rc4-5-g89245600941e (Mon Sep 26 10:13:13 2022 -0700)
            # https://git.kernel.org/linus/89245600941e4e0f87d77f60ee269b5e61ef4e49
            if '89245600941e4e0f87d77f60ee269b5e61ef4e49' in self.lsm.commits:
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
        else:
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_SHADOW_CALL_STACK=y']
            runners.append(runner)

        if Path(self.folders.source, 'kernel/configs/hardening.config').exists():
            runner = Arm64LLVMKernelRunner()
            runner.configs = ['defconfig', 'hardening.config']
            runners.append(runner)

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self) -> None:
        runner = Arm64LLVMKernelRunner()
        runner.configs = ['allmodconfig']
        self._runners.append(runner)

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

    def _add_distroconfig_runners(self) -> None:
        configs: list[tuple[str, str]] = [
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

    def run(self) -> list[lkt.runner.Result]:
        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
