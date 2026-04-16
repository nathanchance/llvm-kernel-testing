import copy
import os
import shlex
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

DEFAULT_PATH = Path('/intentionally/does/not/exist')
PathString = Path | str
ValidSingleCmd = str | bytes | os.PathLike
ValidCmd = ValidSingleCmd | Sequence[ValidSingleCmd]
CmdList = list[ValidSingleCmd]


def chronic(args: ValidCmd, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault('capture_output', True)

    return run(args, **kwargs)


def clang_supports_target(target: str) -> bool:
    return run_check_rc_zero(
        ['clang', f"--target={target}", '-c', '-x', 'c', '-o', '/dev/null', '/dev/null']
    )


def cmd_str(cmd: ValidCmd) -> str:
    if isinstance(cmd, ValidSingleCmd):
        cmd_to_print = cmd
    else:
        cmd_to_print = ' '.join(shlex.quote(str(elem)) for elem in cmd)
    return f"$ {cmd_to_print}"


def get_config_val(linux: Path, path: Path, config: str) -> str:
    config_file: Path = path if path.is_file() else Path(path, '.config')
    if not path.exists():
        msg = 'Could not find configuration?'
        raise FileNotFoundError(msg)
    scripts_config_cmd: CmdList = [
        Path(linux, 'scripts/config'),
        '--file',
        config_file,
        '-k',
        '-s',
        config,
    ]
    return chronic(scripts_config_cmd).stdout.strip()


def is_modular(*args) -> bool:
    return get_config_val(*args) == 'm'


def is_set(*args) -> bool:
    return get_config_val(*args) not in {'', 'n', 'undef'}


def get_time_diff(start_time: float, end_time: float | None = None) -> str:
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


def header(hdr_str: str, end: str = '\n') -> None:
    """
    Prints a fancy header in bold text.
    Parameters:
        hdr_str (str): String to print inside the header.
    """
    border = ''.join(['=' for _x in range(len(hdr_str) + 6)])
    print(f"\n\033[1m{border}\n== {hdr_str} ==\n{border}\n\033[0m", end=end, flush=True)


def path_is_set(path: Path) -> bool:
    return path != DEFAULT_PATH


def run(args: ValidCmd, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault('check', True)

    kwargs.setdefault('text', True)
    if (input_val := kwargs.get('input')) and not isinstance(input_val, str):
        kwargs['text'] = None

    if kwargs.pop('show_cmd', False):
        show_cmd(args)

    if env := kwargs.pop('env', None):
        kwargs['env'] = os.environ | copy.deepcopy(env)

    try:
        # This function defaults check=True so if check=False here, it is explicit
        # pylint: disable-next=subprocess-run-check
        return subprocess.run(args, **kwargs)  # noqa: PLW1510
    except subprocess.CalledProcessError as err:
        if kwargs.get('capture_output'):
            print(err.stdout)
            print(err.stderr)
        raise


def run_check_rc_zero(args: ValidCmd, **kwargs) -> bool:
    return chronic(args, **kwargs, check=False).returncode == 0


def show_cmd(cmd: ValidCmd) -> None:
    print(f"\n{cmd_str(cmd)}")
