#!/usr/bin/env python3

from pathlib import Path

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'riscv'
CLANG_TARGET = 'riscv64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 'riscv64'

# Merge patch series "riscv: KCFI support"
# v6.5-rc1-46-g7f7d3ea6eb00 (Thu Aug 31 00:18:32 2023 -0700)
# https://git.kernel.org/linus/7f7d3ea6eb000bd329a6f2fe3f1c7596c4e783e1
MIN_LLVM_VER_CFI = ClangVersion(17, 0, 0)
# RISC-V: build: Allow LTO to be selected
# v6.8-rc1-2-g021d23428bdb (Mon Jan 22 10:06:29 2024 -0800)
# https://git.kernel.org/linus/021d23428bdbae032294e8f4a29cb53cb50ae71c
MIN_LLVM_VER_LTO = ClangVersion(14, 0, 0)
# [CodeGen][RISCV] Change Shadow Call Stack Register to X3
# llvmorg-17-init-7844-gaa1d2693c256 (Wed Apr 12 21:06:22 2023 +0000)
# https://github.com/llvm/llvm-project/commit/aa1d2693c25622ea4a8ee2b622ba2a617e18ef88
MIN_LLVM_VER_SCS = ClangVersion(17, 0, 0)

# error: Unsupported relocation type in arch/riscv/kernel/head.S
# https://github.com/ClangBuiltLinux/linux/issues/1023
# RISC-V: error: 2-byte data relocations not supported
# https://github.com/ClangBuiltLinux/linux/issues/1143
# RISCV: adjust handling of relocation emission for RISCV
# llvmorg-13-init-13148-gbbea64250f65 (Thu Jun 17 08:20:02 2021 -0700)
# https://github.com/llvm/llvm-project/commit/bbea64250f65480d787e1c5ff45c4de3ec2dcda8
MIN_IAS_LLVM_VER = ClangVersion(13, 0, 0)

# riscv: Allow CONFIG_CFI_CLANG to be selected
# v6.5-rc1-6-g74f8fc31feb4 (Wed Aug 23 14:16:41 2023 -0700)
# https://git.kernel.org/linus/74f8fc31feb4b756814ec0720f48ccdc1175f774
LNX_VER_CFI = LinuxVersion(6, 6, 0)
# RISC-V: build: Allow LTO to be selected
# v6.8-rc1-2-g021d23428bdb (Mon Jan 22 10:06:29 2024 -0800)
# https://git.kernel.org/linus/021d23428bdbae032294e8f4a29cb53cb50ae71c
EXPECTED_LNX_VER_LTO = LinuxVersion(6, 9, 0)


class RISCVLLVMKernelRunner(lkt.runner.LLVMKernelRunner):
    def __init__(self) -> None:
        super().__init__()

        self.boot_arch: str = 'riscv'
        self.image_target: str = 'Image'
        self.qemu_arch: str = QEMU_ARCH


