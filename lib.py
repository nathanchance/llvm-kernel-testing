#!/usr/bin/env python3

import collections
import datetime
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time


def boot_qemu(cfg, arch, log_str, build_folder, kernel_available):
    """
    Boots a kernel in QEMU using 'boot-qemu.py'.

    Parameters:
        cfg (dict): Global configuration dictionary.
        arch (str): Architecture to boot (according to 'boot-qemu.py').
        log_str (str): String to use to use in log file to describe boot.
        build_folder (Path): A Path object pointing to the location of the
                             build folder.
        kernel_available (bool): Whether or not kernel was successfully built.
    """
    if kernel_available:
        boot_qemu_py = cfg['boot_utils_folder'].joinpath('boot-qemu.py').as_posix()
        cmd = [boot_qemu_py, '-a', arch, '-k', build_folder.as_posix()]
        pretty_print_cmd(cmd)
        sys.stderr.flush()
        sys.stdout.flush()
        result = subprocess.run(cmd)
        if result.returncode == 0:
            result_str = 'successful'
        else:
            result_str = 'failed'
    else:
        result_str = 'skipped'
    if not 'config' in log_str:
        log_str += ' config'
    log(cfg, f"{log_str} qemu boot {result_str}")


def can_be_modular(kconfig_file, cfg_sym):
    """
    Returns true if Kconfig symbol can be modular, returns False if not.

    Parameters:
        kconfig_file (Path): A Path object pointing to the Kconfig file the
                             symbol is defined in.
        cfg_sym (str): The Kconfig symbol to check.
    """
    if kconfig_file.exists():
        with open(kconfig_file) as f:
            return re.search(f"config {cfg_sym}\n\ttristate", f.read())
    return False


def capture_cmd(cmd, cwd=None, input=None):
    """
    Capture the output of a command for further processing.

    Parameters:
        cmd (list): A list suitable for passing to subprocess.run().
        cwd (Path, optional): A directory to run the command in.
        input (str, optional): A string to feed to the command via stdin.

    Returns:
        Output of cmd
    """
    return subprocess.run(cmd, capture_output=True, check=True, cwd=cwd, input=input,
                          text=True).stdout


def check_binutils(cfg, arch, cross_compile):
    """
    Checks that binutils are available based on CROSS_COMPILE.

    Parameters:
        arch (str): Name of architecture being compiled.
        cross_compile (str): Cross compile string.

    Returns:
        True if binutils is available in PATH, False if not.
    """
    if shutil.which(f"{cross_compile}as"):
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
    clang_cmd = ['clang', f"--target={target}", '-c', '-x', 'c', '-', '-o', '/dev/null']
    clang = subprocess.run(clang_cmd,
                           input='',
                           stderr=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL,
                           text=True)
    return clang.returncode == 0


def config_val(linux_folder, build_folder, cfg_sym):
    """
    Returns the output of 'scripts/config -s' to allow decisions based on
    current configuration value.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source
                             location.
        build_folder (Path): A Path object pointing to the build folder
                             containing '.config'.
        cfg_sym (str): Configuration symbol to check.

    Returns:
        The configuration value without trailing whitespace for easy
        comparisons.
    """
    return scripts_config(linux_folder, build_folder, ['-k', '-s', cfg_sym],
                          capture_output=True).strip()


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


def create_binutils_version_code(as_exec):
    """
    Turns the version of binutils being used to build the kernel into an
    integer with at least six digits.

    Parameters:
        as_exec (Path): A Path object pointing to the 'as' binary to get the
                        version from.

    Returns:
        An integer with at least six digits.
    """
    as_output = capture_cmd([as_exec, '--version']).split('\n')[0]
    # "GNU assembler (GNU Binutils) 2.39.50.20221024" -> "2.39.50.20221024" -> ['2', '39', '50']
    # "GNU assembler version 2.39-3.fc38" -> "2.39-3.fc38" -> ['2.39'] -> ['2', '39'] -> ['2', '39', '0']
    version_list = as_output.split(' ')[-1].split('-')[0].split('.')[0:3]
    if len(version_list) == 2:
        version_list += ['0']
    return create_version_code(version_list)


