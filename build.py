#!/usr/bin/env python3

from argparse import ArgumentParser
import datetime
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import lkt.report
import lkt.source
import lkt.utils

import lkt.arm
import lkt.arm64
import lkt.hexagon
import lkt.i386
import lkt.loongarch
import lkt.mips
import lkt.powerpc
import lkt.riscv
import lkt.s390
import lkt.x86_64

REPO = Path(__file__).resolve().parent
SUPPORTED_TARGETS = [
    'def',
    'distro',
    'other',
]
SUPPORTED_ARCHITECTURES = [
    'arm',
    'arm64',
    'hexagon',
    'i386',
    'mips',
    'powerpc',
    'riscv',
    's390',
    'x86_64',
]
EXPERIMENTAL_ARCHITECTURES = [
    'loongarch',
]


def parse_arguments():
    parser = ArgumentParser(description='Build a set of Linux kernels with LLVM')

    parser.add_argument('-a',
                        '--architectures',
                        choices=[*SUPPORTED_ARCHITECTURES, *EXPERIMENTAL_ARCHITECTURES],
                        default=SUPPORTED_ARCHITECTURES,
                        metavar='ARCH',
                        nargs='+',
                        help='Architectures to build for (default: %(default)s).')
    parser.add_argument(
        '-b',
        '--build-folder',
        type=str,
        help="Path to build folder (default: 'build' folder in Linux kernel source folder).")
    parser.add_argument(
        '--binutils-prefix',
        type=str,
        help=
        "Path to binutils installation (parent of 'bin' folder, default: Use binutils from PATH).")
    parser.add_argument('--boot-utils-folder',
                        type=str,
                        help='Path to boot-utils folder (default: vendored boot-utils).')
    parser.add_argument('-l',
                        '--linux-folder',
                        required=True,
                        type=str,
                        help='Path to Linux source folder (required).')
    parser.add_argument(
        '--llvm-prefix',
        type=str,
        help="Path to LLVM installation (parent of 'bin' folder, default: Use LLVM from PATH).")
    parser.add_argument('--log-folder',
                        type=str,
                        help='Folder to store log files in (default: %(default)s).')
    parser.add_argument(
        '--only-test-boot',
        action='store_true',
        help=
        'Only build configs that can be booted in QEMU and only build kernel images (no modules)')
    parser.add_argument('--save-objects',
                        action='store_true',
                        help='Save object files (default: Remove build folder).')
    parser.add_argument('-t',
                        '--targets-to-build',
                        choices=SUPPORTED_TARGETS,
                        default=SUPPORTED_TARGETS,
                        metavar='TARGETS',
                        nargs='+',
                        help='Testing targets to build (default: %(default)s).')
    parser.add_argument(
        '--tc-prefix',
        type=str,
        help=
        "Path to toolchain installation (parent of 'bin' folder, default: Use toolchain from PATH).",
    )
    parser.add_argument('--use-ccache',
                        action='store_true',
                        help='Use ccache for building (default: Do not use ccache).')
    parser.add_argument(
        '--qemu-prefix',
        type=str,
        help="Path to QEMU installation (parent of 'bin' folder, default: Use QEMU from PATH).")

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
        raise FileNotFoundError(f"Supplied Linux source folder ('{args.linux_folder}') not found?")
    lsm = lkt.source.LinuxSourceManager(linux_folder)

    if args.boot_utils_folder:
        boot_utils_folder = Path(args.boot_utils_folder).resolve()
    else:
        lkt.utils.header('Updating boot-utils')
        if not (boot_utils_folder := Path(REPO, 'src/boot-utils')).exists():
            git_clone = [
                'git',
                'clone',
                'https://github.com/ClangBuiltLinux/boot-utils',
                boot_utils_folder,
            ]
            subprocess.run(git_clone, check=True)
        git_pull = ['git', '-C', boot_utils_folder, 'pull', '--no-edit']
        subprocess.run(git_pull, check=True)

    if args.build_folder:
        build_folder = Path(args.build_folder).resolve()
    else:
        build_folder = Path(linux_folder, 'build')
    if args.log_folder:
        log_folder = Path(args.log_folder).resolve()
    else:
        log_folder = Path(REPO, 'logs', datetime.datetime.now().strftime('%Y%m%d-%H%M'))

    # Add prefixes to PATH if they exist
    path = os.environ['PATH'].split(':')
    prefixes = [args.binutils_prefix, args.llvm_prefix, args.tc_prefix, args.qemu_prefix]
    for item in prefixes:
        if not item:
            continue
        if not (prefix := Path(item)).exists():
            raise FileNotFoundError(f"Supplied prefix ('{prefix}') does not exist?")
        if not (bin_folder := Path(prefix, 'bin')).exists():
            raise FileNotFoundError(f"Supplied prefix ('{prefix}') has no 'bin' folder?")
        if (bin_folder := str(bin_folder)) not in path:
            path.insert(0, bin_folder)
    os.environ['PATH'] = ':'.join(path)

    report = lkt.report.LKTReport()
    report.folders.log = log_folder
    report.folders.source = linux_folder
    report.show_env_info()

    make_vars = {}
    if args.use_ccache and shutil.which('ccache'):
        make_vars['CC'] = 'ccache clang'
        make_vars['HOSTCC'] = 'ccache clang'
    if shutil.which('pbzip2'):
        make_vars['KBZIP2'] = 'pbzip2'
    if shutil.which('pigz'):
        make_vars['KGZIP'] = 'pigz'

    lkt_runners = {
        'arm': lkt.arm.ArmLKTRunner,
        'arm64': lkt.arm64.Arm64LKTRunner,
        'hexagon': lkt.hexagon.HexagonLKTRunner,
        'i386': lkt.i386.I386LKTRunner,
        'loongarch': lkt.loongarch.LoongArchLKTRunner,
        'mips': lkt.mips.MipsLKTRunner,
        'powerpc': lkt.powerpc.PowerPCLKTRunner,
        'riscv': lkt.riscv.RISCVLKTRunner,
        's390': lkt.s390.S390LKTRunner,
        'x86_64': lkt.x86_64.X8664LKTRunner,
    }
    results = []
    for arch in sorted(args.architectures):
        runner = lkt_runners[arch]()
        runner.folders.boot_utils = boot_utils_folder
        runner.folders.build = build_folder
        runner.folders.configs = Path(REPO, 'configs')
        runner.folders.log = log_folder
        runner.folders.source = linux_folder
        runner.lsm = lsm
        runner.make_vars.update(make_vars)
        runner.only_test_boot = args.only_test_boot
        runner.save_objects = args.save_objects
        runner.targets = args.targets_to_build
        results += runner.run()

    report.generate_report(results)