class RISCVLKTRunner(lkt.runner.LKTRunner):
    def __init__(self) -> None:
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

        self._has_cfi: bool = False
        self._has_lto: bool = False
        self._has_scs: bool = False

    def _add_defconfig_runners(self) -> None:
        runners: list[RISCVLLVMKernelRunner] = []

        runner = RISCVLLVMKernelRunner()
        runner.configs = ['defconfig']
        if self._llvm_version < (13, 0, 0):
            text = Path(self.folders.source, 'arch/riscv/Kconfig').read_text(encoding='utf-8')
            if 'config EFI' in text:
                runner.configs.append('CONFIG_EFI=n')
        runners.append(runner)

        if self._has_lto:
            runner = RISCVLLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} LTO configs",
                f"either LLVM < {MIN_LLVM_VER_LTO} (using '{self._llvm_version}') or Linux < {EXPECTED_LNX_VER_LTO} (have '{self.lsm.version}')",
            )

        cfi_y_config = self.lsm.get_cfi_y_config()
        if self._has_scs:
            # SCS implies CFI because it came first and they perform the same
            # function, so they are worth testing together.
            base_cfgs: list[Path | str] = ['defconfig', cfi_y_config, 'CONFIG_SHADOW_CALL_STACK=y']

            runner = RISCVLLVMKernelRunner()
            runner.configs = base_cfgs.copy()
            runners.append(runner)

            if self._has_lto:
                runner = RISCVLLVMKernelRunner()
                runner.configs = [*base_cfgs, 'CONFIG_LTO_CLANG_THIN=y']
                runners.append(runner)
        elif self._has_cfi:
            runner = RISCVLLVMKernelRunner()
            runner.configs = ['defconfig', cfi_y_config]
            runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} CFI/SCS configs",
                f"either LLVM < {MIN_LLVM_VER_CFI} (using '{self._llvm_version}') or Linux < {LNX_VER_CFI} (have '{self.lsm.version}')",
            )

        for runner in runners:
            runner.bootable = True
            runner.only_test_boot = self.only_test_boot
        self._runners += runners

    def _add_otherconfig_runners(self) -> None:
        runners: list[RISCVLLVMKernelRunner] = []

        runner = RISCVLLVMKernelRunner()
        runner.configs = ['allmodconfig']
        runners.append(runner)

        # The first version to support linker relaxation
        broken_lto_start = ClangVersion(15, 0, 0)
        # [lld][RISCV] Handle relaxation reductions of more than 65536 bytes
        # llvmorg-17-init-11453-g9d37ea95df1b (Tue May 16 14:59:36 2023 -0700)
        # https://github.com/llvm/llvm-project/commit/9d37ea95df1b84cca9b5e954d8964c976a5e303e
        broken_lto_end = ClangVersion(17, 0, 0)
        if not self._has_lto or broken_lto_start <= self._llvm_version < broken_lto_end:
            self._skip_one(
                f"{KERNEL_ARCH} allmodconfig + ThinLTO",
                f"either LLVM between {broken_lto_start} and {broken_lto_end} (using '{self._llvm_version}') or Linux < {EXPECTED_LNX_VER_LTO} (have '{self.lsm.version}')",
            )
        else:
            runner = RISCVLLVMKernelRunner()
            runner.configs = ['allmodconfig', 'CONFIG_GCOV_KERNEL=n', 'CONFIG_LTO_CLANG_THIN=y']
            runners.append(runner)

        self._runners += runners

    def _add_distroconfig_runners(self) -> None:
        distros = ('alpine', 'debian', 'fedora', 'opensuse')
        for distro in distros:
            runner = RISCVLLVMKernelRunner()
            # riscv: set default pm_power_off to NULL
            # v5.15-rc1-6-gf2928e224d85 (Mon Oct 4 14:16:57 2021 -0700)
            # https://git.kernel.org/linus/f2928e224d85e7cc139009ab17cefdfec2df5d11
            runner.bootable = 'f2928e224d85e7cc139009ab17cefdfec2df5d11' in self.lsm.commits
            if not runner.bootable:
                runner.result.boot = (
                    f"skipped due to lack of f2928e224d85e (from {LinuxVersion(5, 16, 0)})"
                )
            runner.configs = [Path(self.folders.configs, distro, 'riscv64.config')]
            self._runners.append(runner)

    def run(self) -> list[lkt.runner.Result]:
        if self._llvm_version < MIN_IAS_LLVM_VER:
            self.make_vars['LLVM_IAS'] = '0'

        if self._llvm_version < (13, 0, 0):
            self.make_vars['LD'] = f"{CROSS_COMPILE}ld"

        riscv_kconfig_txt = Path(self.folders.source, 'arch/riscv/Kconfig').read_text(
            encoding='utf-8'
        )
        self._has_cfi = self._llvm_version >= MIN_LLVM_VER_CFI and self.lsm.arch_supports_kcfi(
            KERNEL_ARCH
        )
        self._has_lto = (
            self._llvm_version >= MIN_LLVM_VER_LTO
            and 'ARCH_SUPPORTS_LTO_CLANG' in riscv_kconfig_txt
        )
        self._has_scs = (
            self._llvm_version >= MIN_LLVM_VER_SCS
            and 'ARCH_SUPPORTS_SHADOW_CALL_STACK' in riscv_kconfig_txt
        )

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
