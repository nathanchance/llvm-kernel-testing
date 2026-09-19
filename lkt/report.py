import re
from dataclasses import dataclass
from pathlib import Path

import lkt.utils
from lkt.executor import Executor


@dataclass
class Result:
    name: str
    build: str
    boot: str
    log: Path


class Report:
    def __init__(self, executor: Executor):
        self.executor: Executor = executor

        self.results: list[Result] = []
        for result_dir in self.executor.results_folder.iterdir():
            name = result_dir.joinpath('name').read_text(encoding='utf-8').strip()
            build = result_dir.joinpath('build').read_text(encoding='utf-8').strip()
            if (boot_file := result_dir.joinpath('boot')).exists():
                boot = boot_file.read_text(encoding='utf-8').strip()
            else:
                boot = ''
            log = self.executor.logs_folder.joinpath(result_dir.name).with_suffix('.log')
            self.results.append(Result(name=name, build=build, boot=boot, log=log))

    def generate(self):
        good_results: list[str] = []
        bad_results: list[str] = []
        skip_results: list[str] = []

        for result in self.results:
            kernel_result = [f"{result.name} {result.build}"]

            if result.build.startswith('failed'):
                issues = [
                    line.replace(f"{self.executor.lst.folder}/", '')
                    for line in result.log.read_text(encoding='utf-8').splitlines()
                    if re.search(r"error:|warning:|undefined", line)
                ]
                if issues:
                    kernel_result.append('\n'.join(issues))

                dst = bad_results
            elif result.build.startswith('skipped'):
                dst = skip_results
            elif result.build.startswith('success'):
                dst = good_results
            else:
                msg = f"Could not handle build result '{result.build}'!"
                raise ValueError(msg)
            dst.append('\n'.join(kernel_result))

            if result.boot:
                if result.boot.startswith('failed'):
                    dst = bad_results
                elif result.boot.startswith('skipped'):
                    dst = skip_results
                elif result.boot.startswith('success'):
                    dst = good_results
                else:
                    msg = f"Could not handle boot result '{result.boot}'!"
                    raise ValueError(msg)
                dst.append(f"{result.name} qemu boot {result.boot}")

        total_duration = f"Total matrix duration: {self.executor.duration}"

        # Print report information to user
        self.executor.lst.show()
        self.executor.env_info.show()
        print(f"\n{total_duration}")

        if good_results:
            lkt.utils.header('List of successful tests')
            print('\n'.join(good_results))

        if bad_results:
            lkt.utils.header('List of failed tests')
            print('\n'.join(bad_results))

        if skip_results:
            lkt.utils.header('List of skipped tests')
            print('\n'.join(skip_results))

        # Generate files for later processing
        info = [
            str(self.executor.lst),
            str(self.executor.env_info),
            '',  # for explicit '\n'
            total_duration,
            '',
        ]
        Path(self.executor.logs_folder, 'info.log').write_text('\n'.join(info), encoding='utf-8')

        if good_results:
            txt = '\n\n'.join(good_results) + '\n'
            Path(self.executor.logs_folder, 'success.log').write_text(txt, encoding='utf-8')

        if bad_results:
            txt = '\n\n'.join(bad_results) + '\n'
            Path(self.executor.logs_folder, 'failed.log').write_text(txt, encoding='utf-8')

        if skip_results:
            txt = '\n\n'.join(skip_results) + '\n'
            Path(self.executor.logs_folder, 'skipped.log').write_text(txt, encoding='utf-8')