def create_linux_version_code(linux_folder):
    """
    Turns the version of the Linux kernel being compiled into an integer with
    at least six digits.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source.

    Returns:
        An integer with at least six digits.
    """
    version_list = get_kernelversion(linux_folder).split('-')[0].split('.')
    return create_version_code(version_list)


def create_llvm_version_code():
    """
    Turns the version of clang being used to compile the kernel into an integer
    with at least six digits.

    Returns:
        An integer with at least six digits.
    """
    clang_cmd = ['clang', '-E', '-x', 'c', '-']
    clang_input = '__clang_major__ __clang_minor__ __clang_patchlevel__'
    clang_output = capture_cmd(clang_cmd, input=clang_input)

    version_list = clang_output.split('\n')[-2].split(' ')
    return create_version_code(version_list)


def create_qemu_version_code(qemu_exec):
    """
    Turns the version of QEMU being used to boot test the kernel into an
    integer with at least six digits.

    Parameters:
        qemu_exec (str): The name of the QEMU binary to version check.

    Returns:
        An integer with at least six digits.
    """
    version_list = get_qemu_version(qemu_exec).split('.')
    return create_version_code(version_list)


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
    log_str = ''

    if configs:
        config_file, config_path = tempfile.mkstemp(dir=build_folder, text=True)
        with open(config_file, 'w') as f:
            for item in configs:
                if 'CONFIG_' in item:
                    # If item has a value ('=y', '=n', or '=m'), respect it.
                    if '=' in item:
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
    version = capture_cmd([binary, '--version']).split('\n')[0]
    location = pathlib.Path(shutil.which(binary)).parent

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
    make_cmd = ['make', '-C', linux_folder, '-s', 'kernelversion']
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

    include_config = linux_folder.joinpath('include', 'config')
    include_config.mkdir(exist_ok=True, parents=True)

    autoconf = include_config.joinpath('auto.conf')
    with open(autoconf, 'w') as f:
        f.write('CONFIG_LOCALVERSION_AUTO=y')

    localversion = capture_cmd(['scripts/setlocalversion'], cwd=linux_folder)

    shutil.rmtree(include_config, ignore_errors=True)

    return f"Linux {kernelversion}{localversion}"


def get_qemu_version(qemu_exec):
    """
    Get the QEMU version information from the QEMU version string.

    Parameters:
        qemu_exec (str): The name of the QEMU binary to version check.

    Returns:
        The QEMU version number as a string.
    """
    qemu_output = capture_cmd([qemu_exec, '--version'])
    return qemu_output.split('\n')[0].split(' ')[3]


def get_time_diff(start_time, end_time):
    """
    Prints the difference between start_time and end_time.

    Parameters:
        start_time (float): Start time of command.
        end_time (float): End time of command.

    Returns:
        A string with the length of time between the two times.
    """
    return datetime.timedelta(seconds=int(end_time - start_time))


def has_kcfi(linux_folder):
    """
    Checks if the Linux source has kCFI.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source.

    Returns:
        True if kCFI is present, false if not.
    """
    with open(linux_folder.joinpath('arch', 'Kconfig')) as f:
        return re.search('fsanitize=kcfi', f.read())


def header(hdr_str, end='\n'):
    """
    Prints a fancy header in bold text.

    Parameters:
        hdr_str (str): String to print inside the header.
    """
    print('\033[1m')
    for x in range(0, len(hdr_str) + 6):
        print('=', end='')
    print(f"\n== {hdr_str} ==")
    for x in range(0, len(hdr_str) + 6):
        print('=', end='')
    print('\n\033[0m', end=end)
    sys.stdout.flush()


def is_modular(linux_folder, build_folder, cfg_sym):
    """
    Checks if a configuration value is enabled as a module.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source location.
        build_folder (Path): A Path object pointing to the build folder containing '.config'.
        cfg_sym (str): Configuration symbol to check.

    Returns:
        True if symbol is 'm', False if not.
    """
    return config_val(linux_folder, build_folder, cfg_sym) == 'm'


