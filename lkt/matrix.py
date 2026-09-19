import lkt.utils
from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.source import LinuxSourceTree


class ArchMatrix:
    def __init__(
        self, lst: LinuxSourceTree, env_info: EnvInfo, targets: list[str], clang_target: str
    ) -> None:
        self.env_info: EnvInfo = env_info
        self.lst: LinuxSourceTree = lst
        self.targets: list[str] = targets

        self.jobs: list[TestJob] = self._generate_jobs()
        if not lkt.utils.clang_supports_target(clang_target):
            for job in self.jobs:
                job.skip_build_reason = 'missing clang target'

    def _generate_jobs(self) -> list[TestJob]:
        msg = 'jobs generator not implemented!'
        raise NotImplementedError(msg)
