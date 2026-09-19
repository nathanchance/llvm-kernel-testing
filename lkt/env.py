import os
import platform

import lkt.utils
from lkt.tool import Tool

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


class EnvInfo:
    def __init__(self) -> None:
        self.binutils: Tool = Tool('as')
        self.clang: Tool = Tool('clang')
        self.path: str = os.getenv('PATH', 'PATH unavailable?')
        self.qemu: dict[str, Tool] = {arch: Tool(f"qemu-system-{arch}") for arch in QEMU_ARCHES}
        uname = platform.uname()
        self.uname: str = f"{uname.system} {uname.node} {uname.release} {uname.version} {uname.machine}"  # fmt: skip

    def __str__(self) -> str:
        return f"""\
clang version: {self.clang.original_version_string}
clang location: {self.clang.location}
binutils version: {self.binutils.original_version_string}
binutils location: {self.binutils.location}
host uname: {self.uname}
PATH: {self.path.replace(os.pathsep, ' ')}"""

    def show(self) -> None:
        lkt.utils.header('Environment information')
        print(str(self))
