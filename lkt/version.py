import os
import re
import shutil
from functools import total_ordering
from pathlib import Path

import lkt.utils

DEFAULT_VERSION = (0, 0, 0)
VersionTuple = tuple[int, ...]
VersionIterator = list[str] | VersionTuple


@total_ordering
class Version:
    def __init__(self, *args, **kwargs) -> None:

        if len(args) > 0:
            self._key: VersionTuple = tuple(args)
        else:
            self._key: VersionTuple = self._gen_key(**kwargs)

    @staticmethod
    def _is_valid_operand(other: object) -> bool:
        return isinstance(other, (tuple, Version))

    @staticmethod
    def _get_key(other: object) -> tuple:
        if isinstance(other, tuple):
            return other
        if isinstance(other, Version):
            # pylint: disable-next=protected-access
            return other._key  # noqa: SLF001
        raise ValueError('Cannot get _key?')

    def _gen_key(self, **kwargs) -> VersionTuple:
        return tuple(map(int, self._gen_ver_iter(**kwargs)))

    def _gen_ver_iter(self, **kwargs) -> VersionIterator:
        raise NotImplementedError('Version has no generate version iterator method')

    def __eq__(self, other: object) -> bool:
        if not self._is_valid_operand(other):
            return NotImplemented
        return self._key == self._get_key(other)

    def __getitem__(self, item: int) -> int:
        return self._key[item]

    def __hash__(self):
        return hash(self._key)

    def __lt__(self, other: object) -> bool:
        if not self._is_valid_operand(other):
            return NotImplemented
        return self._key < self._get_key(other)

    def __repr__(self) -> str:
        return f"{type(self).__name__}{self._key}"

    def __str__(self) -> str:
        return '.'.join(map(str, self._key))


class BinutilsVersion(Version):
    def _gen_ver_iter(self, **kwargs) -> VersionIterator:
        binary: Path | str = kwargs.get('binary', 'as')

        if not shutil.which(binary):
            return DEFAULT_VERSION

        as_output = lkt.utils.chronic([binary, '--version']).stdout.splitlines()[0]
        # "GNU assembler (GNU Binutils) 2.39.50.20221024" -> "2.39.50.20221024" -> ['2', '39', '50']
        # "GNU assembler version 2.39-3.fc38" -> "2.39-3.fc38" -> ['2.39'] -> ['2', '39'] -> ['2', '39', '0']
        as_iter = as_output.split(' ')[-1].split('-')[0].split('.')[0:3]
        if len(as_iter) == 2:
            as_iter.append('0')

        return as_iter


class ClangVersion(Version):
    def _gen_ver_iter(self, **kwargs) -> VersionIterator:
        binary: Path | str = kwargs.get('binary', 'clang')

        if not shutil.which(binary):
            return DEFAULT_VERSION

        clang_cmd = [binary, '-E', '-P', '-x', 'c', '-']
        clang_input = '__clang_major__ __clang_minor__ __clang_patchlevel__'

        return lkt.utils.chronic(clang_cmd, input=clang_input).stdout.strip().split(' ')


class LinuxVersion(Version):
    def _gen_ver_iter(self, **kwargs) -> VersionIterator:
        folder: Path = kwargs.get('folder', Path.cwd())

        if not Path(folder, 'Makefile').exists():
            raise RuntimeError(
                f"Provided kernel source ('{folder}') does not look like a Linux kernel tree?"
            )

        output = lkt.utils.chronic(['make', '-s', 'kernelversion'], cwd=folder).stdout.strip()
        return output.split('-', 1)[0].split('.')


class MinToolVersion(Version):
    def _gen_ver_iter(self, **kwargs) -> VersionIterator:
        folder: Path = kwargs.get('folder', Path.cwd())
        arch: str = kwargs['arch']
        tool: str = kwargs.get('tool', 'llvm')

        if not (min_tool_ver := Path(folder, 'scripts/min-tool-version.sh')).exists():
            return DEFAULT_VERSION  # minimum versions were not codified yet

        cmd_env = {}
        if arch:
            cmd_env['SRCARCH'] = arch

        return (
            lkt.utils.chronic(
                [min_tool_ver, tool],
                env={
                    **os.environ,
                    **cmd_env,
                },
            )
            .stdout.strip()
            .split('.')
        )


class QemuVersion(Version):
    def _gen_ver_iter(self, **kwargs) -> VersionIterator:
        arch: str = kwargs.get('arch', 'x86_64')

        if not shutil.which(binary := f"qemu-system-{arch}"):
            return DEFAULT_VERSION

        qemu_ver = lkt.utils.chronic([binary, '--version']).stdout.splitlines()[0]
        if not (match := re.search(r'version (\d+\.\d+.\d+)', qemu_ver)):
            raise RuntimeError('Could not find QEMU version?')

        return match.groups()[0].split('.')
