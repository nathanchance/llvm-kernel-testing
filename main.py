#!/usr/bin/env python3

from argparse import ArgumentParser
from datetime import datetime
from os import environ, SEEK_END
from pathlib import Path
from re import search
from shutil import which
from signal import signal, SIGINT
from subprocess import run
from time import time

from arm import ARM
from arm64 import ARM64
from hexagon import HEXAGON
from i386 import I386
from mips import MIPS
from powerpc import POWERPC
from riscv import RISCV
from s390 import S390
from x86_64 import X86_64

import lib

base_folder = Path(__file__).resolve().parent
supported_targets = ['def', 'other', 'distro']
supported_architectures = [
    'arm', 'arm64', 'hexagon', 'i386', 'mips', 'powerpc', 'riscv', 's390', 'x86_64'
]


class ArchitectureFactory:

    def get(self, arch, cfg):
        if arch == "arm":
            return ARM(cfg)
        if arch == "arm64":
            return ARM64(cfg)
        if arch == "hexagon":
            return HEXAGON(cfg)
        if arch == "i386":
            return I386(cfg)
        if arch == "mips":
            return MIPS(cfg)
        if arch == "powerpc":
            return POWERPC(cfg)
        if arch == "riscv":
            return RISCV(cfg)
        if arch == "s390":
            return S390(cfg)
        if arch == "x86_64":
            return X86_64(cfg)


def add_to_path(folder):
    """
    Adds <folder> + "/bin" to PATH if it exists.

    Parameters:
        folder (str): A string containing the folder whose bin folder should be
                      added to PATH.
    """
    if folder:
        folder = Path(folder)
        if not folder.exists():
            raise FileNotFoundError(f"Supplied folder ('{folder}') does not exist?")
        bin_folder = folder.joinpath("bin")
        if not bin_folder.exists():
            raise FileNotFoundError(
                f"Supplied folder ('{folder}') does not have a 'bin' folder in it?")
        if not bin_folder.as_posix() in environ['PATH']:
            environ['PATH'] = f"{bin_folder}:" + environ['PATH']


def build_kernels(cfg):
    """
    Calls the build() method for all requested architectures after verifying
    that clang supports the given architecture.

    Parameters:
        cfg (dict): Global configuration dictionary
    """
    arch_factory = ArchitectureFactory()
    for arch_name in cfg["architectures"]:
        arch = arch_factory.get(arch_name, cfg)

        if not arch.clang_supports_target():
            lib.header(f"Skipping {arch_name} kernels")
            print(f"Reason: clang was not configured with this target")
            lib.log(cfg, f"{arch_name} kernels skipped due to missing clang target")
            continue

        arch.build(cfg)


def check_for_commits(linux_folder):
    """
    Checks the Linux kernel tree for certain commits.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel soruce
                             tree.

    Returns:
        A list of commits present for future processing.
    """
    commits_present = []

    if linux_folder.joinpath("scripts", "Makefile.clang").exists():
        commits_present += ["6f5b41a2f5a63"]

    return commits_present


def check_for_configs(linux_folder):
    """
    Checks the Linux kernel tree for certain configuration options.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel soruce
                             tree.

    Returns:
        A list of configurations present for future processing.
    """
    configs_present = []

    with open(linux_folder.joinpath("arch", "Kconfig")) as f:
        file_text = f.read()
        for config in ["LTO_CLANG_THIN", "CFI_CLANG"]:
            if search(f"config {config}", file_text):
                configs_present += [f"CONFIG_{config}"]

    with open(linux_folder.joinpath("init", "Kconfig")) as f:
        file_text = f.read()
        for config in ["WERROR"]:
            if search(f"config {config}", file_text):
                configs_present += [f"CONFIG_{config}"]

    return configs_present


def clone_update_boot_utils(boot_utils_folder):
    """
    Clones and updates boot-utils if necessary.

    Parameters:
        boot_utils_folder (Path): A Path object pointing to boot-utils repository.
    """
    if not boot_utils_folder.exists():
        boot_utils_folder.parent.mkdir(exist_ok=True, parents=True)
        git_clone = [
            "git", "clone", "https://github.com/ClangBuiltLinux/boot-utils", boot_utils_folder
        ]
        run(git_clone, check=True)
    git_pull = ["git", "-C", boot_utils_folder, "pull", "--no-edit"]
    run(git_pull, check=True)


