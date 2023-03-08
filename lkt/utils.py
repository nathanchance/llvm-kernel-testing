#!/usr/bin/env python3

from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time


def chronic(*args, **kwargs):
    try:
        return subprocess.run(*args, **kwargs, capture_output=True, check=True, text=True)
    except subprocess.CalledProcessError as err:
        print(err.stdout)
        print(err.stderr)
        raise err


def clang_supports_target(target):
    clang_cmd = ['clang', f"--target={target}", '-c', '-x', 'c', '-o', '/dev/null', '/dev/null']
    clang_proc = subprocess.run(clang_cmd, capture_output=True, check=False)
    return clang_proc.returncode == 0


def create_binutils_version(gnu_as):
    if not shutil.which(gnu_as):
        return (0, 0, 0)

    as_output = chronic([gnu_as, '--version']).stdout.splitlines()[0]
    # "GNU assembler (GNU Binutils) 2.39.50.20221024" -> "2.39.50.20221024" -> ['2', '39', '50']
    # "GNU assembler version 2.39-3.fc38" -> "2.39-3.fc38" -> ['2.39'] -> ['2', '39'] -> ['2', '39', '0']
    version_list = as_output.split(' ')[-1].split('-')[0].split('.')[0:3]
    if len(version_list) == 2:
        version_list += ['0']
    return tuple(int(item) for item in version_list)


def create_qemu_version(qemu):
    if not shutil.which(qemu):
        return (0, 0, 0)

    qemu_ver = chronic([qemu, '--version']).stdout.splitlines()[0]
    if not (match := re.search(r'version (\d+\.\d+.\d+)', qemu_ver)):
        raise RuntimeError('Could not find QEMU version?')
    return tuple(int(x) for x in match.groups()[0].split('.'))


def get_config_val(linux, path, config):
    config_file = path if path.is_file() else Path(path, '.config')
    if not path.exists():
        raise FileNotFoundError('Could not find configuration?')
    scripts_config_cmd = [
        Path(linux, 'scripts/config'),
        '--file',
        config_file,
        '-k',
        '-s',
        config,
    ]
    return chronic(scripts_config_cmd).stdout.strip()


def is_modular(*args):
    return get_config_val(*args) == 'm'


def is_set(*args):
    return get_config_val(*args) not in ('', 'n', 'undef')


def get_time_diff(start_time, end_time=None):
    if not end_time:
        end_time = time.time()
    seconds = int(end_time - start_time)
    days, seconds = divmod(seconds, 60 * 60 * 24)
    hours, seconds = divmod(seconds, 60 * 60)
    minutes, seconds = divmod(seconds, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")

    return ' '.join(parts)


def header(hdr_str, end='\n'):
    """
    Prints a fancy header in bold text.
    Parameters:
        hdr_str (str): String to print inside the header.
    """
    border = ''.join(['=' for _x in range(0, len(hdr_str) + 6)])
    print(f"\n\033[1m{border}\n== {hdr_str} ==\n{border}\n\033[0m", end=end, flush=True)


def show_cmd(cmd):
    print(f"\n$ {' '.join(shlex.quote(str(item)) for item in cmd)}")
