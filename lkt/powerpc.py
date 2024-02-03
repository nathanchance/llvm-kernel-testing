#!/usr/bin/env python3

from pathlib import Path
import shutil

import lkt.runner
import lkt.utils
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'powerpc'
CLANG_TARGET = 'powerpc-linux-gnu'

# https://github.com/ClangBuiltLinux/linux/issues/1418
# https://git.kernel.org/linus/12318163737cd8808d13faa6e2393774191a6182
MIN_IAS_LNX_VER = LinuxVersion(5, 18, 0)
# https://github.com/llvm/llvm-project/commit/33504b3bbe10d5d4caae13efcb99bd159c126070
MIN_IAS_LLVM_VER = ClangVersion(14, 0, 2)


def ppc64_be_defaults_to_elfv2(lsm):
    # If CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2 does not exist in the current tree,
    # the meaning changes depending on the Linux version. If the tree is newer
    # than 6.2.0 (which first shipped CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2), it
    # means that [1] has been merged, which means that ELFv2 is the only ABI
    # supported internally by the kernel. If it is not newer than 6.2.0, it
    # means ELFv1 is the only option for the internal kernel ABI.
    #
    # [1]: https://lore.kernel.org/20230505071850.228734-5-npiggin@gmail.com/
    if 'CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2' not in lsm.configs:
        return lsm.version >= (6, 2, 0)

    kconfig_text = Path(lsm.folder, 'arch/powerpc/Kconfig').read_text(encoding='utf-8')
    # https://lore.kernel.org/20230505071850.228734-2-npiggin@gmail.com/
    patch_1_state = '"Build big-endian kernel using ELF ABI V2 (EXPERIMENTAL)" if LD_IS_BFD'
    # https://lore.kernel.org/20230505071850.228734-3-npiggin@gmail.com/
    patch_2_state = '"Build big-endian kernel using ELF ABI V2" if LD_IS_BFD && EXPERT'
    return patch_1_state in kconfig_text or patch_2_state in kconfig_text


class PowerPCLLVMKernelRunner(lkt.runner.LLVMKernelRunner):

    def __init__(self):
        super().__init__()

        self.boot_arch = 'ppc64le'
        self.image_target = 'zImage.epapr'
        self.qemu_arch = 'ppc64'

        # Support will be enabled based on known working combinations
        self.make_vars['LLVM_IAS'] = 0


class PowerPCLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

        for cross_compile in ['powerpc64-linux-gnu-', f"{CLANG_TARGET}-", 'powerpc64le-linux-gnu-']:
            # Assignment first so that 'CROSS_COMPILE' is always present in
            # self.make_vars. If binutils are not installed, the whole build
            # will be skipped later.
            self.make_vars['CROSS_COMPILE'] = cross_compile
            if shutil.which(f"{cross_compile}as"):
                break

        self._ppc64_vars = {}
        self._ppc64le_vars = {}

    def _add_defconfig_runners(self):
        ##########
        # 32-bit #
        ##########
        kconfig_text = Path(self.folders.source,
                            'arch/powerpc/platforms/Kconfig.cputype').read_text(encoding='utf-8')
        has_44x_hack = '"440 (44x family)"\n\tdepends on 44x\n\tdepends on !CC_IS_CLANG' in kconfig_text

        cbl_1814 = '2255411d1d0f0' in self.lsm.commits and not has_44x_hack
        cbl_1679 = self._llvm_version < (cbl_1679_fixed_ver := ClangVersion(16, 0, 0)) and cbl_1814

        if cbl_1679:
            self._skip_one(
                f"{KERNEL_ARCH} ppc44x_defconfig",
                f"LLVM < {cbl_1679_fixed_ver} (using '{self._llvm_version}') with 2255411d1d0f0 (from {LinuxVersion(6, 0, 0)}) present (https://github.com/ClangBuiltLinux/linux/issues/1679)",
            )
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
            runner.qemu_arch = 'ppc'
            self._runners.append(runner)

        if '297565aa22cfa' in self.lsm.commits:
            runner = PowerPCLLVMKernelRunner()
            runner.boot_arch = 'ppc32_mac'
            # https://github.com/llvm/llvm-project/commit/1e3c6fc7cb9d2ee6a5328881f95d6643afeadbff
            runner.bootable = self._llvm_version >= (pmac_min_llvm_ver_for_boot :=
                                                     ClangVersion(14, 0, 0))
            if not runner.bootable:
                runner.result[
                    'boot'] = f"skipped due to LLVM < {pmac_min_llvm_ver_for_boot} (using '{self._llvm_version}')"
            runner.configs = ['pmac32_defconfig']
            if '0b5e06e9cb156' not in self.lsm.commits:
                runner.configs += [
                    'CONFIG_SERIAL_PMACZILOG=y',
                    'CONFIG_SERIAL_PMACZILOG_CONSOLE=y',
                ]
            runner.image_target = 'vmlinux'
            runner.only_test_boot = self.only_test_boot
            runner.qemu_arch = 'ppc'
            self._runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} pmac32_defconfig",
                f"missing 297565aa22cfa (from {LinuxVersion(5, 18, 0)}) for https://github.com/ClangBuiltLinux/linux/issues/563",
            )

        #####################
        # 64-bit big endian #
        #####################
        no_elfv2 = not ppc64_be_defaults_to_elfv2(self.lsm)

        runner = PowerPCLLVMKernelRunner()
        runner.boot_arch = 'ppc64'
        runner.bootable = True
        runner.configs = ['ppc64_guest_defconfig']
        wa_cbl_668 = '9451c79bc39e' not in self.lsm.commits
        wa_cbl_1292 = '51696f39cbee5' not in self.lsm.commits and self._llvm_version >= (12, 0, 0)
        wa_cbl_1445 = self.lsm.version >= (5, 18, 0) and self._llvm_version < (14, 0, 0)
        if wa_cbl_668 or wa_cbl_1292 or wa_cbl_1445:
            runner.configs.append('CONFIG_PPC_DISABLE_WERROR=y')
        runner.image_target = 'vmlinux'
        # This needs to happen before the LLVM_IAS assignment below.
        runner.make_vars.update(self._ppc64_vars)
        if no_elfv2:
            # https://github.com/ClangBuiltLinux/linux/issues/602
            runner.make_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
            # The PowerPC vDSO at the time of this comment (6.5-rc3) uses $(CC)
            # to link, not $(LD) like the rest of the kernel. When using the
            # integrated assembler, '--prefix' is not added to CLANG_FLAGS
            # (https://git.kernel.org/linus/eec08090bcc113643522d4272dc0b945045aba74),
            # meaning that clang attempts to use the host's GNU ld in clang
            # versions that contain
            # https://github.com/llvm/llvm-project/commit/3452a0d8c17f7166f479706b293caf6ac76ffd90.
            # Just use GNU as in this case, as that is how this configuration
            # has been built until recently.
            runner.make_vars['LLVM_IAS'] = 0
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        ########################
        # 64-bit little endian #
        ########################
        runner = PowerPCLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['powernv_defconfig']
        runner.make_vars.update(self._ppc64le_vars)
        # https://github.com/ClangBuiltLinux/linux/issues/1260
        if self._llvm_version < (12, 0, 0) and 'LD' not in self.make_vars:
            runner.make_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        runner = PowerPCLLVMKernelRunner()
        # See comment in _add_distroconfig_runners(), RELOCATABLE is always set
        # for this configuration.
        runner.bootable = 'LD' in self._ppc64le_vars or self._llvm_version >= (
            12, 0, 0) or 'CONFIG_MODULE_REL_CRCS' not in self.lsm.configs
        if not runner.bootable:
            parts = [
                'skipped due to',
                'CONFIG_RELOCATABLE=y,',
                'LLVM < 12.0.0 (2fc704a0a529d),',
                'and Linux < 5.19 (7b4537199a4a)',
            ]
            runner.result['boot'] = ' '.join(parts)
        runner.configs = ['ppc64le_guest_defconfig']
        runner.make_vars.update(self._ppc64le_vars)
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        if self.only_test_boot:
            return

        #######################
        # Non-boot defconfigs #
        #######################
        runner = PowerPCLLVMKernelRunner()
        runner.configs = ['ppc64_defconfig']
        if wa_cbl_668 or wa_cbl_1292 or wa_cbl_1445:
            runner.configs.append('CONFIG_PPC_DISABLE_WERROR=y')
        # This needs to happen before the LLVM_IAS assignment below.
        runner.make_vars.update(self._ppc64_vars)
        if no_elfv2:
            # https://github.com/ClangBuiltLinux/linux/issues/602
            runner.make_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
            # See comment in ppc64_guest_defconfig
            runner.make_vars['LLVM_IAS'] = 0
        self._runners.append(runner)

        runner = PowerPCLLVMKernelRunner()
        runner.configs = ['ppc64le_defconfig']
        runner.make_vars.update(self._ppc64le_vars)
        self._runners.append(runner)

    def _add_otherconfig_runners(self):
        min_llvm_ver_for_elfv2_select = ClangVersion(15, 0, 0)
        can_select_elfv2 = 'a11334d8327b' in self.lsm.commits and self._llvm_version >= min_llvm_ver_for_elfv2_select
        elfv2_on_by_default = ppc64_be_defaults_to_elfv2(self.lsm)
        if can_select_elfv2 or elfv2_on_by_default:
            runner = PowerPCLLVMKernelRunner()
            runner.configs = [
                'allmodconfig',
                'CONFIG_WERROR=n',
            ]
            if not elfv2_on_by_default:
                runner.configs.append('CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2=y')
            runner.make_vars.update(self._ppc64_vars)
            self._runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} allmodconfig",
                f"lack of a11334d8327b (from {LinuxVersion(6, 4, 0)}) with LLVM < {min_llvm_ver_for_elfv2_select} (using '{self._llvm_version}') or lack of 9d90161ca5c7 (from {LinuxVersion(6, 5, 0)})",
            )

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
                    and '6fcb574125e67' not in self.lsm.commits
                    and self._llvm_version <= (12, 0, 0)):
                self._skip_one(
                    f"{KERNEL_ARCH} {distro} config",
                    'https://github.com/ClangBuiltLinux/linux/issues/1160',
                )
                continue
            runner = PowerPCLLVMKernelRunner()
            runner.configs = [Path(self.folders.configs, distro, f"{config_name}.config")]
            # There is a boot failure with LLVM 11.1.0 (which does not have
            # https://github.com/llvm/llvm-project/commit/2fc704a0a529dd7eba7566a293f981a86bfa5c3e)
            # when CONFIG_RELOCATABLE is enabled on kernels prior to 5.19,
            # which do not have commit 7b4537199a4a ("kbuild: link symbol CRCs
            # at final link, removing CONFIG_MODULE_REL_CRCS"). Just skip boot
            # testing in this case.
            runner.bootable = not (
                'LD' not in self._ppc64le_vars and self._llvm_version < (12, 0, 0)
                and 'CONFIG_MODULE_REL_CRCS' in self.lsm.configs
                and lkt.utils.is_set(self.folders.source, runner.configs[0], 'RELOCATABLE'))
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
        if self.lsm.version >= MIN_IAS_LNX_VER and self._llvm_version >= MIN_IAS_LLVM_VER:
            self._ppc64_vars['LLVM_IAS'] = 1
            self._ppc64le_vars['LLVM_IAS'] = 1

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