def is_relative_to(path_one, path_two):
    """
    Checks if path_one is relative to path_two. Needed for Python < 3.9
    compatibility :(

    Parameters:
        path_one (Path): A Path object pointing to the potential child path.
        path_two (Path): A Path object pointing to the potential parent path.

    Returns:
        Ttrue
    """
    if sys.version_info >= (3, 9):
        return path_one.is_relative_to(path_two)
    else:
        try:
            path_one.relative_to(path_two)
        except ValueError:
            return False
        return True


def is_set(linux_folder, build_folder, cfg_sym):
    """
    Checks if a configuration value is set (either enabled as 'y'/'n' or has a
    non-empty value as a string).

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source
                             location.
        build_folder (Path): A Path object pointing to the build folder
                             containing '.config'.
        cfg_sym (str): Configuration symbol to check.

    Returns:
        True if symbol is not 'n' or empty, False if not.
    """
    val = config_val(linux_folder, build_folder, cfg_sym)
    return not (val == '' or val == 'n' or val == 'undef')


def kmake(kmake_cfg):
    """
    Runs a make command in the Linux kernel folder.

    Dictionary keys and meaning:
        * linux_folder (Path): A Path object pointing to the Linux kernel
                               source location.
        * build_folder (Path): A Path object pointing to the folder the build
                               will be done in.
        * log_file (Path): A Path object pointing to the file that the build
                           output will be written into.
        * variables (dict): A dictionary of make variables to be merged with
                            the main dictionary (e.g., to turn the integrated
                            assembler on, use ld.bfd, specify architecture).
        * targets (list): A list of targets to run (e.g. ['defconfig', 'all']).

    Parameters:
        kmake_cfg (dict): A dictionary of variables needed for the build.

    Returns:
        A tuple containing the result of the command and how long it took to
        run for logging purposes.
    """
    linux_folder = kmake_cfg['linux_folder']
    build_folder = kmake_cfg['build_folder']
    log_file = kmake_cfg['log_file']
    variables = kmake_cfg['variables']
    targets = kmake_cfg['targets']

    cores = len(os.sched_getaffinity(0))

    make_flags = ['-C', linux_folder.as_posix()]
    make_flags += [f"-skj{cores}"]

    if is_relative_to(build_folder, linux_folder):
        build_folder = build_folder.relative_to(linux_folder)

    make_variables = []
    make_variables_dict = {
        'HOSTLDFLAGS': '-fuse-ld=lld',
        'LLVM': '1',
        'LLVM_IAS': '0',
        'LOCALVERSION': '-cbl',
        'O': build_folder.as_posix(),
    }
    if variables:
        make_variables_dict.update(variables)
    make_variables_dict = collections.OrderedDict(sorted(make_variables_dict.items()))
    for key, value in make_variables_dict.items():
        make_variables += [f"{key}={value}"]

    make_targets = targets

    make_cmd = ['make'] + make_flags + make_variables + make_targets

    pretty_print_cmd(make_cmd)
    start_time = time.time()
    sys.stderr.flush()
    sys.stdout.flush()
    with subprocess.Popen(make_cmd, stderr=subprocess.STDOUT,
                          stdout=subprocess.PIPE) as p, open(log_file, 'bw') as f:
        while True:
            byte = p.stdout.read(1)
            if byte:
                sys.stdout.buffer.write(byte)
                sys.stdout.flush()
                f.write(byte)
            else:
                break
    result = p.returncode

    command_time = get_time_diff(start_time, time.time())
    print(f"\nReal\t{command_time}")

    return p.returncode, command_time


def log(cfg, log_str):
    """
    Writes string to one of the logs, based on what it contains.

    Parameters:
        cfg (dict): Global configuration dictionary
        log_str (str): String to write to log.
    """
    if 'failed' in log_str:
        file = cfg['logs']['failed']
    elif 'skipped' in log_str:
        file = cfg['logs']['skipped']
    elif 'success' in log_str:
        file = cfg['logs']['success']
    else:
        file = cfg['logs']['info']

    with open(file, 'a') as f:
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
    return log_folder.joinpath(f"{log_str.replace(' ', '-').replace('-config','')}.log")


