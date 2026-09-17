from lkt.env import EnvInfo
from lkt.job import TestJob
from lkt.source import LinuxSourceTree

class ArchMatrix:
    def __init__(self, lst: LinuxSourceTree, env_info: EnvInfo) -> None:
        self.env_info: EnvInfo = env_info
        self.jobs: list[TestJob] = []
        self.lst: LinuxSourceTree = lst
