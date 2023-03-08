#!/usr/bin/env python3

import os
from pathlib import Path
import re
import shutil
import time

import lkt.runner
import lkt.utils


def get_cmd_info(cmd):
    version = lkt.utils.chronic([cmd, '--version']).stdout.splitlines()[0]
    location = Path(shutil.which(cmd)).parent
    return version, location


def get_linux_version(linux):
    (include_config := Path(linux, 'include/config')).mkdir(exist_ok=True, parents=True)
    Path(include_config, 'auto.conf').write_text('CONFIG_LOCALVERSION_AUTO=y\n', encoding='utf-8')

    base_make_cmd = ['make', '-C', linux, '-s']
    setlocalver = Path(linux, 'scripts/setlocalversion')
    if 'KERNELVERSION is not set' in setlocalver.read_text(encoding='utf-8'):
        kernelrelease = lkt.utils.chronic([*base_make_cmd, 'kernelrelease']).stdout.strip()
    else:
        kernelrelease = [lkt.utils.chronic([*base_make_cmd, 'kernelversion']).stdout.strip()]
        kernelrelease.append(lkt.utils.chronic(setlocalver, cwd=linux).stdout.strip())

    shutil.rmtree(include_config, ignore_errors=True)

    return f"Linux {''.join(kernelrelease)}"


class LKTReport:

    def __init__(self):
        self.env_info = {}
        self.folders = lkt.runner.Folders()
        self.results = {
            'good': [],
            'bad': [],
            'skip': [],
        }
        self.start_time = time.time()

    def _generate_env_info(self):
        if not self.folders.source:
            raise RuntimeError('Cannot generate environment information without source location!')
        if not self.folders.source.exists():
            raise FileNotFoundError('Provided source location does not exist?')

        self.env_info['clang version'], self.env_info['clang location'] = get_cmd_info('clang')
        self.env_info['binutils version'], self.env_info['binutils location'] = get_cmd_info('as')
        self.env_info['Linux version'] = get_linux_version(self.folders.source)
        self.env_info['Linux source location'] = self.folders.source
        self.env_info['PATH'] = os.environ['PATH']

    def generate_report(self, results):
        for result in results:
            kernel_result = []
            kernel = [result['name'], result['build']]
            if 'duration' in result:
                kernel += ['in', result['duration']]
            if 'reason' in result:
                kernel += ['due to', result['reason']]
            kernel_result.append(' '.join(kernel))

            if result['build'] == 'failed':
                issues = []
                for line in result['log'].read_text(encoding='utf-8').splitlines():
                    if re.search('error:|warning:|undefined', line):
                        issues.append(line.replace(f"{self.folders.source}/", ''))
                if issues:
                    kernel_result.append('\n'.join(issues))

            if result['build'] == 'failed':
                dst = self.results['bad']
            elif result['build'] == 'skipped':
                dst = self.results['skip']
            elif result['build'] == 'successful':
                dst = self.results['good']
            else:
                raise ValueError(f"Could not handle build result '{result['build']}'!")
            dst.append('\n'.join(kernel_result))

            if 'boot' in result:
                if result['boot'].startswith('failed'):
                    dst = self.results['bad']
                elif result['boot'].startswith('skipped'):
                    dst = self.results['skip']
                elif result['boot'].startswith('successful'):
                    dst = self.results['good']
                else:
                    raise ValueError(f"Could not handle boot result '{result['boot']}'!")
                dst.append(f"{result['name']} qemu boot {result['boot']}")

        total_duration = f"Total script duration: {lkt.utils.get_time_diff(self.start_time)}"

        # Print report information to user
        self.show_env_info()
        print(f"\n{total_duration}")

        if self.results['good']:
            lkt.utils.header('List of successful tests')
            print('\n'.join(self.results['good']))

        if self.results['bad']:
            lkt.utils.header('List of failed tests')
            print('\n'.join(self.results['bad']))

        if self.results['skip']:
            lkt.utils.header('List of skipped tests')
            print('\n'.join(self.results['skip']))

        # Generate files for later processing
        info = []
        for label, value in self.env_info.items():
            info.append(f"{label}: {value}")
        info += ['', total_duration, '']  # '' for explicit '\n'
        self.folders.log.mkdir(exist_ok=True, parents=True)
        Path(self.folders.log, 'info.log').write_text('\n'.join(info), encoding='utf-8')

        if self.results['good']:
            txt = '\n\n'.join(self.results['good']) + '\n'
            Path(self.folders.log, 'success.log').write_text(txt, encoding='utf-8')

        if self.results['bad']:
            txt = '\n\n'.join(self.results['bad']) + '\n'
            Path(self.folders.log, 'failed.log').write_text(txt, encoding='utf-8')

        if self.results['skip']:
            txt = '\n\n'.join(self.results['skip']) + '\n'
            Path(self.folders.log, 'skipped.log').write_text(txt, encoding='utf-8')

    def show_env_info(self):
        if not self.env_info:
            self._generate_env_info()

        lkt.utils.header('Environment information')
        for label, value in self.env_info.items():
            print(f"{label}: {value}", flush=True)
