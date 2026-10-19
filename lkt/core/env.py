import os
import platform
from pathlib import Path

import lkt.utils

from .tool import Tool

QEMU_ARCHES = (
    'arm',
    'aarch64',
    'i386',
    'loongarch64',
    'mips',
    'mipsel',
    'ppc',
    'ppc64',
    'riscv64',
    's390x',
    'x86_64',
)
BINUTILS_ARCHES: dict[str, str | tuple[str, ...]] = {
    lkt.utils.MACHINE: '',
    'powerpc': ('powerpc64le-linux-gnu-', 'powerpc64-linux-gnu-', 'powerpc64-linux-gnu-'),
    's390x': 's390x-linux-gnu-',
}


class EnvInfo:
    def __init__(self) -> None:
        self.binutils: dict[str, Tool] = {}
        for arch, value in BINUTILS_ARCHES.items():
            if not isinstance(triples := value, tuple):
                triples = (triples,)
            for triple in triples:
                self.binutils[arch] = (gnu_as := Tool(f"{triple}as"))
                if gnu_as.location != Path():
                    break
        self.clang: Tool = Tool('clang')
        self.path: str = os.getenv('PATH', 'PATH unavailable?')
        self.qemu: dict[str, Tool] = {arch: Tool(f"qemu-system-{arch}") for arch in QEMU_ARCHES}
        uname = platform.uname()
        self.uname: str = f"{uname.system} {uname.node} {uname.release} {uname.version} {uname.machine}"  # fmt: skip

    def __str__(self) -> str:
        return f"""\
clang version: {self.clang.original_version_string}
clang location: {self.clang.location}
binutils version: {self.binutils[lkt.utils.MACHINE].original_version_string}
binutils location: {self.binutils[lkt.utils.MACHINE].location}
host uname: {self.uname}
PATH: {self.path.replace(os.pathsep, ' ')}"""

    def show(self) -> None:
        lkt.utils.header('Environment information')
        print(str(self))
