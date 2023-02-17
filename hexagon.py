#!/usr/bin/env python3

import copy
from pathlib import Path
import shutil

import lib


def build_defconfigs(self, cfg):
    log_str = 'hexagon defconfig'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': lib.log_file_from_str(self.log_folder, log_str),
        'targets': ['distclean', log_str.split(' ')[1], 'all'],
        'variables': self.make_variables,
    }
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])


def build_otherconfigs(self, cfg):
    if has_ffb92ce826fd8(self.linux_folder) and self.llvm_version >= (13, 0, 0):
        log_str = 'hexagon allmodconfig'
        configs = []
        if 'CONFIG_WERROR' in self.configs_present:
            configs += ['CONFIG_WERROR']
        config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
        if config_path:
            self.make_variables['KCONFIG_ALLCONFIG'] = config_path
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['distclean', log_str.split(' ')[1], 'all'],
            'variables': self.make_variables,
        }
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, f"{log_str}{config_str}", return_code == 0, time, kmake_cfg['log_file'])
        if config_path:
            Path(config_path).unlink()
            del self.make_variables['KCONFIG_ALLCONFIG']


def has_ffb92ce826fd8(linux_folder):
    return 'EXPORT_SYMBOL(__raw_readsw)' in lib.get_text(linux_folder, 'arch/hexagon/lib/io.c')


class HEXAGON:

    def __init__(self, cfg):
        self.build_folder = Path(cfg['build_folder'], self.__class__.__name__.lower())
        self.commits_present = cfg['commits_present']
        self.configs_present = cfg['configs_present']
        self.linux_folder = cfg['linux_folder']
        self.llvm_version = cfg['llvm_version']
        self.log_folder = cfg['log_folder']
        self.make_variables = copy.deepcopy(cfg['make_variables'])
        self.save_objects = cfg['save_objects']
        self.targets_to_build = cfg['targets_to_build']

    def build(self, cfg):
        if cfg['boot_testing_only']:
            lib.header('Skipping hexagon kernels')
            print('Only boot testing was requested')
            lib.log(cfg, 'hexagon kernels skipped due to boot testing only')
            return

        self.make_variables['ARCH'] = 'hexagon'
        self.make_variables['LLVM_IAS'] = '1'
        if '6f5b41a2f5a63' not in self.commits_present:
            self.make_variables['CROSS_COMPILE'] = 'hexagon-linux-musl-'

        has_788dcee0306e1 = 'KBUILD_CFLAGS += -mlong-calls' in lib.get_text(
            self.linux_folder, 'arch/hexagon/Makefile')
        has_f1f99adf05f21 = Path(self.linux_folder, 'arch/hexagon/lib/divsi3.S').exists()
        if not (has_788dcee0306e1 and has_f1f99adf05f21):
            lib.header('Skipping hexagon kernels')
            print('Hexagon needs the following fixes from Linux 5.13 to build properly:\n')
            print('  * https://git.kernel.org/linus/788dcee0306e1bdbae1a76d1b3478bb899c5838e')
            print('  * https://git.kernel.org/linus/6fff7410f6befe5744d54f0418d65a6322998c09')
            print('  * https://git.kernel.org/linus/f1f99adf05f2138ff2646d756d4674e302e8d02d')
            print(
                '\nProvide a kernel tree with Linux 5.13+ or one with these fixes to build Hexagon kernels.',
            )
            lib.log(
                cfg,
                'hexagon kernels skipped due to missing 788dcee0306e, 6fff7410f6be, and/or f1f99adf05f2',
            )
            return

        lib.header('Building hexagon kernels', end='')

        if 'def' in self.targets_to_build:
            build_defconfigs(self, cfg)
        if 'other' in self.targets_to_build:
            build_otherconfigs(self, cfg)

        if not self.save_objects:
            shutil.rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target('hexagon-linux-musl')
