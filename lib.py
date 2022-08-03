#!/usr/bin/env python3

from collections import OrderedDict
from datetime import timedelta
from os import sched_getaffinity
from pathlib import Path
from shutil import rmtree, which
from subprocess import DEVNULL, PIPE, Popen, run, STDOUT
from sys import stdout
from tempfile import mkstemp
from time import time

def boot_qemu(cfg, arch, log_str, build_folder, kernel_available):
    """
    Boots a kernel in QEMU using 'boot-qemu.py'.

    Parameters:
        cfg (dict): Global configuration dictionary.
        arch (str): Architecture to boot (according to 'boot-qemu.py').
        log_str (str): String to use to use in log file to describe boot.
        build_folder (Path): A Path object pointing to the location of the build folder.
        kernel_available (bool): Whether or not kernel was successfully built.
    """
    if kernel_available:
        boot_qemu_py = cfg["boot_utils"].joinpath("boot-qemu.py").as_posix()
        cmd = [boot_qemu_py, "-a", arch, "-k", build_folder.as_posix()]
        pretty_print_cmd(cmd)
        result = run(cmd)
        if result.returncode == 0:
            result_str = "successful"
        else:
            result_str = "failed"
    else:
        result_str = "skipped"
    log(cfg, f"{log_str} qemu boot {result_str}")

def capture_cmd(cmd, cwd=None, input=None):
    """
    Capture the output of a command for further processing.

    Parameters:
        cmd (list): A list suitable for passing to subprocess.run()
        cwd (Path, optional): A directory to run the command in.
        input (str, optional): A string to feed to the command via stdin.

    Returns:
        Output of cmd
    """
    return run(cmd, capture_output=True, check=True, cwd=cwd, input=input, text=True).stdout

def check_binutils(cfg, arch, cross_compile):
    """
    Checks that binutils are available based on CROSS_COMPILE.

    Parameters:
        arch (str): Name of architecture being compiled.
        cross_compile (str): Cross compile string.

    Returns:
        True if binutils is available in PATH, False if not.
    """
    if which(f"{cross_compile}as"):
        return True
    else:
        msg = f"{arch} kernels skipped due to missing binutils"
        log(cfg, msg)
        print(f"{msg}\n")
        return False

def clang_supports_target(target):
    """
    Tests that clang supports a particular target triple.

    Parameters:
        target (str): Target string to test.
    """
    clang_cmd = ["clang", f"--target={target}", "-c", "-x", "c", "-", "-o", "/dev/null"]
    clang = run(clang_cmd, input="", stderr=DEVNULL, stdout=DEVNULL, text=True)
    return clang.returncode == 0

def create_version_code(version):
    """
    Turns a version list with three values (major, minor, and patch level) into
    an integer with at least six digits:
        * major: as is
        * minor: with a minimum length of two ("1" becomes "01")
        * patch level: with a minimum length of three ("1" becomes "001")

    Parameters:
        version (list): A list with three integer values (major, minor, and
                        patch level).

    Returns:
        An integer with at least six digits.
    """
    major, minor, patch = [int(version[i]) for i in (0, 1, 2)]
    return int("{:d}{:02d}{:03d}".format(major, minor, patch))

def create_linux_version_code(linux_folder):
    """
    Turns the version of the Linux kernel being compiled into an integer with
    at least six digits.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source.

    Returns:
        An integer with at least six digits.
    """
    version_tuple = get_kernelversion(linux_folder).split("-")[0].split(".")
    return create_version_code(version_tuple)

def create_llvm_version_code():
    """
    Turns the version of clang being used to compile the kernel into an integer
    with at least six digits.

    Returns:
        An integer with at least six digits.
    """
    clang_cmd = ["clang", "-E", "-x", "c", "-"]
    clang_input = "__clang_major__ __clang_minor__ __clang_patchlevel__"
    clang_output = capture_cmd(clang_cmd, input=clang_input)

    version_tuple = clang_output.split("\n")[-2].split(" ")
    return create_version_code(version_tuple)

def die(die_str):
    """
    Prints a string in bold red then exits with an error code of 1.

    Parameters:
        die_str (str): String to print in red; prefixed with "ERROR: "
                       automatically.
    """
    red(f"ERROR: {die_str}")
    exit(1)

