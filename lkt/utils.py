#!/usr/bin/env python3

from pathlib import Path
import shlex
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
    border = ''.join(['=' for _x in range(len(hdr_str) + 6)])
    print(f"\n\033[1m{border}\n== {hdr_str} ==\n{border}\n\033[0m", end=end, flush=True)


def show_cmd(cmd):
    print(f"\n$ {' '.join(shlex.quote(str(item)) for item in cmd)}")