def log_result(cfg, log_str, success, time, build_log):
    """
    Log result of kernel build based on result.

    Parameters:
        cfg (dict): Global configuration dictionary
        log_str (str): Specific log string for kernel.
        success (bool): Whether or not the kernel build was successful.
        time (str): Amount of time that command took to completed.
        build_log (Path): A Path object pointing to the build log.
    """
    result_str = 'successful' if success else 'failed'
    if not 'config' in log_str:
        log_str += ' config'
    msg = f"{log_str} {result_str} in {time}"
    if not success:
        with open(build_log) as f:
            for line in f:
                if re.search('error:|warning:|undefined', line):
                    msg += f"\n{line.strip()}"
    log(cfg, msg)


def modify_config(linux_folder, build_folder, mod_type):
    """
    Modifies the .config file in build_folder in a specific way.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source
                             location.
        build_folder (Path): A Path object pointing to the build folder
                             containing '.config'.
        mod_type (str): The way to modify the config.
    """
    if mod_type == 'big endian':
        args = ['-d', 'CPU_LITTLE_ENDIAN', '-e', 'CPU_BIG_ENDIAN']
    elif mod_type == 'little endian':
        args = ['-d', 'CPU_BIG_ENDIAN', '-e', 'CPU_LITTLE_ENDIAN']
    elif mod_type == 'thinlto':
        args = ['-d', 'LTO_NONE', '-e', 'LTO_CLANG_THIN']
    scripts_config(linux_folder, build_folder, args)


def pretty_print_cmd(cmd):
    """
    Prints cmd in a "pretty" manner, similar to how 'set -x' works in bash,
    namely by surrounding list elements that have spaces with quotation marks
    so that copying and pasting the command in a shell works.

    Parameters:
        cmd (list): Command to print.
    """
    cmd_pretty = ''
    for element in cmd:
        if ' ' in element:
            if '=' in element:
                var = element.split('=')[0]
                value = element.split('=')[1]
                cmd_pretty += f' {var}="{value}"'
            else:
                cmd_pretty += f' "{element}"'
        else:
            cmd_pretty += f" {element}"
    print(f"\n$ {cmd_pretty.strip()}", flush=True)


def process_cfg_item(linux_folder, build_folder, cfg_item):
    """
    Changes a configuration symbol from 'm' to 'y' if pattern is found in file.

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source
                             location.
        build_folder (Path): A Path object pointing to the build folder
                             containing '.config'.
        cfg_item (tuple): A tuple containing the symbol, the file it is defined
                          in, and (optional) 'scripts/config' arguments to
                          perform if the symbol cannot be modular.
    """
    cfg_sym = cfg_item[0]
    file = cfg_item[1]
    if len(cfg_item) == 3:
        sc_action = cfg_item[2]
    else:
        sc_action = ['-e']

    sym_is_m = is_modular(linux_folder, build_folder, cfg_sym)
    sym_cannot_be_m = not can_be_modular(linux_folder.joinpath(file), cfg_sym)

    if sym_is_m and sym_cannot_be_m:
        return sc_action + [cfg_sym]
    return []


def red(red_str):
    """
    Prints string in bold red.

    Parameters:
        red_str (str): String to print in bold red.
    """
    print(f"\n\033[01;31m{red_str}\033[0m")


def scripts_config(linux_folder, build_folder, args, capture_output=False):
    """
    Runs 'scripts/config' from Linux source folder against configuration in
    build folder. '.config' must already exist!

    Parameters:
        linux_folder (Path): A Path object pointing to the Linux kernel source
                             location.
        build_folder (Path): A Path object pointing to the build folder
                             containing '.config'.
        args (list): A list of arguments for 'scripts/configs'.
        capture_output (bool, optional): Whether or not to capture the output
                                         of 'scripts/config'. Useful for
                                         getting the value of configuration
                                         symbols.
    """
    scripts_config = linux_folder.joinpath('scripts', 'config').as_posix()
    config = build_folder.joinpath('.config').as_posix()

    cmd = [scripts_config, '--file', config] + args
    if capture_output:
        return capture_cmd(cmd)
    pretty_print_cmd(cmd)
    subprocess.run(cmd, check=True)


