#!/usr/bin/env python3

from pathlib import Path
import shutil

import lkt.runner
from lkt.source import LinuxSourceManager
import lkt.utils
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'powerpc'
CLANG_TARGET = 'powerpc-linux-gnu'

# https://github.com/ClangBuiltLinux/linux/issues/1418
# powerpc/32: Remove remaining .stabs annotations
# v5.17-rc2-28-g12318163737c (Mon Feb 7 21:03:10 2022 +1100)
# https://git.kernel.org/linus/12318163737cd8808d13faa6e2393774191a6182
MIN_IAS_LNX_VER = LinuxVersion(5, 18, 0)
# [PowerPC] Allow absolute expressions in relocations
# llvmorg-14.0.1-16-g33504b3bbe10 (Mon Apr 18 17:02:51 2022 -0700)
# https://github.com/llvm/llvm-project/commit/33504b3bbe10d5d4caae13efcb99bd159c126070
MIN_IAS_LLVM_VER = ClangVersion(14, 0, 2)


def ppc64_be_defaults_to_elfv2(lsm: LinuxSourceManager) -> bool:
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
    # powerpc/64: Force ELFv2 when building with LLVM linker
    # v6.4-rc2-35-g9d90161ca5c7 (Wed Jun 14 12:46:42 2023 +1000)
    # https://git.kernel.org/linus/9d90161ca5c7234e80e14e563d198f322ca0c1d0
    patch_1_state = '"Build big-endian kernel using ELF ABI V2 (EXPERIMENTAL)" if LD_IS_BFD'
    # powerpc/64: Make ELFv2 the default for big-endian builds
    # v6.4-rc2-36-g8c5fa3b5c4df (Wed Jun 14 12:46:42 2023 +1000)
    # https://git.kernel.org/linus/8c5fa3b5c4df3d071dab42b04b971df370d99354
    patch_2_state = '"Build big-endian kernel using ELF ABI V2" if LD_IS_BFD && EXPERT'
    return patch_1_state in kconfig_text or patch_2_state in kconfig_text


class PowerPCLLVMKernelRunner(lkt.runner.LLVMKernelRunner):
    def __init__(self) -> None:
        super().__init__()

        self.boot_arch: str = 'ppc64le'
        self.image_target: str = 'zImage.epapr'
        self.qemu_arch: str = 'ppc64'

        # Support will be enabled based on known working combinations
        self.make_vars['LLVM_IAS'] = '0'


