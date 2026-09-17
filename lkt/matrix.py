from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.source import LinuxSourceTree


class ArchMatrix:
    def __init__(self, lst: LinuxSourceTree, env_info: EnvInfo, targets: list[str]) -> None:
        self.env_info: EnvInfo = env_info
        self.lst: LinuxSourceTree = lst
        self.targets: list[str] = targets

        self.jobs: list[TestJob] = self._generate_jobs()

    def _generate_jobs(self) -> list[TestJob]:
        msg = 'jobs generator not implemented!'
        raise NotImplementedError(msg)