def gen_allconfig(build_folder, configs):
    """
    Generate a file for use with KCONFIG_ALLCONFIG.

    Parameters:
        build_folder (Path): A Path object pointing to the build_folder
        configs (list): A list of configuration values with notes about why
                        configurations are enabled or disabled.

    Returns:
        A tuple with the full path to the configuration file and string for
        logging.
    """
    config_path = None
    log_str = ""

    if configs:
        config_file, config_path = mkstemp(dir=build_folder, text=True)
        with open(config_file, "w") as f:
            for item in configs:
                if "CONFIG_" in item:
                    # If item has a value ('=y', '=n', or '=m'), respect it.
                    if "=" in item:
                        config = item
                    # Otherwise, we assume '=n'.
                    else:
                        config = f"{item}=n"
                    f.write(f"{config}\n")
                    log_str += f" + {config}"
                else:
                    log_str += f" {item}"

    return config_path, log_str

def get_binary_info(binary):
    """
    Gets the first line of the version string and installation location of
    binary.

    Parameters:
        binary (str): Binary to get information of.

    Returns:
        A tuple of the version string and installation location as strings.
    """
    version = capture_cmd([binary, "--version"]).split("\n")[0]
    location = Path(which(binary)).parent

    return version, location

def get_kernelversion(linux_folder):
    """
    Gets the version of the Linux kernel being compiled from
    'make -s kernelversion'.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source.

    Returns:
        The output of 'make -s kernelversion'.
    """
    make_cmd = ["make", "-C", linux_folder, "-s", "kernelversion"]
    return capture_cmd(make_cmd).strip()

def get_linux_version(linux_folder):
    """
    Gets the version of the Linux kernel being compiled in a format equivalent
    to running 'uname -sr'. Forces CONFIG_LOCALVERSION_AUTO=y to get commit
    info.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source.

    Returns:
        A string with the Linux kernel version in a format similar to 'uname -sr'.
    """
    kernelversion = get_kernelversion(linux_folder)

    include_config = linux_folder.joinpath("include", "config")
    include_config.mkdir(exist_ok=True, parents=True)

    autoconf = include_config.joinpath("auto.conf")
    with open(autoconf, "w") as f:
        f.write("CONFIG_LOCALVERSION_AUTO=y")

    localversion = capture_cmd(["scripts/setlocalversion"], cwd=linux_folder)

    rmtree(include_config, ignore_errors=True)

    return f"Linux {kernelversion}{localversion}"

def get_time_diff(start_time, end_time):
    """
    Prints the difference between start_time and end_time.

    Parameters:
        start_time (float): Start time of command.
        end_time (float): End time of command.

    Returns:
        A string with the length of time between the two times.
    """
    return timedelta(seconds=int(end_time - start_time))

def header(hdr_str, end='\n'):
    """
    Prints a fancy header in bold text.

    Parameters:
        hdr_str (str): String to print inside the header.
    """
    print("\033[1m")
    for x in range(0, len(hdr_str) + 6):
        print("=", end="")
    print(f"\n== {hdr_str} ==")
    for x in range(0, len(hdr_str) + 6):
        print("=", end="")
    print("\n\033[0m", end=end)

def kmake(kmake_cfg):
    """
    Runs a make command in the Linux kernel folder.

    Parameters:
        kmake_cfg (dict): A dictionary of variables needed for the build.

    Returns:
        A tuple containing the result of the command and how long it took to run
    """
    linux_folder = kmake_cfg["linux_folder"]
    build_folder = kmake_cfg["build_folder"]
    log_file = kmake_cfg["log_file"]
    variables = kmake_cfg["variables"]
    targets = kmake_cfg["targets"]

    cores = len(sched_getaffinity(0))

    make_flags = ["-C", linux_folder.as_posix()]
    make_flags += [f"-skj{cores}"]

    if build_folder.is_relative_to(linux_folder):
        build_folder = build_folder.relative_to(linux_folder)

    make_variables = []
    make_variables_dict = {
        "HOSTLDFLAGS": "-fuse-ld=lld",
        "LLVM": "1",
        "LLVM_IAS": "0",
        "LOCALVERSION": "-cbl",
        "O": build_folder.as_posix(),
    }
    if variables:
        make_variables_dict.update(variables)
    make_variables_dict = OrderedDict(sorted(make_variables_dict.items()))
    for key, value in make_variables_dict.items():
        make_variables += [f"{key}={value}"]

    make_targets = targets

    make_cmd = ["make"] + make_flags + make_variables + make_targets

    pretty_print_cmd(make_cmd)
    start_time = time()
    with Popen(make_cmd, stderr=STDOUT, stdout=PIPE) as p, open(log_file, "bw") as f:
        while True:
            byte = p.stdout.read(1)
            if byte:
                stdout.buffer.write(byte)
                stdout.flush()
                f.write(byte)
            else:
                break
    result = p.returncode

    command_time = get_time_diff(start_time, time())
    print(f"\nReal\t{command_time}")

    return p.returncode, command_time

