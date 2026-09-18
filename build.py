#!/usr/bin/env python3

import datetime
import os
import shutil
import signal
import sys
from argparse import ArgumentParser
from pathlib import Path

import lkt.utils
from lkt.env import EnvInfo
from lkt.executor import Executor
from lkt.matrix import ArchMatrix
from lkt.source import LinuxSourceTree
from lkt.version import LinuxVersion
from lkt.x86_64 import X8664Matrix

# This is the minimum version of Linux that can be used with this test
# framework due to assumptions made throughout the framework with regards to
# present commits and make variables.
MINIMUM_SUPPORTED_LINUX_VERSION = LinuxVersion(5, 15, 0)

REPO = Path(__file__).resolve().parent
SUPPORTED_TARGETS = [
    'def',
]
SUPPORTED_ARCHITECTURES = [
    'x86_64',
]
EXPERIMENTAL_ARCHITECTURES = []


def parse_arguments():
    parser = ArgumentParser(description='Build a set of Linux kernels with LLVM')

    parser.add_argument(
        '-a',
        '--architectures',
        choices=[*SUPPORTED_ARCHITECTURES, *EXPERIMENTAL_ARCHITECTURES],
        default=SUPPORTED_ARCHITECTURES,
        metavar='ARCH',
        nargs='+',
        help='Architectures to build for (default: %(default)s).',
    )
    parser.add_argument(
        '-b',
        '--build-folder',
        type=str,
        help="Path to build folder (default: 'build' folder in Linux kernel source folder).",
    )
    parser.add_argument(
        '--binutils-prefix',
        type=str,
        help="Path to binutils installation (parent of 'bin' folder, default: Use binutils from PATH).",
    )
    parser.add_argument(
        '--boot-utils-folder',
        type=str,
        help='Path to boot-utils folder (default: vendored boot-utils).',
    )
    parser.add_argument(
        '-l',
        '--linux-folder',
        required=True,
        type=str,
        help='Path to Linux source folder (required).',
    )
    parser.add_argument(
        '--llvm-prefix',
        type=str,
        help="Path to LLVM installation (parent of 'bin' folder, default: Use LLVM from PATH).",
    )
    parser.add_argument(
        '--only-test-boot',
        action='store_true',
        help='Only build configs that can be booted in QEMU and only build kernel images (no modules)',
    )
    parser.add_argument(
        '--output-folder', type=str, help='Folder to store output files in (default: %(default)s).'
    )
    parser.add_argument(
        '--save-objects',
        action='store_true',
        help='Save object files (default: Remove build folder).',
    )
    parser.add_argument(
        '-t',
        '--targets-to-build',
        choices=SUPPORTED_TARGETS,
        default=SUPPORTED_TARGETS,
        metavar='TARGETS',
        nargs='+',
        help='Testing targets to build (default: %(default)s).',
    )
    parser.add_argument(
        '--tc-prefix',
        type=str,
        help="Path to toolchain installation (parent of 'bin' folder, default: Use toolchain from PATH).",
    )
    parser.add_argument(
        '--use-ccache',
        action='store_true',
        help='Use ccache for building (default: Do not use ccache).',
    )
    parser.add_argument(
        '--qemu-prefix',
        type=str,
        help="Path to QEMU installation (parent of 'bin' folder, default: Use QEMU from PATH).",
    )

    return parser.parse_args()


def interrupt_handler(_signum, _frame):
    """
    Causes Ctrl-C to exit with a non-zero error code.
    """
    sys.exit(130)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, interrupt_handler)

    args = parse_arguments()

    # Folders
    if not (linux_folder := Path(args.linux_folder).resolve()).exists():
        msg = f"Supplied Linux source folder ('{args.linux_folder}') not found?"
        raise FileNotFoundError(msg)
    lst = LinuxSourceTree(linux_folder)

    if args.boot_utils_folder:
        boot_utils_folder = Path(args.boot_utils_folder).resolve()
    else:
        lkt.utils.header('Updating boot-utils')
        if not (boot_utils_folder := Path(REPO, 'src/boot-utils')).exists():
            lkt.utils.run(
                [
                    'git',
                    'clone',
                    'https://github.com/ClangBuiltLinux/boot-utils',
                    boot_utils_folder,
                ]
            )
        lkt.utils.run(['git', 'pull', '--no-edit'], cwd=boot_utils_folder)

    if args.build_folder:
        build_folder = Path(args.build_folder).resolve()
    else:
        build_folder = Path(linux_folder, 'build')
    if args.output_folder:
        output_folder = Path(args.output_folder).resolve()
    else:
        output_folder = Path(
            REPO, 'output', datetime.datetime.now(datetime.UTC).strftime('%Y%m%d-%H%M')
        )

    # Add prefixes to PATH if they exist
    path = os.environ['PATH'].split(':')
    prefixes = [args.binutils_prefix, args.llvm_prefix, args.tc_prefix, args.qemu_prefix]
    for item in prefixes:
        if not item:
            continue
        if not (prefix := Path(item)).exists():
            msg = f"Supplied prefix ('{prefix}') does not exist?"
            raise FileNotFoundError(msg)
        if not (bin_folder := Path(prefix, 'bin')).exists():
            msg = f"Supplied prefix ('{prefix}') has no 'bin' folder?"
            raise FileNotFoundError(msg)
        if (bin_folder := str(bin_folder)) not in path:
            path.insert(0, bin_folder)
    os.environ['PATH'] = ':'.join(path)
    env_info = EnvInfo()

    arch_to_matrix: dict[str, type] = {
        'x86_64': X8664Matrix,
    }
    matrices: list[ArchMatrix] = [
        arch_to_matrix[arch](lst=lst, env_info=env_info, targets=args.targets_to_build)
        for arch in args.architectures
    ]
    executor = Executor(
        matrices=matrices,
        lst=lst,
        env_info=env_info,
        boot_utils_folder=boot_utils_folder,
        build_folder=build_folder,
        output_folder=output_folder,
        only_boot_testing=args.only_test_boot,
        save_objects=args.save_objects,
    )
    if args.use_ccache and shutil.which('ccache'):
        executor.make_vars['CC'] = 'ccache clang'
        executor.make_vars['HOSTCC'] = 'ccache clang'

    executor.run()
