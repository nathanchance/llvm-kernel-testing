#!/usr/bin/env python3

from pathlib import Path
import shutil

import lkt.runner

KERNEL_ARCH = 'powerpc'
CLANG_TARGET = 'powerpc-linux-gnu'


# Move this to source.py once the series is in mainline
def has_big_endian_elf_v2(lsm):
    if 'CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2' not in lsm.configs:
        return False

    kconfig_text = Path(lsm.folder, 'arch/powerpc/Kconfig').read_text(encoding='utf-8')
    return 'depends on CC_HAS_ELFV2\n\tdepends on LD_IS_BFD' not in kconfig_text


class PowerPCLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = 'ppc64le'
        self.image_target = 'zImage.epapr'


class PowerPCLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__()

        self.make_vars['ARCH'] = KERNEL_ARCH
        for cross_compile in ['powerpc64-linux-gnu-', f"{CLANG_TARGET}-", 'powerpc64le-linux-gnu-']:
            # Assignment first so that 'CROSS_COMPILE' is always present in
            # self.make_vars. If binutils are not installed, the whole build
            # will be skipped later.
            self.make_vars['CROSS_COMPILE'] = cross_compile
            if shutil.which(f"{cross_compile}as"):
                break

        self._clang_target = CLANG_TARGET
        self._ppc64le_vars = {}

    def _add_defconfig_runners(self):
        kconfig_text = Path(self.folders.source,
                            'arch/powerpc/platforms/Kconfig.cputype').read_text(encoding='utf-8')
        has_44x_hack = '"440 (44x family)"\n\tdepends on 44x\n\tdepends on !CC_IS_CLANG' in kconfig_text

        cbl_1814 = '2255411d1d0f0' in self.lsm.commits and not has_44x_hack
        cbl_1679 = self._llvm_version < (16, 0, 0) and cbl_1814

        if cbl_1679:
            self._results.append({
                'name':
                'powerpc ppc44x_defconfig',
                'build':
                'skipped',
                'reason':
                'LLVM < 16.x and 2255411d1d0f0 (https://github.com/ClangBuiltLinux/linux/issues/1679)',
            })
        else:
            runner = PowerPCLLVMKernelRunner()
            runner.boot_arch = 'ppc32'
            cbl_1345 = self._llvm_version < (12, 0, 1) and '48cf12d88969b' in self.lsm.commits
            runner.bootable = not (cbl_1345 or cbl_1814)
            if not runner.bootable:
                parts = ['skipped']
                if cbl_1345:
                    parts += [
                        'due to lr save/restore',
                        '(https://github.com/ClangBuiltLinux/linux/issues/1345)',
                    ]
                elif cbl_1814:
                    parts += [
                        'due to "-mcpu=440"',
                        '(https://github.com/ClangBuiltLinux/linux/issues/1814)',
                    ]
                runner.result['boot'] = ' '.join(parts)
            runner.configs = ['ppc44x_defconfig']
            runner.image_target = 'uImage'
            if not self.only_test_boot:
                runner.make_targets.append(runner.image_target)
            runner.only_test_boot = self.only_test_boot
            self._runners.append(runner)

        if '297565aa22cfa' in self.lsm.commits:
            runner = PowerPCLLVMKernelRunner()
            runner.boot_arch = 'ppc32_mac'
            runner.bootable = self._llvm_version >= (14, 0, 0)
            if not runner.bootable:
                runner.result['boot'] = 'skipped due to LLVM < 14.0.0 (lack of 1e3c6fc7cb9d2)'
            runner.configs = [
                'pmac32_defconfig',
                'CONFIG_SERIAL_PMACZILOG=y',
                'CONFIG_SERIAL_PMACZILOG_CONSOLE=y',
            ]
            runner.image_target = 'vmlinux'
            runner.only_test_boot = self.only_test_boot
            self._runners.append(runner)
        else:
            self._results.append({
                'name':
                'powerpc pmac32_defconfig',
                'build':
                'skipped',
                'reason':
                'missing 297565aa22cfa (https://github.com/ClangBuiltLinux/linux/issues/563)',
            })

        runner = PowerPCLLVMKernelRunner()
        runner.boot_arch = 'ppc64'
        runner.bootable = True
        runner.configs = ['pseries_defconfig']
        wa_cbl_1292 = '51696f39cbee5' not in self.lsm.commits and self._llvm_version >= (12, 0, 0)
        wa_cbl_1445 = self.lsm.version >= (5, 18, 0) and self._llvm_version < (14, 0, 0)
        if wa_cbl_1292 or wa_cbl_1445:
            runner.configs.append('CONFIG_PPC_DISABLE_WERROR=y')
        runner.image_target = 'vmlinux'
        runner.make_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        runner = PowerPCLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['powernv_defconfig']
        runner.make_vars.update(self._ppc64le_vars)
        # https://github.com/ClangBuiltLinux/linux/issues/1260
        if self._llvm_version < (12, 0, 0) and 'LD' not in self.make_vars:
            runner.make_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        if self.only_test_boot:
            return

        runner = PowerPCLLVMKernelRunner()
        runner.configs = ['ppc64le_defconfig']
        runner.make_vars.update(self._ppc64le_vars)
        self._runners.append(runner)

    def _add_otherconfig_runners(self):
        if has_big_endian_elf_v2(self.lsm):
            runner = PowerPCLLVMKernelRunner()
            runner.configs = [
                'allmodconfig',
                'CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2=y',
                'CONFIG_WERROR=n',
            ]
            runner.make_vars.update(self._ppc64le_vars)
            self._runners.append(runner)

        for cfg_target in ['allnoconfig', 'tinyconfig']:
            runner = PowerPCLLVMKernelRunner()
            runner.configs = [cfg_target]
            self._runners.append(runner)

    def _add_distroconfig_runners(self):
        configs = [
            ('debian', 'powerpc64le'),
            ('fedora', 'ppc64le'),
            ('opensuse', 'ppc64le'),
        ]
        for distro, config_name in configs:
            if (distro == 'opensuse' and '231b232df8f67' in self.lsm.commits
                    and '6fcb574125e67' not in self.lsm.commits and self._llvm_version <=
                (12, 0, 0)):
                self._results.append({
                    'name':
                    f"{self.make_vars['ARCH']} {distro} config",
                    'build':
                    'skipped',
                    'reason':
                    'https://github.com/ClangBuiltLinux/linux/issues/1160',
                })
                continue
            runner = PowerPCLLVMKernelRunner()
            runner.configs = [Path(self.folders.configs, distro, f"{config_name}.config")]
            # There is a boot failure with LLVM 11.1.0 (which does not have
            # https://github.com/llvm/llvm-project/commit/2fc704a0a529dd7eba7566a293f981a86bfa5c3e)
            # when CONFIG_RELOCATABLE is enabled on kernels prior to 5.19,
            # which do not have commit 7b4537199a4a ("kbuild: link symbol CRCs
            # at final link, removing CONFIG_MODULE_REL_CRCS"). Just skip boot
            # testing in this case.
            runner.bootable = not ('LD' not in self._ppc64le_vars and self._llvm_version <
                                   (12, 0, 0) and 'CONFIG_MODULE_REL_CRCS' in self.lsm.configs
                                   and lkt.utils.is_set(self.folders.source, runner.configs[0],
                                                        'RELOCATABLE'))
            if not runner.bootable:
                parts = [
                    'skipped due to',
                    'CONFIG_RELOCATABLE=y,',
                    'LLVM < 12.0.0 (2fc704a0a529d),',
                    'and Linux < 5.19 (7b4537199a4a)',
                ]
                runner.result['boot'] = ' '.join(parts)
            runner.lsm = self.lsm
            runner.make_vars.update(self._ppc64le_vars)
            self._runners.append(runner)

    def run(self):
        if '0355785313e21' not in self.lsm.commits and 'CROSS_COMPILE' in self.make_vars:
            self._ppc64le_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
        if self.lsm.version >= (5, 18, 0) and self._llvm_version >= (14, 0, 0):
            self._ppc64le_vars['LLVM_IAS'] = 1

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
