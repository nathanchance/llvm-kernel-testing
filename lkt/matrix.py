from pathlib import Path

import lkt.utils
from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.source import LinuxSourceTree


class ArchMatrix:
    def __init__(
        self,
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        targets: list[str],
        clang_target: str,
        qemu_arch: str,
    ) -> None:
        self.env_info: EnvInfo = env_info
        self.lst: LinuxSourceTree = lst
        self.targets: list[str] = targets

        self.jobs: list[TestJob] = self._generate_jobs()

        if not lkt.utils.clang_supports_target(clang_target):
            for job in self.jobs:
                if not job.skip_build_reason:
                    job.skip_build_reason = 'missing clang target'

        if env_info.qemu[qemu_arch].location == Path():
            for job in self.jobs:
                if job.bootable and not job.skip_boot_reason:
                    job.skip_boot_reason = f"missing qemu-system-{qemu_arch}"

    def _generate_jobs(self) -> list[TestJob]:
        msg = 'jobs generator not implemented!'
        raise NotImplementedError(msg)