class PowerPCLKTRunner(lkt.runner.LKTRunner):
    def __init__(self) -> None:
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

        for cross_compile in ('powerpc64-linux-gnu-', f"{CLANG_TARGET}-", 'powerpc64le-linux-gnu-'):
            # Assignment first so that 'CROSS_COMPILE' is always present in
            # self.make_vars. If binutils are not installed, the whole build
            # will be skipped later.
            self.make_vars['CROSS_COMPILE'] = cross_compile
            if shutil.which(f"{cross_compile}as"):
                break

        self._ppc64_vars: lkt.runner.MakeVars = {}
        self._ppc64le_vars: lkt.runner.MakeVars = {}

    def _add_defconfig_runners(self) -> None:
        ##########
        # 32-bit #
        ##########
        kconfig_text = Path(
            self.folders.source, 'arch/powerpc/platforms/Kconfig.cputype'
        ).read_text(encoding='utf-8')
        has_44x_hack = (
            '"440 (44x family)"\n\tdepends on 44x\n\tdepends on !CC_IS_CLANG' in kconfig_text
        )

        # powerpc/44x: Fix build failure with GCC 12 (unrecognized opcode: `wrteei')
        # v5.19-rc2-164-g2255411d1d0f (Wed Jul 27 21:36:06 2022 +1000)
        # https://git.kernel.org/linus/2255411d1d0f0661d1e5acd5f6edf4e6652a345a
        cbl_1814 = '2255411d1d0f0' in self.lsm.commits and not has_44x_hack
        # https://github.com/ClangBuiltLinux/linux/issues/1679
        cbl_1679 = self._llvm_version < (cbl_1679_fixed_ver := ClangVersion(16, 0, 0)) and cbl_1814

        if cbl_1679:
            self._skip_one(
                f"{KERNEL_ARCH} ppc44x_defconfig",
                f"LLVM < {cbl_1679_fixed_ver} (using '{self._llvm_version}') with 2255411d1d0f0 (from {LinuxVersion(6, 0, 0)}) present (https://github.com/ClangBuiltLinux/linux/issues/1679)",
            )
        else:
            runner = PowerPCLLVMKernelRunner()
            runner.boot_arch = 'ppc32'
            # https://github.com/ClangBuiltLinux/linux/issues/1345
            # powerpc/irq: Inline call_do_irq() and call_do_softirq()
            # v5.12-rc3-100-g48cf12d88969 (Mon Mar 29 13:22:17 2021 +1100)
            # https://git.kernel.org/linus/48cf12d88969bd4238b8769767eb476970319d93
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
                runner.result.boot = ' '.join(parts)
            runner.configs = ['ppc44x_defconfig']
            runner.image_target = 'uImage'
            if not self.only_test_boot:
                runner.make_targets.append(runner.image_target)
            runner.only_test_boot = self.only_test_boot
            runner.qemu_arch = 'ppc'
            self._runners.append(runner)

        # lib/xor: make xor prototypes more friendly to compiler vectorization
        # v5.17-rc1-61-g297565aa22cf (Fri Feb 11 20:39:39 2022 +1100)
        # https://git.kernel.org/linus/297565aa22cfa80ab0f88c3569693aea0b6afb6d
        if '297565aa22cfa' in self.lsm.commits:
            runner = PowerPCLLVMKernelRunner()
            runner.boot_arch = 'ppc32_mac'
            # [JumpThreading] Ignore free instructions
            # llvmorg-14-init-4665-g1e3c6fc7cb9d (Thu Sep 23 18:28:36 2021 +0200)
            # https://github.com/llvm/llvm-project/commit/1e3c6fc7cb9d2ee6a5328881f95d6643afeadbff
            runner.bootable = self._llvm_version >= (
                pmac_min_llvm_ver_for_boot := ClangVersion(14, 0, 0)
            )
            if not runner.bootable:
                runner.result.boot = f"skipped due to LLVM < {pmac_min_llvm_ver_for_boot} (using '{self._llvm_version}')"
            runner.configs = ['pmac32_defconfig']
            # powerpc/pmac32: enable serial options by default in defconfig
            # v6.5-rc3-36-g0b5e06e9cb15 (Mon Aug 14 21:54:04 2023 +1000)
            # https://git.kernel.org/linus/0b5e06e9cb156e7e97bfb4e1ebf6acd62497eaf5
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
        # https://github.com/ClangBuiltLinux/linux/issues/668
        # powerpc/pmac/smp: Avoid unused-variable warnings
        # v5.6-rc2-66-g9451c79bc39e (Tue Mar 17 23:40:36 2020 +1100)
        # https://git.kernel.org/linus/9451c79bc39e610882bdd12370f01af5004a3c4f
        wa_cbl_668 = '9451c79bc39e' not in self.lsm.commits
        # https://github.com/ClangBuiltLinux/linux/issues/1292
        # KVM: PPC: Book3S HV: Workaround high stack usage with clang
        # v5.13-rc2-41-g51696f39cbee (Wed Jun 23 00:18:30 2021 +1000)
        # https://git.kernel.org/linus/51696f39cbee5bb684e7959c0c98b5f54548aa34
        wa_cbl_1292 = '51696f39cbee5' not in self.lsm.commits and self._llvm_version >= (12, 0, 0)
        # https://github.com/ClangBuiltLinux/linux/issues/1445
        # [Clang][CFG] check children statements of asm goto
        # llvmorg-14-init-14129-g3a604fdbcd5f (Fri Jan 7 14:11:08 2022 -0800)
        # https://github.com/llvm/llvm-project/commit/3a604fdbcd5fd9ca41f6659692bb4ad2151c3cf4
        wa_cbl_1445 = self.lsm.version >= (5, 18, 0) and self._llvm_version < (14, 0, 0)
        if wa_cbl_668 or wa_cbl_1292 or wa_cbl_1445:
            runner.configs.append('CONFIG_PPC_DISABLE_WERROR=y')
        # There is a warning at boot on 5.4, which does not appear in 5.10 or
        # newer. While it would be nice to investigate this issue, 5.4 is quite
        # old at this point, so I am just going to workaround it in this way
        # for now.
        # [    0.372692] Unable to lookup optimized_callback()/emulate_step()
        # [    0.376043] WARNING: CPU: 0 PID: 1 at arch/powerpc/kernel/optprobes.c:250 kretprobe_trampoline+0x16b4/0x19dc
        if self.lsm.version < (5, 10, 0):
            runner.configs.append('CONFIG_KPROBES=n')
        runner.image_target = 'vmlinux'
        # This needs to happen before the LLVM_IAS assignment below.
        runner.make_vars.update(self._ppc64_vars)
        if no_elfv2:
            # ppc64 pseries_defconfig ld.lld errors
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
            runner.make_vars['LLVM_IAS'] = '0'
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        ########################
        # 64-bit little endian #
        ########################
        runner = PowerPCLLVMKernelRunner()
        runner.bootable = True
        runner.configs = ['powernv_defconfig']
        runner.make_vars.update(self._ppc64le_vars)
        # ld.lld unknown relocation (110) against symbol for powerpc64
        # https://github.com/ClangBuiltLinux/linux/issues/1260
        # [ELF] Support R_PPC64_ADDR16_HIGH
        # llvmorg-12-init-17087-g5fcb412ed083 (Tue Jan 19 11:42:53 2021 -0800)
        # https://github.com/llvm/llvm-project/commit/5fcb412ed0831ad763810f9b424149b3b353451a
        if self._llvm_version < (12, 0, 0) and 'LD' not in self.make_vars:
            runner.make_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
        runner.only_test_boot = self.only_test_boot
        self._runners.append(runner)

        runner = PowerPCLLVMKernelRunner()
        # See comment in _add_distroconfig_runners(), RELOCATABLE is always set
        # for this configuration.
        runner.bootable = (
            'LD' in self._ppc64le_vars
            or self._llvm_version >= (12, 0, 0)
            or 'CONFIG_MODULE_REL_CRCS' not in self.lsm.configs
        )
        if not runner.bootable:
            parts = [
                'skipped due to',
                'CONFIG_RELOCATABLE=y,',
                # [ELF] --emit-relocs: fix st_value of STT_SECTION in the presence of a gap before the first input section
                # llvmorg-12-init-10472-g2fc704a0a529 (Mon Nov 2 08:37:15 2020 -0800)
                # https://github.com/llvm/llvm-project/commit/2fc704a0a529dd7eba7566a293f981a86bfa5c3e
                'LLVM < 12.0.0 (2fc704a0a529d),',
                # kbuild: link symbol CRCs at final link, removing CONFIG_MODULE_REL_CRCS
                # v5.18-rc1-54-g7b4537199a4a (Tue May 24 16:33:20 2022 +0900)
                # https://git.kernel.org/linus/7b4537199a4a8480b8c3ba37a2d44765ce76cd9b
                'and Linux < 5.19 (7b4537199a4a)',
            ]
            runner.result.boot = ' '.join(parts)
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
            # ppc64 pseries_defconfig ld.lld errors
            # https://github.com/ClangBuiltLinux/linux/issues/602
            runner.make_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
            # See comment in ppc64_guest_defconfig
            runner.make_vars['LLVM_IAS'] = '0'
        self._runners.append(runner)

        runner = PowerPCLLVMKernelRunner()
        runner.configs = ['ppc64le_defconfig']
        runner.make_vars.update(self._ppc64le_vars)
        self._runners.append(runner)

    def _add_otherconfig_runners(self) -> None:
        min_llvm_ver_for_elfv2_select = ClangVersion(15, 0, 0)
        # This used to be a dynamic check but stable backported a11334d8327b3f
        # without its dependencies (breaking that), so just check for the
        # mainline version that it actually landed in.
        min_lnx_ver_for_elfv2_select = LinuxVersion(6, 4, 0)
        can_select_elfv2 = (
            self.lsm.version >= min_lnx_ver_for_elfv2_select
            and self._llvm_version >= min_llvm_ver_for_elfv2_select
        )
        elfv2_on_by_default = ppc64_be_defaults_to_elfv2(self.lsm)
        if can_select_elfv2 or elfv2_on_by_default:
            runner = PowerPCLLVMKernelRunner()
            runner.configs = ['allmodconfig']
            if not elfv2_on_by_default:
                runner.configs.append('CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2=y')
            runner.make_vars.update(self._ppc64_vars)
            self._runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} allmodconfig",
                # powerpc: Allow CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2 with ld.lld 15+
                # v6.3-rc2-10-ga11334d8327b (Wed Mar 15 00:52:10 2023 +1100)
                # https://git.kernel.org/linus/a11334d8327b3fd7987cbfb38e956a44c722d88f
                # powerpc/64: Force ELFv2 when building with LLVM linker
                # v6.4-rc2-35-g9d90161ca5c7 (Wed Jun 14 12:46:42 2023 +1000)
                # https://git.kernel.org/linus/9d90161ca5c7234e80e14e563d198f322ca0c1d0
                f"lack of a11334d8327b (from {min_lnx_ver_for_elfv2_select}) with LLVM < {min_llvm_ver_for_elfv2_select} (using '{self._llvm_version}') or lack of 9d90161ca5c7 (from {LinuxVersion(6, 5, 0)})",
            )

        for cfg_target in ('allnoconfig', 'tinyconfig'):
            runner = PowerPCLLVMKernelRunner()
            runner.configs = [cfg_target]
            self._runners.append(runner)

    def _add_distroconfig_runners(self) -> None:
        configs = [
            ('alpine', 'ppc64le'),
            ('debian', 'powerpc64le'),
            ('fedora', 'ppc64le'),
            ('opensuse', 'ppc64le'),
        ]
        for distro, config_name in configs:
            reason = None
            if distro in ('fedora', 'opensuse') and self.lsm.version < (5, 17, 0):
                # Drop OpenSUSE's PowerPC configuration from 5.15
                reason = 'https://github.com/ClangBuiltLinux/continuous-integration2/pull/775'
            elif (
                distro == 'opensuse'
                # powerpc/64: Make VDSO32 track COMPAT on 64-bit
                # v5.9-rc2-94-g231b232df8f6 (Mon Sep 14 23:07:04 2020 +1000)
                # https://git.kernel.org/linus/231b232df8f67e7d37af01259c21f2a131c3911e
                and '231b232df8f67' in self.lsm.commits
                # powerpc: Kconfig: disable CONFIG_COMPAT for clang < 12
                # v5.13-rc2-26-g6fcb574125e6 (Sun May 23 20:51:35 2021 +1000)
                # https://git.kernel.org/linus/6fcb574125e673f33ff058caa54b4e65629f3a08
                and '6fcb574125e67' not in self.lsm.commits
                and self._llvm_version <= (12, 0, 0)
            ):
                # arch/powerpc/kernel/vdso32/gettimeofday.S:40: Error: syntax error; found @', expected ,'
                reason = 'https://github.com/ClangBuiltLinux/linux/issues/1160'

            if reason:
                self._skip_one(f"{KERNEL_ARCH} {distro} config", reason)
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
                'LD' not in self._ppc64le_vars
                and self._llvm_version < (12, 0, 0)
                and 'CONFIG_MODULE_REL_CRCS' in self.lsm.configs
                and lkt.utils.is_set(self.folders.source, runner.configs[0], 'RELOCATABLE')
            )
            if not runner.bootable:
                parts = [
                    'skipped due to',
                    'CONFIG_RELOCATABLE=y,',
                    'LLVM < 12.0.0 (2fc704a0a529d),',
                    'and Linux < 5.19 (7b4537199a4a)',
                ]
                runner.result.boot = ' '.join(parts)
            runner.make_vars.update(self._ppc64le_vars)
            self._runners.append(runner)

    def run(self) -> list[lkt.runner.Result]:
        # powerpc: Add "-z notext" flag to disable diagnostic
        # v5.14-rc2-77-g0355785313e2 (Sun Aug 15 13:49:39 2021 +1000)
        # https://git.kernel.org/linus/0355785313e2191be4e1108cdbda94ddb0238c48
        if '0355785313e21' not in self.lsm.commits and 'CROSS_COMPILE' in self.make_vars:
            self._ppc64le_vars['LD'] = f"{self.make_vars['CROSS_COMPILE']}ld"
        if self.lsm.version >= MIN_IAS_LNX_VER and self._llvm_version >= MIN_IAS_LLVM_VER:
            self._ppc64_vars['LLVM_IAS'] = '1'
            self._ppc64le_vars['LLVM_IAS'] = '1'

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if not self.only_test_boot:
            if 'other' in self.targets:
                self._add_otherconfig_runners()
            if 'distro' in self.targets:
                self._add_distroconfig_runners()

        return super().run()
