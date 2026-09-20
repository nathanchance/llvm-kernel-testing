from pathlib import Path

from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree
from lkt.version import ClangVersion, Version

KERNEL_ARCH = 'arm64'
CLANG_TARGET = 'aarch64-linux-gnu'


def can_build_arm64_big_endian(lst: LinuxSourceTree, llvm_version: Version) -> bool:
    arm64_kconfig_txt = Path(lst.folder, 'arch/arm64/Kconfig').read_text(encoding='utf-8')

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


class Arm64Matrix(ArchMatrix):
    def __init__(
        self, lst: LinuxSourceTree, env_info: EnvInfo, targets: list[str], **kwargs
    ) -> None:
        super().__init__(lst, env_info, targets, CLANG_TARGET, **kwargs)

    def _add_defconfig_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = [
            TestJob(arch=KERNEL_ARCH, configs=['defconfig']),
            TestJob(arch=KERNEL_ARCH, configs=['defconfig', 'CONFIG_LTO_CLANG_THIN=y']),
        ]

        if Path(self.lst.folder, 'arch/arm64/configs/virt.config').exists():
            jobs.append(TestJob(arch=KERNEL_ARCH, configs=['virtconfig']))

        if Path(self.lst.folder, 'kernel/configs/hardening.config').exists():
            jobs.append(TestJob(arch=KERNEL_ARCH, configs=['defconfig', 'hardening.config']))

        be_job = TestJob(
            arch=KERNEL_ARCH,
            configs=['defconfig', 'CONFIG_CPU_BIG_ENDIAN=y'],
            boot_utils_arch='arm64be',
        )
        if not can_build_arm64_big_endian(self.lst, self.env_info.clang.version):
            be_job.skip_build_reason = f"LLVM < 15.0.0 (using '{self.env_info.clang.version}') or no big endian support in Linux"
        jobs.append(be_job)

        if self.lst.arch_supports_kcfi(KERNEL_ARCH):
            cfi_y_config = self.lst.get_cfi_y_config()
            # cfi: Switch to -fsanitize=kcfi
            # v6.0-rc4-5-g89245600941e (Mon Sep 26 10:13:13 2022 -0700)
            # https://git.kernel.org/linus/89245600941e4e0f87d77f60ee269b5e61ef4e49
            if '89245600941e4e0f87d77f60ee269b5e61ef4e49' in self.lst.commits:
                jobs.append(
                    TestJob(
                        arch=KERNEL_ARCH,
                        configs=['defconfig', cfi_y_config, 'CONFIG_SHADOW_CALL_STACK=y'],
                    )
                )

            jobs.append(
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=[
                        'defconfig',
                        cfi_y_config,
                        'CONFIG_LTO_CLANG_THIN=y',
                        'CONFIG_SHADOW_CALL_STACK=y',
                    ],
                )
            )
        else:
            jobs.append(
                TestJob(arch=KERNEL_ARCH, configs=['defconfig', 'CONFIG_SHADOW_CALL_STACK=y'])
            )

        for job in jobs:
            job.bootable = True

        return jobs

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        if 'def' in self.targets:
            jobs += self._add_defconfig_jobs()
        if 'other' in self.targets:
            jobs += [
                TestJob(arch=KERNEL_ARCH, configs=['allmodconfig']),
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=[
                        'allmodconfig',
                        'CONFIG_GCOV_KERNEL=n',
                        'CONFIG_KASAN=n',
                        'CONFIG_LTO_CLANG_THIN=y',
                    ],
                ),
                TestJob(arch=KERNEL_ARCH, configs=['allnoconfig']),
                TestJob(arch=KERNEL_ARCH, configs=['tinyconfig']),
            ]

        return jobs
