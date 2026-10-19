from ..core.env import EnvInfo
from ..core.job import TestJob
from ..core.matrix import ArchMatrix
from ..core.source import LinuxSourceTree
from ..core.version import LinuxVersion

KERNEL_ARCH = 'hexagon'
CLANG_TARGET = 'hexagon-linux-musl'


class HexagonMatrix(ArchMatrix):
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        only_boot_testing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(lst, env_info, targets, CLANG_TARGET, '', only_boot_testing, **kwargs)

    def _generate_jobs(self) -> list[TestJob]:
        jobs: list[TestJob] = []

        if 'def' in self.targets:
            jobs += [
                TestJob(
                    arch=KERNEL_ARCH,
                    configs=['defconfig'],
                    skip_build_reason='only testing boot' if self.only_boot_testing else '',
                ),
            ]

        if self.only_boot_testing:
            return jobs

        if 'other' in self.targets:
            job = TestJob(arch=KERNEL_ARCH, configs=['allmodconfig'])
            # ffb92ce826fd8 landed in 5.16 but it had 'Cc: stable', so we need
            # to check for its presence. However, just checking for that is no
            # longer sufficient, as arch/hexagon/lib/io.c is getting removed in
            # 6.13, which breaks the check in lkt/source.py:
            # (https://git.kernel.org/linus/a8cb1e92d29096b1fe58ef6fdcee699196eac1bd
            if (
                self.lst.version < (ffb92ce826fd8_ver := LinuxVersion(5, 16, 0))
                and 'ffb92ce826fd801acb0f4e15b75e4ddf0d189bde' not in self.lst.commits
            ):
                job.skip_build_reason = f"lack of ffb92ce826fd8 (from {ffb92ce826fd8_ver})"
            # https://github.com/llvm/llvm-project/issues/80185#issuecomment-2187294487
            if self.env_info.clang.version[0] == 19:
                job.configs.append('CONFIG_FORTIFY_KUNIT_TEST=n')
            jobs.append(job)

        return jobs
