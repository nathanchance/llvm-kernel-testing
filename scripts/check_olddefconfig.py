#!/usr/bin/env python3

import re
from argparse import ArgumentParser
from pathlib import Path


def parse_arguments() -> None:
    parser = ArgumentParser(description='Check .config after running olddefconfig')

    parser.add_argument('config_file', type=Path, help='Path to .config')
    parser.add_argument('requested_options', nargs='+', help='Options to check configuration for')

    return parser.parse_args()


def main():
    args = parse_arguments()

    missing_configs = []

    config_text = args.config_file.read_text(encoding='utf-8')
    for item in args.requested_options:
        cfg_name, cfg_val = item.split('=', 1)

        # 'CONFIG_FOO=n' does not appear in the final config, it is
        # '# CONFIG_FOO is not set'
        search = f"# {cfg_name} is not set" if cfg_val == 'n' else item
        # If we find a match, move on
        if re.search(f"^{search}$", config_text, flags=re.MULTILINE):
            continue

        # If we did not find a match for '# CONFIG_FOO is not set' or
        # CONFIG_FOO="", we should only add it to the missing configs
        # list if it is present with some other value because it may
        # not be visible, which means it is implicitly 'n' or '""'.
        if cfg_val in {'n', '""'} and re.search(f"^{cfg_name}=", config_text, flags=re.MULTILINE):
            missing_configs.append(item)

    if missing_configs:
        warning_msg = f"\nWARNING: Missing requested configurations after olddefconfig: {', '.join(missing_configs)}"
        print(warning_msg)


if __name__ == '__main__':
    main()
