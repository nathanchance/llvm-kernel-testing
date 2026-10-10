from pathlib import Path

import lkt.utils

from ..core.env import EnvInfo
from ..core.job import TestJob
from ..core.matrix import ArchMatrix
from ..core.source import LinuxSourceTree
from ..core.version import LinuxVersion, QemuVersion

KERNEL_ARCH = 's390'
CLANG_TARGET = 's390x-linux-gnu'
CROSS_COMPILE = f"{CLANG_TARGET}-"
QEMU_ARCH = 's390x'

# QEMU needs to contain at least https://gitlab.com/qemu-project/qemu/-/commit/c23908305b3ce7a547b0981eae549f36f756b950
# which comes from this series: https://lore.kernel.org/all/20210108132049.8501-1-david@redhat.com/
MIN_QEMU_VER = QemuVersion(6, 0, 0)

# https://git.kernel.org/torvalds/l/8218827b73c6e41029438a2d3cc573286beee914
MIN_IAS_LNX_VER = LinuxVersion(5, 19, 0)


class S390Matrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            lst, env_info, targets, CLANG_TARGET, QEMU_ARCH, only_boot_testing, **kwargs
        )

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        if 'def' in self.targets:
            jobs.append(
                TestJob(
                    arch=KERNEL_ARCH,
                    bootable=True,
                    configs=['defconfig'],
                    make_targets=['bzImage'] if self.only_boot_testing else [],
                )
            )

        if not self.only_boot_testing and 'other' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=[otherconfig])
                for otherconfig in ('allmodconfig', 'allnoconfig', 'tinyconfig')
            ]

        if not self.only_boot_testing and 'distro' in self.targets:
            jobs += [
                TestJob(
                    arch=KERNEL_ARCH,
                    bootable=True,
                    configs=[Path(lkt.utils.CONFIGS, distro, 's390x.config')],
                )
                for distro in ('alpine', 'debian', 'fedora', 'opensuse')
            ]

        make_vars: lkt.utils.MakeVars = {}

        lld_res = lkt.utils.chronic(['ld.lld', '-m', 'elf64_s390'], check=False)
        no_s390_support_in_lld = 'error: unknown emulation:' in lld_res.stderr
        # https://lore.kernel.org/20240207-s390-lld-and-orphan-warn-v1-11-8a665b3346ab@kernel.org/
        s390_makefile_txt = self.lst.read_text('arch/s390/Makefile')
        no_s390_kernel_support_for_lld = '-z notext' not in s390_makefile_txt
        if no_s390_support_in_lld or no_s390_kernel_support_for_lld:
            make_vars['LD'] = f"{CROSS_COMPILE}ld"

        # https://github.com/llvm/llvm-project/pull/81841
        objcopy_res = lkt.utils.chronic(
            ['llvm-objcopy', '-I', 'binary', '-O', 'elf64-s390', '-', '/dev/null'],
            check=False,
            input='',
        )
        no_s390_support_in_llvm_objcopy = 'error: invalid output format:' in objcopy_res.stderr
        # https://github.com/ClangBuiltLinux/linux/issues/1996
        s390_boot_makefile_txt = self.lst.read_text('arch/s390/boot/Makefile')
        have_broken_info_bin = (
            '--set-section-flags .vmlinux.info=alloc,load' not in s390_boot_makefile_txt
        )
        if no_s390_support_in_llvm_objcopy or have_broken_info_bin:
            make_vars['OBJCOPY'] = f"{CROSS_COMPILE}objcopy"

        # https://github.com/ClangBuiltLinux/linux/issues/859
        have_objdump_t_j_wa = r' | grep "\s$*\s\+" | ' in s390_boot_makefile_txt
        if not have_objdump_t_j_wa:
            make_vars['OBJDUMP'] = f"{CROSS_COMPILE}objdump"

        if self.lst.version < MIN_IAS_LNX_VER:
            make_vars['CROSS_COMPILE'] = CROSS_COMPILE
            make_vars['LLVM_IAS'] = '0'

        if make_vars:
            binutils = self.env_info.binutils[QEMU_ARCH]
            if binutils.location == Path():
                for job in jobs:
                    job.skip_build_reason = 'missing binutils'
            elif (
                'LD' in make_vars
                and binutils.version >= (2, 39, 50)
                and '80ddf5ce1c9291cb175d52ed1227134ad48c47ee' not in self.lst.commits
            ):
                for job in jobs:
                    job.skip_build_reason = 'linker error with CONFIG_RELOCATABLE=n (https://github.com/ClangBuiltLinux/linux/issues/1747)'
            else:
                for job in jobs:
                    job.make_vars |= make_vars

        if (qemu_ver := self.env_info.qemu[QEMU_ARCH].version) < MIN_QEMU_VER:
            for job in jobs:
                if job.bootable:
                    job.bootable = False
                    job.skip_boot_reason = f"QEMU < {MIN_QEMU_VER} (found '{qemu_ver}')"

        return jobs
