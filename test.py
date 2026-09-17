#!/usr/bin/env python3

import os
from pathlib import Path

from lkt.env import EnvInfo
from lkt.source import LinuxSourceTree
from lkt.x86_64 import X8664Matrix


def main():
    env_info = EnvInfo()
    lst = LinuxSourceTree(Path(os.environ['CBL_SRC_D'], 'linux-next'))

    matrix = X8664Matrix(lst=lst, env_info=env_info, targets=['def'])
    print(matrix)
    print(matrix.jobs)


if __name__ == '__main__':
    main()
