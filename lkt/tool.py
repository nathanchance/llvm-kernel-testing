import shutil
from pathlib import Path

import lkt.utils
from lkt.version import BinutilsVersion, ClangVersion, QemuVersion, Version


class Tool:
    def __init__(self, tool: str) -> None:
        self.tool: str = tool
        self.location: Path
        self.original_version_string: str
        self.version: Version

        if not (resolved_tool := shutil.which(self.tool)):
            self.location = Path()
            self.original_version_string = ''
            self.version = Version(0, 0, 0)
            return

        self.location = Path(resolved_tool).parent
        self.original_version_string = lkt.utils.chronic(
            [resolved_tool, '--version']
        ).stdout.splitlines()[0]

        if self.tool == 'clang':
            self.version = ClangVersion(binary=resolved_tool)
        elif self.tool.endswith('as'):
            self.version = BinutilsVersion(version_string=self.original_version_string)
        elif self.tool.startswith('qemu-system-'):
            self.version = QemuVersion(version_string=self.original_version_string)
        else:
            msg = f"Cannot parse version of {self.tool}!"
            raise RuntimeError(msg)