def log(cfg, log_str):
    """
    Writes string to one of the logs, based on what it contains.

    Parameters:
        cfg (dict): Global configuration dictionary
        log_str (str): String to write to log.
    """
    if "failed" in log_str:
        file = cfg["logs"]["failed"]
    elif "skipped" in log_str:
        file = cfg["logs"]["skipped"]
    elif "success" in log_str:
        file = cfg["logs"]["success"]
    else:
        file = cfg["logs"]["info"]

    with open(file, "a") as f:
        f.write(f"{log_str}\n\n")

def log_file_from_str(log_folder, log_str):
    """
    Returns the full path to a log file based on log_folder and log_str.

    Parameters:
        log_folder (Path): A Path object pointing to the log folder.
        log_str (str): A string describing the build for the log.

    Returns:
        A Path object pointing to the log.
    """
    return log_folder.joinpath(f"{log_str.replace(' ', '-')}.log")

def log_result(cfg, log_str, success, time):
    """
    Log result of kernel build based on result.

    Parameters:
        cfg (dict): Global configuration dictionary
        log_str (str): Specific log string for kernel.
        success (bool): Whether or not the kernel build was successful.
        time (str): Amount of time that command took to completed.
    """
    result_str = "successful" if success else "failed"
    log(cfg, f"{log_str} {result_str} in {time}")

def modify_config(linux_folder, build_folder, mod_type):
    """
    Modifies the .config file in build_folder in a specific way.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source location.
        build_folder (Path): A Path objet pointing to the build folder containing '.config'.
        mod_type (str): The way to modify the config.
    """
    if mod_type == "big endian":
        args = ["-d", "CPU_LITTLE_ENDIAN", "-e", "CPU_BIG_ENDIAN"]
    elif mod_type == "little endian":
        args = ["-d", "CPU_BIG_ENDIAN", "-e", "CPU_LITTLE_ENDIAN"]
    elif mod_type == "thinlto":
        args = ["-d", "LTO_NONE", "-e", "LTO_CLANG_THIN"]
    elif mod_type == "clang hardening":
        args = ["-e", "CFI_CLANG"]
        args += ["-d", "LTO_NONE"]
        args += ["-e", "LTO_CLANG_THIN"]
        args += ["-e", "SHADOW_CALL_STACK"]
    scripts_config(linux_folder, build_folder, args)

def pretty_print_cmd(cmd):
    """
    Prints cmd in a "pretty" manner, similar to how 'set -x' works in bash,
    namely by surrounding list elements that have spaces with quotation marks
    so that copying and pasting the command in a shell works.

    Parameters:
        cmd (list): Command to print.
    """
    cmd_pretty = ""
    for element in cmd:
        if " " in element:
            if "=" in element:
                var = element.split("=")[0]
                value = element.split("=")[1]
                cmd_pretty += f' {var}="{value}"'
            else:
                cmd_pretty += f' "{element}"'
        else:
            cmd_pretty += f" {element}"
    print(f"\n$ {cmd_pretty.strip()}")

def red(red_str):
    """
    Prints string in bold red.

    Parameters:
        red_str (str): String to print in bold red.
    """
    print(f"\n\033[01;31m{red_str}\033[0m")

def scripts_config(linux_folder, build_folder, args):
    """
    Runs 'scripts/config' from Linux source folder against configuration in
    build folder. '.config' must already exist!

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source location.
        build_folder (Path): A Path objet pointing to the build folder containing '.config'.
        args (list): A list of arguments for 'scripts/configs'.
    """
    scripts_config = linux_folder.joinpath("scripts", "config").as_posix()
    config = build_folder.joinpath(".config").as_posix()

    cmd = [scripts_config, "--file", config] + args
    pretty_print_cmd(cmd)
    run(cmd, check=True)
