#!/usr/bin/env python3

from pathlib import Path

import lkt.runner
from lkt.version import BinutilsVersion, ClangVersion, QemuVersion

KERNEL_ARCH = 's390'
CLANG_TARGET = 's390x-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 's390x'

# While the change that raised the minimum version of LLVM for s390 did
# not land in Linux until 5.14, backports to earlier versions may use
# the assembly constructs that caused the minimum version to be bumped
# in the first place
HARD_MIN_LLVM_VER = ClangVersion(13, 0, 0)

# QEMU needs to contain at least https://gitlab.com/qemu-project/qemu/-/commit/c23908305b3ce7a547b0981eae549f36f756b950
# which comes from this series: https://lore.kernel.org/all/20210108132049.8501-1-david@redhat.com/
MIN_QEMU_VER = QemuVersion(6, 0, 0)


class S390LLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = KERNEL_ARCH
        self.image_target = 'bzImage'
        self.qemu_arch = QEMU_ARCH


class S390LKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__()

        self.make_vars['ARCH'] = KERNEL_ARCH
        for variable in ['LD', 'OBJCOPY', 'OBJDUMP']:
            self.make_vars[variable] = f"{CROSS_COMPILE}{variable.lower()}"

        self._binutils_version = BinutilsVersion(binary=f"{CROSS_COMPILE}as")
        self._clang_target = CLANG_TARGET
        self._qemu_version = QemuVersion(arch=QEMU_ARCH)

    def _add_defconfig_runners(self):
        runner = S390LLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['defconfig']
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

    def _add_otherconfig_runners(self):
        other_cfgs = [
            'allmodconfig',
            'allnoconfig',
            'tinyconfig',
        ]
        for config_target in other_cfgs:
            runner = S390LLVMKernelRunner()
            runner.configs = [config_target]
            if config_target == 'allmodconfig':
                if '925d046e7e52' in self.lsm.commits and '876e480da2f74' not in self.lsm.commits:
                    runner.configs.append('CONFIG_INFINIBAND_ADDR_TRANS=n')
                if 'CONFIG_WERROR' in self.lsm.configs:
                    runner.configs.append('CONFIG_WERROR=n')
            self._runners.append(runner)

    def _add_distroconfig_runners(self):
        distros = [
            'debian',
            'fedora',
            'opensuse',
        ]
        for distro in distros:
            runner = S390LLVMKernelRunner()
            runner.bootable = True
            runner.configs = [Path(self.folders.configs, distro, 's390x.config')]
            if distro == 'fedora' and 'efe5e0fea4b24' not in self.lsm.commits:
                runner.configs += ['CONFIG_MARCH_Z13=n', 'CONFIG_MARCH_Z196=y']
            runner.lsm = self.lsm
            self._runners.append(runner)

    def run(self):
        if self.lsm.version < (5, 6, 0):
            print_text = (
                's390 kernels did not build properly until Linux 5.6\n'
                '        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/'
            )
            return self._skip(
                'missing fixes from 5.6 (https://lore.kernel.org/r/your-ad-here.call-01580230449-ext-6884@work.hours/)',
                print_text)
        if self._binutils_version >= (2, 39, 50) and '80ddf5ce1c929' not in self.lsm.commits:
            print_text = (
                's390 kernels may fail to link with binutils 2.40+ and CONFIG_RELOCATABLE=n\n'
                '        https://github.com/ClangBuiltLinux/linux/issues/1747')
            return self._skip(
                'linker error with CONFIG_RELOCATABLE=n (https://github.com/ClangBuiltLinux/linux/issues/1747)',
                print_text)

        if (min_llvm_ver := self.lsm.get_min_llvm_ver(KERNEL_ARCH)) < HARD_MIN_LLVM_VER:
            min_llvm_ver = HARD_MIN_LLVM_VER
            reason = 'to avoid build failures from backports of commits that came after minimum version change in 5.14'
        else:
            reason = 'because of scripts/min-tool-version.sh for supplied tree'

        if self._llvm_version < min_llvm_ver:
            return self._skip(f"LLVM < {min_llvm_ver}",
                              f"s390 requires LLVM {min_llvm_ver} or newer {reason}")

        if self.lsm.version >= (5, 19, 0):
            self.make_vars['LLVM_IAS'] = 1
        else:
            self.make_vars['CROSS_COMPILE'] = CROSS_COMPILE

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        if self._qemu_version < MIN_QEMU_VER:
            for runner in self._runners:
                if runner.bootable:
                    runner.bootable = False
                    runner.result[
                        'boot'] = f"skipped due to qemu older than {MIN_QEMU_VER} (found {self._qemu_version})"

        return super().run()
