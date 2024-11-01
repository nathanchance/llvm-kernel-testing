#!/usr/bin/env python3

from pathlib import Path

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'riscv'
CLANG_TARGET = 'riscv64-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 'riscv64'

# https://git.kernel.org/torvalds/l/abc71bf0a70311ab294f97a7f16e8de03718c05a
MIN_LNX_VER = LinuxVersion(5, 7, 0)

# https://git.kernel.org/linus/7f7d3ea6eb000bd329a6f2fe3f1c7596c4e783e1
MIN_LLVM_VER_CFI = ClangVersion(17, 0, 0)
# https://git.kernel.org/riscv/c/021d23428bdbae032294e8f4a29cb53cb50ae71c
MIN_LLVM_VER_LTO = ClangVersion(14, 0, 0)
# https://github.com/llvm/llvm-project/commit/aa1d2693c25622ea4a8ee2b622ba2a617e18ef88
MIN_LLVM_VER_SCS = ClangVersion(17, 0, 0)

# https://github.com/ClangBuiltLinux/linux/issues/1023
# https://github.com/ClangBuiltLinux/linux/issues/1143
MIN_IAS_LLVM_VER = ClangVersion(13, 0, 0)

# https://git.kernel.org/linus/74f8fc31feb4b756814ec0720f48ccdc1175f774
LNX_VER_CFI = LinuxVersion(6, 6, 0)
# https://git.kernel.org/riscv/c/021d23428bdbae032294e8f4a29cb53cb50ae71c
EXPECTED_LNX_VER_LTO = LinuxVersion(6, 9, 0)


class RISCVLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = 'riscv'
        self.image_target = 'Image'
        self.qemu_arch = QEMU_ARCH


class RISCVLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

        self._has_cfi = False
        self._has_lto = False
        self._has_scs = False

    def _add_defconfig_runners(self):
        runners = []

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

        if self._has_scs:
            # SCS implies CFI because it came first and they perform the same
            # function, so they are worth testing together.
            base_cfgs = ['defconfig', 'CONFIG_CFI_CLANG=y', 'CONFIG_SHADOW_CALL_STACK=y']

            runner = RISCVLLVMKernelRunner()
            runner.configs = base_cfgs.copy()
            runners.append(runner)

            if self._has_lto:
                runner = RISCVLLVMKernelRunner()
                runner.configs = [*base_cfgs, 'CONFIG_LTO_CLANG_THIN=y']
                runners.append(runner)
        elif self._has_cfi:
            runner = RISCVLLVMKernelRunner()
            runner.configs = ['defconfig', 'CONFIG_CFI_CLANG=y']
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

    def _add_otherconfig_runners(self):
        runners = []

        runner = RISCVLLVMKernelRunner()
        runner.configs = ['allmodconfig']
        runners.append(runner)

        # The first version to support linker relaxation
        broken_lto_start = ClangVersion(15, 0, 0)
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

    def _add_distroconfig_runners(self):
        distros = ('alpine', 'opensuse')
        for distro in distros:
            runner = RISCVLLVMKernelRunner()
            runner.bootable = 'f2928e224d85e' in self.lsm.commits
            if not runner.bootable:
                runner.result[
                    'boot'] = f"skipped due to lack of f2928e224d85e (from {LinuxVersion(5, 16, 0)})"
            runner.configs = [Path(self.folders.configs, distro, 'riscv64.config')]
            self._runners.append(runner)

    def run(self):
        if self.lsm.version < MIN_LNX_VER:
            print_text = (
                f"RISC-V needs the following fixes from Linux {MIN_LNX_VER} to build properly:\n"
                '\n'
                '        * https://git.kernel.org/linus/52e7c52d2ded5908e6a4f8a7248e5fa6e0d6809a\n'
                '        * https://git.kernel.org/linus/fdff9911f266951b14b20e25557278b5b3f0d90d\n'
                '        * https://git.kernel.org/linus/abc71bf0a70311ab294f97a7f16e8de03718c05a\n'
                '\n'
                f"Provide a kernel tree with Linux {MIN_LNX_VER} or newer to build RISC-V kernels.")
            return self._skip_all(
                f"missing 52e7c52d2ded, fdff9911f266, and/or abc71bf0a703 (from {MIN_LNX_VER})",
                print_text)

        if '6f5b41a2f5a63' not in self.lsm.commits:
            self.make_vars['CROSS_COMPILE'] = CROSS_COMPILE
        if self._llvm_version < MIN_IAS_LLVM_VER:
            self.make_vars['LLVM_IAS'] = 0

        if (self._llvm_version < (13, 0, 0) or 'ec3a5cb61146c' not in self.lsm.commits
                or self.lsm.version <= (5, 10, 999)):
            self.make_vars['LD'] = f"{CROSS_COMPILE}ld"

        riscv_kconfig_txt = Path(self.folders.source,
                                 'arch/riscv/Kconfig').read_text(encoding='utf-8')
        self._has_cfi = self._llvm_version >= MIN_LLVM_VER_CFI and 'ARCH_SUPPORTS_CFI_CLANG' in riscv_kconfig_txt
        self._has_lto = self._llvm_version >= MIN_LLVM_VER_LTO and 'ARCH_SUPPORTS_LTO_CLANG' in riscv_kconfig_txt
        self._has_scs = self._llvm_version >= MIN_LLVM_VER_SCS and 'ARCH_SUPPORTS_SHADOW_CALL_STACK' in riscv_kconfig_txt

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            min_other_distro_lnx_ver = LinuxVersion(5, 8, 0)
            if self.lsm.version > min_other_distro_lnx_ver and 'ec3a5cb61146c' in self.lsm.commits:
                if 'other' in self.targets:
                    self._add_otherconfig_runners()
                if 'distro' in self.targets:
                    self._add_distroconfig_runners()
            else:
                self._skip_one(
                    f"{KERNEL_ARCH} other and distro configs",
                    f"Linux < {min_other_distro_lnx_ver} (have '{self.lsm.version}') or missing ec3a5cb61146c (from {LinuxVersion(5, 13, 0)})",
                )

        return super().run()
