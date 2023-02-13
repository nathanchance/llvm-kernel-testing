#!/usr/bin/env python3

import copy
from pathlib import Path
import shutil

import lib


def boot_qemu(cfg, log_str, build_folder, kernel_available, arch='mipsel'):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)


def build_defconfigs(self, cfg):
    log_str = 'mips malta_defconfig'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': lib.log_file_from_str(self.log_folder, log_str),
        'targets': ['distclean', log_str.split(' ')[1]],
        'variables': self.make_variables,
    }
    lib.kmake(kmake_cfg)
    if self.sc_args:
        lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], self.sc_args)
    kmake_cfg['targets'] = ['olddefconfig', self.default_target]
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, f"{log_str}{self.config_str}", return_code == 0, time,
                   kmake_cfg['log_file'])
    boot_qemu(cfg, f"{log_str}{self.config_str}", kmake_cfg['build_folder'], return_code == 0)

    log_str = 'mips malta_defconfig + CONFIG_RANDOMIZE_BASE=y'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': Path(self.log_folder, 'mips-malta_defconfig-kaslr.log'),
        'targets': ['distclean', log_str.split(' ')[1]],
        'variables': self.make_variables,
    }
    lib.kmake(kmake_cfg)
    kaslr_sc_args = [
        *copy.deepcopy(self.sc_args),
        '-e', 'RELOCATABLE',
        '--set-val', 'RELOCATION_TABLE_SIZE', '0x00200000',
        '-e', 'RANDOMIZE_BASE',
    ]  # yapf: disable
    lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], kaslr_sc_args)
    kmake_cfg['targets'] = ['olddefconfig', self.default_target]
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, f"{log_str}{self.config_str}", return_code == 0, time,
                   kmake_cfg['log_file'])
    boot_qemu(cfg, f"{log_str}{self.config_str}", kmake_cfg['build_folder'], return_code == 0)

    log_str = 'mips malta_defconfig + CONFIG_CPU_BIG_ENDIAN=y'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': Path(self.log_folder, 'mips-malta_defconfig-big-endian.log'),
        'targets': ['distclean', log_str.split(' ')[1]],
        'variables': {
            **self.make_variables,
            **self.ld_bfd
        },
    }
    lib.kmake(kmake_cfg)
    lib.modify_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], 'big endian')
    if self.sc_args:
        lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], self.sc_args)
    kmake_cfg['targets'] = ['olddefconfig', self.default_target]
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, f"{log_str}{self.config_str}", return_code == 0, time,
                   kmake_cfg['log_file'])
    boot_qemu(cfg, f"{log_str}{self.config_str}", kmake_cfg['build_folder'], return_code == 0,
              'mips')

    if self.boot_testing_only:
        return

    generic_cfgs = ['32r1', '32r1el', '32r2', '32r2el']
    if self.llvm_version >= (12, 0, 0):
        generic_cfgs += ['32r6', '32r6el']
    for generic_cfg in generic_cfgs:
        log_str = f"mips {generic_cfg}_defconfig"
        generic_make_variables = {}
        if '32r1' in generic_cfg:
            generic_make_variables['CROSS_COMPILE'] = self.cross_compile
            generic_make_variables['LLVM_IAS'] = '0'
        if 'el' not in generic_cfg:
            generic_make_variables.update(self.ld_bfd)
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['distclean', log_str.split(' ')[1], 'all'],
            'variables': {
                **self.make_variables,
                **generic_make_variables
            },
        }
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])


def build_otherconfigs(self, cfg):
    for cfg_target in ['allnoconfig', 'tinyconfig']:
        log_str = f"mips {cfg_target}"
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['distclean', log_str.split(' ')[1], 'all'],
            'variables': {
                **self.make_variables,
                **self.ld_bfd
            },
        }
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])


# https://git.kernel.org/mips/c/c47c7ab9b53635860c6b48736efdd22822d726d7
def has_c47c7ab9b5363(linux_folder):
    return 'CONFIG_BLK_DEV_INITRD=y' in lib.get_text(linux_folder,
                                                     'arch/mips/configs/malta_defconfig')


def has_e91946d6d93ef(linux_folder):
    return Path(linux_folder, 'arch/mips/vdso/Kconfig').exists()


class MIPS:

    def __init__(self, cfg):
        self.boot_testing_only = cfg['boot_testing_only']
        self.build_folder = Path(cfg['build_folder'], self.__class__.__name__.lower())
        self.linux_folder = cfg['linux_folder']
        self.linux_version = cfg['linux_version']
        self.llvm_version = cfg['llvm_version']
        self.default_target = 'vmlinux' if self.boot_testing_only else 'all'
        self.log_folder = cfg['log_folder']
        self.make_variables = copy.deepcopy(cfg['make_variables'])
        self.save_objects = cfg['save_objects']
        self.targets_to_build = cfg['targets_to_build']

        self.cross_compile = ''
        self.config_str = ''
        self.ld_bfd = {}
        self.sc_args = []

    def build(self, cfg):
        self.make_variables['ARCH'] = 'mips'

        lib.header('Building mips kernels')

        for cross_compile in ['mips64-linux-gnu-', 'mips-linux-gnu-', 'mipsel-linux-gnu-']:
            gnu_as = f"{cross_compile}as"
            if shutil.which(gnu_as):
                break
        self.cross_compile = cross_compile

        if self.linux_version >= (5, 15, 0):
            self.make_variables['LLVM_IAS'] = '1'
        else:
            self.make_variables['CROSS_COMPILE'] = self.cross_compile

        if not lib.check_binutils(cfg, 'mips', self.cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(gnu_as)
        print(f"binutils version: {binutils_version}")
        print(f"binutils location: {binutils_location}")

        if not has_c47c7ab9b5363(self.linux_folder):
            self.config_str += ' + CONFIG_BLK_DEV_INITRD=y'
            self.sc_args += ['-e', 'BLK_DEV_INITRD']

        # https://github.com/ClangBuiltLinux/linux/issues/1025
        if has_e91946d6d93ef(self.linux_folder) and self.llvm_version < (13, 0, 0):
            self.ld_bfd = {'LD': f"{self.cross_compile}ld"}

        if 'def' in self.targets_to_build:
            build_defconfigs(self, cfg)
        if 'other' in self.targets_to_build:
            build_otherconfigs(self, cfg)

        if not self.save_objects:
            shutil.rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target('mips-linux-gnu')
