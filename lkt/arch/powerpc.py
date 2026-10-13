from pathlib import Path

from ..core.env import EnvInfo
from ..core.job import TestJob
from ..core.matrix import ArchMatrix
from ..core.source import LinuxSourceTree
from ..core.version import ClangVersion, LinuxVersion
from ..utils import CONFIGS

KERNEL_ARCH = 'powerpc'
CLANG_TARGET = 'powerpc64le-linux-gnu'

# https://github.com/ClangBuiltLinux/linux/issues/1418
# powerpc/32: Remove remaining .stabs annotations
# v5.17-rc2-28-g12318163737c (Mon Feb 7 21:03:10 2022 +1100)
# https://git.kernel.org/linus/12318163737cd8808d13faa6e2393774191a6182
MIN_IAS_LNX_VER = LinuxVersion(5, 18, 0)


def ppc64_be_defaults_to_elfv2(lst: LinuxSourceTree) -> bool:
    # If CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2 does not exist in the current tree,
    # the meaning changes depending on the Linux version. If the tree is newer
    # than 6.2.0 (which first shipped CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2), it
    # means that [1] has been merged, which means that ELFv2 is the only ABI
    # supported internally by the kernel. If it is not newer than 6.2.0, it
    # means ELFv1 is the only option for the internal kernel ABI.
    #
    # [1]: https://lore.kernel.org/20230505071850.228734-5-npiggin@gmail.com/
    if 'CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2' not in lst.configs:
        return lst.version >= (6, 2, 0)

    kconfig_text = lst.read_text('arch/powerpc/Kconfig')
    # powerpc/64: Force ELFv2 when building with LLVM linker
    # v6.4-rc2-35-g9d90161ca5c7 (Wed Jun 14 12:46:42 2023 +1000)
    # https://git.kernel.org/linus/9d90161ca5c7234e80e14e563d198f322ca0c1d0
    patch_1_state = '"Build big-endian kernel using ELF ABI V2 (EXPERIMENTAL)" if LD_IS_BFD'
    # powerpc/64: Make ELFv2 the default for big-endian builds
    # v6.4-rc2-36-g8c5fa3b5c4df (Wed Jun 14 12:46:42 2023 +1000)
    # https://git.kernel.org/linus/8c5fa3b5c4df3d071dab42b04b971df370d99354
    patch_2_state = '"Build big-endian kernel using ELF ABI V2" if LD_IS_BFD && EXPERT'
    return patch_1_state in kconfig_text or patch_2_state in kconfig_text


class PowerPC32Matrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(lst, env_info, targets, CLANG_TARGET, 'ppc', only_boot_testing, **kwargs)

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        if 'def' in self.targets:
            kconfig_text = self.lst.read_text('arch/powerpc/platforms/Kconfig.cputype')
            has_44x_hack = (
                '"440 (44x family)"\n\tdepends on 44x\n\tdepends on !CC_IS_CLANG' in kconfig_text
            )

            # powerpc/44x: Fix build failure with GCC 12 (unrecognized opcode: `wrteei')
            # v5.19-rc2-164-g2255411d1d0f (Wed Jul 27 21:36:06 2022 +1000)
            # https://git.kernel.org/linus/2255411d1d0f0661d1e5acd5f6edf4e6652a345a
            cbl_1814 = (
                '2255411d1d0f0661d1e5acd5f6edf4e6652a345a' in self.lst.commits and not has_44x_hack
            )

            ppc44x_job = TestJob(
                arch=KERNEL_ARCH, boot_utils_arch='ppc32', configs=['ppc44x_defconfig']
            )
            # https://github.com/ClangBuiltLinux/linux/issues/1679
            if (
                self.env_info.clang.version < (cbl_1679_fixed_ver := ClangVersion(16, 0, 0))
                and cbl_1814
            ):
                ppc44x_job.skip_build_reason = f"LLVM < {cbl_1679_fixed_ver} (using '{self.env_info.clang.version}') with 2255411d1d0f0 (from {LinuxVersion(6, 0, 0)}) present (https://github.com/ClangBuiltLinux/linux/issues/1679)"
            if self.only_boot_testing:
                ppc44x_job.make_targets.append('uImage')
            else:
                ppc44x_job.extra_make_targets.append('uImage')
            ppc44x_job.bootable = not cbl_1814
            if not ppc44x_job.bootable:
                ppc44x_job.skip_boot_reason = (
                    '"-mcpu=440" (https://github.com/ClangBuiltLinux/linux/issues/1814)'
                )
            jobs.append(ppc44x_job)

            ppc32_mac_job = TestJob(
                arch=KERNEL_ARCH,
                bootable=True,
                boot_utils_arch='ppc32_mac',
                configs=['pmac32_defconfig'],
            )
            if self.only_boot_testing:
                ppc32_mac_job.make_targets.append('vmlinux')
            # lib/xor: make xor prototypes more friendly to compiler vectorization
            # v5.17-rc1-61-g297565aa22cf (Fri Feb 11 20:39:39 2022 +1100)
            # https://git.kernel.org/linus/297565aa22cfa80ab0f88c3569693aea0b6afb6d
            if '297565aa22cfa80ab0f88c3569693aea0b6afb6d' not in self.lst.commits:
                ppc32_mac_job.skip_build_reason = f"missing 297565aa22cfa (from {LinuxVersion(5, 18, 0)}) for https://github.com/ClangBuiltLinux/linux/issues/563"
            # powerpc/pmac32: enable serial options by default in defconfig
            # v6.5-rc3-36-g0b5e06e9cb15 (Mon Aug 14 21:54:04 2023 +1000)
            # https://git.kernel.org/linus/0b5e06e9cb156e7e97bfb4e1ebf6acd62497eaf5
            if '0b5e06e9cb156e7e97bfb4e1ebf6acd62497eaf5' not in self.lst.commits:
                ppc32_mac_job.configs += [
                    'CONFIG_SERIAL_PMACZILOG=y',
                    'CONFIG_SERIAL_PMACZILOG_CONSOLE=y',
                ]
            jobs.append(ppc32_mac_job)

        if (binutils := self.env_info.binutils[KERNEL_ARCH]).location == Path():
            for job in jobs:
                if not job.skip_build_reason:
                    job.skip_build_reason = 'missing binutils'
        else:
            for job in jobs:
                job.make_vars |= {
                    'CROSS_COMPILE': binutils.tool.replace('gnu-as', 'gnu-'),
                    'LLVM_IAS': '0',
                }

        return jobs