def setup_config(sc_cfg):
    """
    Sets up a distribution configuration in the build folder.

    Parameters:
        sc_cfg (dict): A dictionary with 'linux_folder', 'linux_version_code',
                       'build_folder', and 'config_file' as keys.
    """
    linux_folder = sc_cfg['linux_folder']
    linux_version_code = sc_cfg['linux_version_code']
    build_folder = sc_cfg['build_folder']
    config_file = sc_cfg['config_file']

    log_cfgs = []
    sc_args = []

    # Clean up build folder
    shutil.rmtree(build_folder, ignore_errors=True)
    build_folder.mkdir(parents=True)

    # Copy '.config'
    config_dst = build_folder.joinpath('.config')
    pretty_print_cmd(['cp', config_file.as_posix(), config_dst.as_posix()])
    shutil.copyfile(config_file, config_dst)

    # CONFIG_DEBUG_INFO_BTF has two conditions:
    #
    #   * pahole needs to be available
    #
    #   * The kernel needs https://git.kernel.org/linus/90ceddcb495008ac8ba7a3dce297841efcd7d584,
    #     which is first available in 5.7: https://github.com/ClangBuiltLinux/linux/issues/871
    #
    # If either of those conditions are false, we need to disable this config so
    # that the build does not error.
    debug_info_btf = 'DEBUG_INFO_BTF'
    debug_info_btf_y = is_set(linux_folder, build_folder, debug_info_btf)
    pahole_available = shutil.which('pahole')
    if debug_info_btf_y and not (pahole_available and linux_version_code >= 507000):
        log_cfgs += [debug_info_btf]
        sc_args += ['-d', debug_info_btf]

    bpf_preload = 'BPF_PRELOAD'
    if is_set(linux_folder, build_folder, bpf_preload):
        log_cfgs += [bpf_preload]
        sc_args += ['-d', bpf_preload]

    # Distribution fun
    if 'debian' in config_file.as_posix():
        # We are building upstream kernels, which do not have Debian's
        # signing keys in their source.
        system_trusted_keys = 'SYSTEM_TRUSTED_KEYS'
        if is_set(linux_folder, build_folder, system_trusted_keys):
            log_cfgs += [system_trusted_keys]
            sc_args += ['-d', system_trusted_keys]

        # The Android drivers are not modular in upstream.
        for android_cfg in ['ANDROID_BINDER_IPC', 'ASHMEM']:
            if is_modular(linux_folder, build_folder, android_cfg):
                sc_args += ['-e', android_cfg]

    if 'archlinux' in config_file.as_posix():
        # These files will not exist in our kernel tree.
        extra_firmware = 'EXTRA_FIRMWARE'
        if is_set(linux_folder, build_folder, extra_firmware):
            log_cfgs += [extra_firmware]
            sc_args += ['-u', extra_firmware]

    # Make sure that certain configuration options do not get disabled across
    # kernel versions. This would not be necessary if we had an individual
    # config for each kernel version that we support but that is a lot more
    # effort.
    cfg_items = []

    # CONFIG_BCM7120_L2_IRQ as a module is invalid before https://git.kernel.org/linus/3ac268d5ed2233d4a2db541d8fd744ccc13f46b0
    cfg_items += [('BCM7120_L2_IRQ', 'drivers/irqchip/Kconfig')]

    # CONFIG_CHELSIO_IPSEC_INLINE as a module is invalid before https://git.kernel.org/linus/1b77be463929e6d3cefbc929f710305714a89723
    cfg_items += [('CHELSIO_IPSEC_INLINE', 'drivers/crypto/chelsio/Kconfig')]

    # CONFIG_CORESIGHT (and all of its drivers) as a module is invalid before https://git.kernel.org/linus/8e264c52e1dab8a7c1e036222ef376c8920c3423
    coresight_suffixes = [
        '', '_LINKS_AND_SINKS', '_LINK_AND_SINK_TMC', '_CATU', '_SINK_TPIU', '_SINK_ETBV10',
        '_SOURCE_ETM4X', '_STM'
    ]
    for coresight_sym in [f"CORESIGHT{s}" for s in coresight_suffixes]:
        cfg_items += [(coresight_sym, 'drivers/hwtracing/coresight/Kconfig')]

    # CONFIG_CS89x0_PLATFORM as a module is invalid before https://git.kernel.org/linus/47fd22f2b84765a2f7e3f150282497b902624547
    cfg_items += [('CS89x0_PLATFORM', 'drivers/net/ethernet/cirrus/Kconfig', ['-e', 'CS89x0',
                                                                              '-e'])]

    # CONFIG_CRYPTO_BLAKE2S_{ARM,X86} as modules is invalid after https://git.kernel.org/linus/2d16803c562ecc644803d42ba98a8e0aef9c014e
    cfg_items += [('CRYPTO_BLAKE2S_ARM', 'arch/arm/crypto/Kconfig')]
    cfg_items += [('CRYPTO_BLAKE2S_X86', 'crypto/Kconfig')]

    # CONFIG_DAX as a module is invalid after https://git.kernel.org/next/linux-next/c/47ff0a68f6be7961879ee267485f8c7720932985
    cfg_items += [('DAX', 'drivers/dax/Kconfig')]

    # CONFIG_DRM_GEM_{CMA,SHMEM}_HELPER as modules is invalid before https://git.kernel.org/linus/4b2b5e142ff499a2bef2b8db0272bbda1088a3fe
    for drm_helper in ['CMA', 'SHMEM']:
        # These are not user selectable symbols so unset them and let Kconfig set them as necessary.
        cfg_items += [(f"DRM_GEM_{drm_helper}_HELPER", 'drivers/gpu/drm/Kconfig', ['-u'])]

    # CONFIG_GPIO_MXC as a module is invalid before https://git.kernel.org/linus/12d16b397ce0a999d13762c4c0cae2fb82eb60ee
    # CONFIG_GPIO_PL061 as a module is invalid before https://git.kernel.org/linus/616844408de7f21546c3c2a71ea7f8d364f45e0d
    # CONFIG_GPIO_TPS68470 as a module is invalid before https://git.kernel.org/linus/a1ce76e89907a69713f729ff21db1efa00f3bb47
    gpio_suffixes = ['MXC', 'PL061', 'TPS68470']
    for gpio_sym in [f"GPIO_{s}" for s in gpio_suffixes]:
        cfg_items += [(gpio_sym, 'drivers/gpio/Kconfig')]

    # CONFIG_IIO_RESCALE_KUNIT_TEST as a module is invalid before https://git.kernel.org/linus/0565d238b9b4abb7b904248d9064bea80ac706fe
    cfg_items += [('IIO_RESCALE_KUNIT_TEST', 'drivers/iio/test/Kconfig')]

    # CONFIG_IMX_DSP as a module is invalid before https://git.kernel.org/linus/f52cdcce9197fef9d4a68792dd3b840ad2b77117
    cfg_items += [('IMX_DSP', 'drivers/firmware/imx/Kconfig')]

    # CONFIG_KPROBES_SANITY_TEST as a module is invalid before https://git.kernel.org/linus/e44e81c5b90f698025eadceb7eef8661eda117d5
    cfg_items += [('KPROBES_SANITY_TEST', 'lib/Kconfig.debug')]

    # CONFIG_PCI_DRA7XX{,_HOST,_EP} as modules is invalid before https://git.kernel.org/linus/3b868d150efd3c586762cee4410cfc75f46d2a07
    # CONFIG_PCI_EXYNOS as a module is invalid before https://git.kernel.org/linus/778f7c194b1dac351d345ce723f8747026092949
    # CONFIG_PCI_MESON as a module is invalid before https://git.kernel.org/linus/a98d2187efd9e6d554efb50e3ed3a2983d340fe5
    pci_suffixes = ['DRA7XX', 'DRA7XX_EP', 'DRA7XX_HOST', 'EXYNOS', 'MESON']
    for pci_sym in [f"PCI_{s}" for s in pci_suffixes]:
        cfg_items += [(pci_sym, 'drivers/pci/controller/dwc/Kconfig')]

    # CONFIG_PINCTRL_AMD as a module is invalid after https://git.kernel.org/linus/41ef3c1a6bb0fd4a3f81170dd17de3adbff80783
    cfg_items += [('PINCTRL_AMD', 'drivers/pinctrl/Kconfig')]

    # CONFIG_POWER_RESET_SC27XX as a module is invalid before https://git.kernel.org/linus/f78c55e3b4806974f7d590b2aab8683232b7bd25
    cfg_items += [('POWER_RESET_SC27XX', 'drivers/power/reset/Kconfig')]

    # CONFIG_PROC_THERMAL_MMIO_RAPL as a module is invalid before https://git.kernel.org/linus/a5923b6c3137b9d4fc2ea1c997f6e4d51ac5d774
    cfg_items += [('PROC_THERMAL_MMIO_RAPL', 'drivers/thermal/intel/int340x_thermal/Kconfig')]

    # CONFIG_QCOM_RPMPD as a module is invalid before https://git.kernel.org/linus/f29808b2fb85a7ff2d4830aa1cb736c8c9b986f4
    # CONFIG_QCOM_RPMHPD as a module is invalid before https://git.kernel.org/linus/d4889ec1fc6ac6321cc1e8b35bb656f970926a09
    for rpm_sym in [f"QCOM_RPM{s}PD" for s in ['', 'H']]:
        cfg_items += [(rpm_sym, 'drivers/soc/qcom/Kconfig')]

    # CONFIG_RADIO_ADAPTERS as a module is invalid before https://git.kernel.org/linus/215d49a41709610b9e82a49b27269cfaff1ef0b6
    cfg_items += [('RADIO_ADAPTERS', 'drivers/media/radio/Kconfig')]

    # CONFIG_RATIONAL as a module is invalid before https://git.kernel.org/linus/bcda5fd34417c89f653cc0912cc0608b36ea032c
    cfg_items += [('RATIONAL', 'lib/math/Kconfig')]

    # CONFIG_RESET_MESON as a module is invalid before https://git.kernel.org/linus/3bfe8933f9d187f93f0d0910b741a59070f58c4c
    reset_suffixes = ['IMX7', 'MESON']
    for reset_sym in [f"RESET_{s}" for s in reset_suffixes]:
        cfg_items += [(reset_sym, 'drivers/reset/Kconfig')]

    # CONFIG_RTW88_8822BE as a module is invalid before https://git.kernel.org/linus/416e87fcc780cae8d72cb9370fa0f46007faa69a
    # CONFIG_RTW88_8822CE as a module is invalid before https://git.kernel.org/linus/ba0fbe236fb8a7b992e82d6eafb03a600f5eba43
    for rtw_sym in [f"RTW88_8822{s}E" for s in ['B', 'C']]:
        cfg_items += [(rtw_sym, 'drivers/net/wireless/realtek/rtw88/Kconfig')]

    # CONFIG_SERIAL_LANTIQ as a module is invalid before https://git.kernel.org/linus/ad406341bdd7d22ba9497931c2df5dde6bb9440e
    cfg_items += [('SERIAL_LANTIQ', 'drivers/tty/serial/Kconfig')]

    # CONFIG_SND_SOC_SOF_DEBUG_PROBES as a module is invalid before https://git.kernel.org/linus/3dc0d709177828a22dfc9d0072e3ac937ef90d06
    cfg_items += [('SND_SOC_SOF_DEBUG_PROBES', 'sound/soc/sof/Kconfig')]

    # CONFIG_SND_SOC_SOF_HDA_PROBES as a module is invalid before https://git.kernel.org/linus/e18610eaa66a1849aaa00ca43d605fb1a6fed800
    cfg_items += [('SND_SOC_SOF_HDA_PROBES', 'sound/soc/sof/intel/Kconfig')]

    # CONFIG_SND_SOC_SPRD_MCDT as a module is invalid before https://git.kernel.org/linus/fd357ec595d36676c239d8d16706a270a961ac32
    cfg_items += [('SND_SOC_SPRD_MCDT', 'sound/soc/sprd/Kconfig')]

    # CONFIG_SYSCTL_KUNIT_TEST as a module is invalid before https://git.kernel.org/linus/c475c77d5b56398303e726969e81208196b3aab3
    cfg_items += [('SYSCTL_KUNIT_TEST', 'lib/Kconfig.debug')]

    # CONFIG_TEGRA124_EMC as a module is invalid before https://git.kernel.org/linus/281462e593483350d8072a118c6e072c550a80fa
    # CONFIG_TEGRA20_EMC as a module is invalid before https://git.kernel.org/linus/0260979b018faaf90ff5a7bb04ac3f38e9dee6e3
    # CONFIG_TEGRA30_EMC as a module is invalid before https://git.kernel.org/linus/0c56eda86f8cad705d7d14e81e0e4efaeeaf4613
    for tegra_ver in ['124', '20', '30']:
        cfg_items += [(f"TEGRA{tegra_ver}_EMC", 'drivers/memory/tegra/Kconfig')]

    # CONFIG_TEGRA20_APB_DMA as a module is invalid before https://git.kernel.org/linus/703b70f4dc3d22b4ab587e0ca424b974a4489db4
    cfg_items += [('TEGRA20_APB_DMA', 'drivers/dma/Kconfig')]

    # CONFIG_TI_CPTS as a module is invalid before https://git.kernel.org/linus/92db978f0d686468e527d49268e7c7e8d97d334b
    cfg_items += [('TI_CPTS', 'drivers/net/ethernet/ti/Kconfig')]

    # CONFIG_UNICODE as a module is invalid before https://git.kernel.org/linus/5298d4bfe80f6ae6ae2777bcd1357b0022d98573
    cfg_items += [('UNICODE', 'fs/unicode/Kconfig')]

    # CONFIG_VIRTIO_IOMMU as a module is invalid before https://git.kernel.org/linus/fa4afd78ea12cf31113f8b146b696c500d6a9dc3
    cfg_items += [('VIRTIO_IOMMU', 'drivers/iommu/Kconfig')]

    # CONFIG_ZPOOL as a module is invalid after https://git.kernel.org/linus/b3fbd58fcbb10725a1314688e03b1af6827c42f9
    cfg_items += [('ZPOOL', 'mm/Kconfig')]

    for cfg_item in cfg_items:
        sc_args += process_cfg_item(linux_folder, build_folder, cfg_item)

    # CONFIG_MFD_ARIZONA as a module is invalid before https://git.kernel.org/linus/33d550701b915938bd35ca323ee479e52029adf2
    # Done manually because 'tristate'/'bool' is not right after 'config MFD_ARIZONA'...
    with open(linux_folder.joinpath('drivers', 'mfd', 'Makefile')) as f:
        has_33d550701b915 = re.search('arizona-objs', f.read())
    mfd_arizona_is_m = is_modular(linux_folder, build_folder, 'MFD_ARIZONA')
    if mfd_arizona_is_m and not has_33d550701b915:
        sc_args += ['-e', 'MFD_ARIZONA']

    # CONFIG_USB_FOTG210_{HCD,UDC} as modules is invalid after https://git.kernel.org/gregkh/usb/c/aeffd2c3b09f4f50438ec8960095129798bcb33a
    # Done manually because 'tristate'/'bool' is not right after 'config USB_FOTG210_UDC'...
    # This file check is good enough, as patch 1 adds this file and patch 2 is
    # the one that changes the symbols from 'tristate' to 'bool'. Due to the
    # nature of the changes, the two patches *should* always be together (i.e.,
    # it is not expected that patch 1 shows up somewhere without patch 2...).
    if linux_folder.joinpath('drivers', 'usb', 'fotg210', 'Kconfig').exists():
        for usb_fotg_sym in [f"USB_FOTG210_{s}" for s in ['HCD', 'UDC']]:
            if is_modular(linux_folder, build_folder, usb_fotg_sym):
                sc_args += ['-e', usb_fotg_sym]

    if sc_args:
        scripts_config(linux_folder, build_folder, ['-k'] + sc_args)

    log_str = ''
    for log_cfg in log_cfgs:
        log_str += f" + CONFIG_{log_cfg}=n"

    return log_str