def format_logs(cfg):
    """
    Trim all log files of trailing new lines and remove the full path to the
    Linux source folder for readability's sake.

    Parameters:
        cfg (dict): Global configuration dictionary
    """
    str_to_remove = cfg["linux_folder"].as_posix() + "/"
    logs = cfg["logs"]

    for key, file in logs.items():
        if Path(file).exists():
            # Trim trailing new line by truncating by one byte.
            with open(file, "rb+") as f:
                f.seek(-1, SEEK_END)
                f.truncate()

            # Replace all instances of the Linux source folder with nothing, as
            # if building in tree.
            with open(file) as f:
                old_log = f.read()
                new_log = old_log.replace(str_to_remove, "")
            with open(file, "w") as f:
                f.write(new_log)


def initial_config_and_setup(args):
    """
    Sets up the global configuration and  performs a few initial setup actions
    based on user input.

    Parameters:
        args (Namespace): The Namespace object returned from parse_arguments()

    Returns:
        cfg (dict): A dictionary of configuration values
    """
    linux_folder = Path(args.linux_folder)
    if not linux_folder.exists():
        raise FileNotFoundError(
            f"Supplied Linux source folder ('{linux_folder}') could not be found!")

    log_folder = Path(args.log_folder)

    # Ensure log folder is created for future writing
    log_folder.mkdir(exist_ok=True, parents=True)

    cfg = {
        "architectures": args.architectures,
        "commits_present": check_for_commits(linux_folder),
        "configs_folder": base_folder.joinpath("configs"),
        "configs_present": check_for_configs(linux_folder),
        "linux_folder": linux_folder,
        "log_folder": log_folder,
        "logs": {},
        "targets_to_build": args.targets_to_build,
        "save_objects": args.save_objects,
    }

    for log in ['failed', 'info', 'skipped', 'success']:
        cfg["logs"][log] = log_folder.joinpath(f"{log}.log")

    for prefix in [args.binutils_prefix, args.llvm_prefix, args.tc_prefix, args.qemu_prefix]:
        add_to_path(prefix)

    build_folder = args.build_folder
    if not build_folder:
        build_folder = linux_folder.joinpath("build")
    cfg["build_folder"] = Path(build_folder)

    # Ensure PATH has been updated with proper folders above before creating
    # these.
    cfg["linux_version_code"] = lib.create_linux_version_code(linux_folder)
    cfg["llvm_version_code"] = lib.create_llvm_version_code()

    boot_utils_folder = Path(args.boot_utils_folder)
    if lib.is_relative_to(boot_utils_folder, base_folder):
        lib.header("Updating boot-utils")
        clone_update_boot_utils(boot_utils_folder)
    cfg["boot_utils_folder"] = boot_utils_folder

    make_variables = {}
    if args.use_ccache and which("ccache"):
        make_variables["CC"] = "ccache clang"
        make_variables["HOSTCC"] = "ccache clang"
    if which("pbzip2"):
        make_variables["KBZIP2"] = "pbzip2"
    if which("pigz"):
        make_variables["KGZIP"] = "pigz"
    cfg["make_variables"] = make_variables

    return cfg


def interrupt_handler(signum, frame):
    """
    Causes Ctrl-C to exit with a non-zero error code. Parameters are ignored so
    they are explicitly undocumented.
    """
    exit(130)