class PowerPC64Matrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(lst, env_info, targets, CLANG_TARGET, 'ppc64', only_boot_testing, **kwargs)

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        elfv2_on_by_default = ppc64_be_defaults_to_elfv2(self.lst)

        if 'def' in self.targets:
            jobs.append(
                TestJob(
                    arch=KERNEL_ARCH,
                    bootable=True,
                    boot_utils_arch='ppc64',
                    configs=['ppc64_guest_defconfig'],
                    make_targets=['vmlinux'] if self.only_boot_testing else [],
                )
            )

            if not self.only_boot_testing:
                jobs.append(TestJob(arch=KERNEL_ARCH, configs=['ppc64_defconfig']))

        if not self.only_boot_testing and 'other' in self.targets:
            # This used to be a dynamic check but stable backported a11334d8327b3f
            # without its dependencies (breaking that), so just check for the
            # mainline version that it actually landed in.
            can_select_elfv2 = self.lst.version >= (lnx_ver_elfv2_select := LinuxVersion(6, 4, 0))

            allmod_job = TestJob(arch=KERNEL_ARCH, configs=['allmodconfig'])
            if not elfv2_on_by_default and can_select_elfv2:
                allmod_job.configs.append('CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2=y')
            elif not can_select_elfv2:
                # powerpc: Allow CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2 with ld.lld 15+
                # v6.3-rc2-10-ga11334d8327b (Wed Mar 15 00:52:10 2023 +1100)
                # https://git.kernel.org/linus/a11334d8327b3fd7987cbfb38e956a44c722d88f
                allmod_job.skip_build_reason = f"lack of a11334d8327b (from {lnx_ver_elfv2_select})"
            jobs.append(allmod_job)

            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=[config])
                for config in ('allnoconfig', 'tinyconfig')
            ]

        if (binutils := self.env_info.binutils[KERNEL_ARCH]).location == Path():
            for job in jobs:
                if not job.skip_build_reason:
                    job.skip_build_reason = 'missing binutils'
        else:
            cross_compile = binutils.tool.replace('gnu-as', 'gnu-')
            for job in jobs:
                # https://github.com/ClangBuiltLinux/linux/issues/1601
                job.make_vars['CROSS_COMPILE'] = cross_compile

                if self.lst.version < MIN_IAS_LNX_VER:
                    job.make_vars['LLVM_IAS'] = '0'
                if not elfv2_on_by_default:
                    job.make_vars |= {
                        'LD': f"{cross_compile}ld",
                        'LLVM_IAS': '0',
                    }

        return jobs


class PowerPC64LEMatrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(lst, env_info, targets, CLANG_TARGET, 'ppc64', only_boot_testing, **kwargs)

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        if 'def' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['powernv_defconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['ppc64le_guest_defconfig']),
            ]
            for job in jobs:
                job.bootable = True
                job.boot_utils_arch = 'ppc64le'
                if self.only_boot_testing:
                    job.make_targets.append('zImage.epapr')
            if not self.only_boot_testing:
                jobs.append(TestJob(arch=KERNEL_ARCH, configs=['ppc64le_defconfig']))

        if not self.only_boot_testing and 'distro' in self.targets:
            configs = [
                ('alpine', 'ppc64le'),
                ('debian', 'powerpc64le'),
                ('fedora', 'ppc64le'),
                ('opensuse', 'ppc64le'),
            ]
            for distro, config_name in configs:
                skip_build_reason = ''
                if distro in {'fedora', 'opensuse'} and self.lst.version < (5, 17, 0):
                    # Drop OpenSUSE's PowerPC configuration from 5.15
                    skip_build_reason = (
                        'https://github.com/ClangBuiltLinux/continuous-integration2/pull/775'
                    )
                jobs.append(
                    TestJob(
                        arch=KERNEL_ARCH,
                        bootable=True,
                        configs=[Path(CONFIGS, distro, f"{config_name}.config")],
                        skip_build_reason=skip_build_reason,
                    )
                )

        if (binutils := self.env_info.binutils[KERNEL_ARCH]).location == Path():
            for job in jobs:
                if not job.skip_build_reason:
                    job.skip_build_reason = 'missing binutils'
        else:
            cross_compile = binutils.tool.replace('gnu-as', 'gnu-')
            for job in jobs:
                # https://github.com/ClangBuiltLinux/linux/issues/1601
                job.make_vars['CROSS_COMPILE'] = cross_compile

                if self.lst.version < MIN_IAS_LNX_VER:
                    job.make_vars['LLVM_IAS'] = '0'

        return jobs
