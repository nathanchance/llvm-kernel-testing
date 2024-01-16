#!/usr/bin/env python3

from functools import total_ordering
import os
from pathlib import Path
import re
import shutil

import lkt.utils

DEFAULT_VERSION = (0, 0, 0)


@total_ordering
class Version:

    def __init__(self, *args, **kwargs):

        if len(args) > 0:
            self._key = tuple(args)
        else:
            self._key = self._gen_key(**kwargs)

    def _is_valid_operand(self, other):
        return isinstance(other, (tuple, Version))

    def _get_key(self, other):
        if isinstance(other, tuple):
            return other
        # pylint: disable-next=protected-access
        return other._key  # noqa: SLF001

    def _gen_key(self, **kwargs):
        return tuple(map(int, self._gen_ver_iter(**kwargs)))

    def _gen_ver_iter(self):
        raise NotImplementedError('Version has no generate version iterator method')

    def __eq__(self, other):
        if not self._is_valid_operand(other):
            return NotImplemented
        return self._key == self._get_key(other)

    def __lt__(self, other):
        if not self._is_valid_operand(other):
            return NotImplemented
        return self._key < self._get_key(other)

    def __repr__(self):
        return f"{type(self).__name__}{self._key}"

    def __str__(self):
        return '.'.join(map(str, self._key))


class BinutilsVersion(Version):

    def _gen_ver_iter(self, binary='as'):
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

    def _gen_ver_iter(self, binary='clang'):
        if not shutil.which(binary):
            return DEFAULT_VERSION

        clang_cmd = [binary, '-E', '-P', '-x', 'c', '-']
        clang_input = '__clang_major__ __clang_minor__ __clang_patchlevel__'

        return lkt.utils.chronic(clang_cmd, input=clang_input).stdout.strip().split(' ')


class LinuxVersion(Version):

    def _gen_ver_iter(self, folder=None):
        if not folder:
            folder = Path.cwd()

        if not Path(folder, 'Makefile').exists():
            raise RuntimeError(
                f"Provided kernel source ('{folder}') does not look like a Linux kernel tree?")

        output = lkt.utils.chronic(['make', '-s', 'kernelversion'], cwd=folder).stdout.strip()
        return output.split('-', 1)[0].split('.')


class MinToolVersion(Version):

    def _gen_ver_iter(self, **kwargs):
        folder = kwargs['folder'] if 'folder' in kwargs else Path.cwd()
        arch = kwargs['arch'] if 'arch' in kwargs else None
        tool = kwargs['tool'] if 'tool' in kwargs else 'llvm'

        if not (min_tool_ver := Path(folder, 'scripts/min-tool-version.sh')).exists():
            return DEFAULT_VERSION  # minimum versions were not codified yet

        cmd_env = {}
        if arch:
            cmd_env['SRCARCH'] = arch

        return lkt.utils.chronic([min_tool_ver, tool], env={
            **os.environ,
            **cmd_env,
        }).stdout.strip().split('.')


class QemuVersion(Version):

    def _gen_ver_iter(self, arch='x86_64'):
        if not shutil.which(binary := f"qemu-system-{arch}"):
            return DEFAULT_VERSION

        qemu_ver = lkt.utils.chronic([binary, '--version']).stdout.splitlines()[0]
        if not (match := re.search(r'version (\d+\.\d+.\d+)', qemu_ver)):
            raise RuntimeError('Could not find QEMU version?')

        return match.groups()[0].split('.')