def parse_arguments():
    """
    Parses arguments to script.

    Returns:
        A Namespace object containing key values from parser.parse_args()
    """
    parser = ArgumentParser()

    parser.add_argument("-a",
                        "--architectures",
                        choices=supported_architectures,
                        default=supported_architectures,
                        metavar="ARCH",
                        nargs="+",
                        help="Architectures to build for (default: %(default)s).")
    parser.add_argument(
        "-b",
        "--build-folder",
        type=str,
        help="Path to build folder (default: 'build' folder in Linux kernel source folder).")
    parser.add_argument(
        "--binutils-prefix",
        type=str,
        help=
        "Path to binutils installation (parent of 'bin' folder, default: Use binutils from PATH).")
    parser.add_argument("--boot-utils-folder",
                        default=base_folder.joinpath("src", "boot-utils"),
                        type=str,
                        help="Path to boot-utils folder (default: %(default)s).")
    parser.add_argument("-l",
                        "--linux-folder",
                        required=True,
                        type=str,
                        help="Path to Linux source folder (required).")
    parser.add_argument(
        "--llvm-prefix",
        type=str,
        help="Path to LLVM installation (parent of 'bin' folder, default: Use LLVM from PATH).")
    parser.add_argument("--log-folder",
                        default=base_folder.joinpath("logs",
                                                     datetime.now().strftime("%Y%m%d-%H%M")),
                        type=str,
                        help="Folder to store log files in (default: %(default)s).")
    parser.add_argument("--save-objects",
                        action="store_true",
                        help="Save object files (default: Remove build folder).")
    parser.add_argument("-t",
                        "--targets-to-build",
                        choices=supported_targets,
                        default=supported_targets,
                        metavar="TARGETS",
                        nargs="+",
                        help="Testing targets to build (default: %(default)s).")
    parser.add_argument(
        "--tc-prefix",
        type=str,
        help=
        "Path to toolchain installation (parent of 'bin' folder, default: Use toolchain from PATH)."
    )
    parser.add_argument("--use-ccache",
                        action="store_true",
                        help="Use ccache for building (default: Do not use ccache).")
    parser.add_argument(
        "--qemu-prefix",
        type=str,
        help="Path to QEMU installation (parent of 'bin' folder, default: Use QEMU from PATH).")

    return parser.parse_args()


def pretty_print_log(log_file):
    """
    Prints a log file with no empty spaces.

    Parameters:
        log_file (Path): A Path object pointing to the log file to print.
    """
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                print(line)


def report_results(cfg, start_time):
    """
    Prints results of builds based on logs in a specific format.

    Parameters:
        cfg (dict): Global configuration dictionary
        start_time (int): Intial time that the script started running.
    """
    lib.log(cfg, f"Total script runtime: {lib.get_time_diff(start_time, time())}")
    format_logs(cfg)

    logs = cfg["logs"]

    header_strs = {
        "info": "Toolchain, kernel, and runtime information",
        "success": "List of successful tests",
        "failed": "List of failed tests",
        "skipped": "List of skipped tests",
    }
    for key, log_str in header_strs.items():
        log_file = logs[key]
        if log_file.exists():
            lib.header(log_str)
            if key == "info":
                with open(log_file) as f:
                    print(f.read().strip())
            else:
                pretty_print_log(log_file)


def tc_lnx_env_info(cfg):
    """
    Write toolchain, Linux, and environment information to log file then show it to the user.

    Parameters:
        cfg (dict): Global configuration dictionary
    """
    lib.header("Build information")

    log_file = cfg["logs"]["info"]

    binutils_version, binutils_location = lib.get_binary_info("as")
    clang_version, clang_location = lib.get_binary_info("clang")
    linux_location = cfg["linux_folder"]
    linux_version = lib.get_linux_version(linux_location)
    path = environ['PATH']

    with open(log_file, "w") as f:
        f.write(f"{clang_version}\n")
        f.write(f"clang location: {clang_location}\n")
        f.write(f"binutils version: {binutils_version}\n")
        f.write(f"binutils location: {binutils_location}\n")
        f.write(f"{linux_version}")
        f.write(f"Linux source location: {linux_location}\n")
        f.write(f"PATH: {path}\n\n")

    with open(log_file) as f:
        print(f.read().strip())


if __name__ == '__main__':
    signal(SIGINT, interrupt_handler)

    start_time = time()

    args = parse_arguments()
    cfg = initial_config_and_setup(args)

    tc_lnx_env_info(cfg)

    build_kernels(cfg)

    report_results(cfg, start_time)
