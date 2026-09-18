#!/usr/bin/env python3

import os
from pathlib import Path

from lkt.env import EnvInfo
from lkt.executor import Executor
from lkt.source import LinuxSourceTree
from lkt.x86_64 import X8664Matrix


def main():
    env_info = EnvInfo()
    lst = LinuxSourceTree(Path(os.environ['CBL_SRC_D'], 'linux-next'))

    matrix = X8664Matrix(lst=lst, env_info=env_info, targets=['def'])
    lkt_rewrite_tmp = Path(os.environ['TMP_FOLDER'], 'lkt-rewrite')
    executor = Executor(
        [matrix],
        lst,
        env_info,
        Path(os.environ['CBL_SRC_C'], 'boot-utils'),
        lkt_rewrite_tmp.joinpath('build'),
        lkt_rewrite_tmp.joinpath('output'),
    )

    executor.run()


if __name__ == '__main__':
    main()
