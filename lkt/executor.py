from pathlib import Path

from lkt.job import TestJob
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree

class Executor:
    def __init__(self, matrix: list[ArchMatrix], lst: LinuxSourceTree, boot_utils_folder: Path, build_folder: Path, output_folder: Path, only_boot_testing: bool = False, save_objects: bool = False) -> None:
        self.jobs: list[TestJob] = [*item.jobs for item in matrix]
        self.lst: LinuxSourceTree = lst
        self.boot_utils_folder: Path = boot_utils_folder
        self.build_folder: Path = build_folder
        self.logs_folder: Path = Path(output_folder, 'logs')
        self.only_boot_testing: bool = only_boot_testing
        self.results_folder: Path = Path(output_folder, 'results')
        self.save_objects: bool = save_objects
