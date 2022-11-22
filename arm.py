#!/usr/bin/env python3

import copy
import pathlib
import re
import shutil

import lib


def boot_qemu(cfg, log_str, build_folder, kernel_available, arch='arm32_v7'):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)


def disable_be(linux_folder):
    with open(linux_folder.joinpath('arch', 'arm', 'mm', 'Kconfig'), encoding='utf-8') as file:
        text = file.read()
        first_pattern = 'bool "Build big-endian kernel"'
        second_pattern = 'depends on ARCH_SUPPORTS_BIG_ENDIAN'
        return not re.search(f"({first_pattern}|{second_pattern})\n\tdepends on !LD_IS_LLD", text)


def has_nwfpe_replexitval(linux_folder):
    with open(linux_folder.joinpath('arch', 'arm', 'nwfpe', 'Makefile'), encoding='utf-8') as file:
        return re.search('replexitval=never', file.read())


# https://github.com/ClangBuiltLinux/linux/issues/325
def thumb2_ok(linux_folder):
    with open(linux_folder.joinpath('arch', 'arm', 'Kconfig'), encoding='utf-8') as file:
        has_9d417cbe36eee = re.search('select HAVE_FUTEX_CMPXCHG if FUTEX', file.read())
    with open(linux_folder.joinpath('init', 'Kconfig'), encoding='utf-8') as file:
        has_3297481d688a5 = not re.search('config HAVE_FUTEX_CMPXCHG', file.read())
    return has_9d417cbe36eee or has_3297481d688a5


def build_defconfigs(self, cfg):
    defconfigs = [('multi_v5_defconfig', 'arm32_v5')]
    defconfigs += [('aspeed_g5_defconfig', 'arm32_v6')]
    defconfigs += [('multi_v7_defconfig', 'arm32_v7')]
    for defconfig in defconfigs:
        log_str = f"arm {defconfig[0]}"
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['distclean', log_str.split(' ')[1], 'all'],
            'variables': self.make_variables,
        }
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0, defconfig[1])

    if thumb2_ok(self.linux_folder):
        log_str = 'arm multi_v7_defconfig + CONFIG_THUMB2_KERNEL=y'
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': self.log_folder.joinpath('arm-defconfig-thumb2.log'),
            'targets': ['distclean', log_str.split(' ')[1]],
            'variables': self.make_variables,
        }
        lib.kmake(kmake_cfg)
        lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'],
                           ['-e', 'THUMB2_KERNEL'])
        kmake_cfg['targets'] = ['olddefconfig', 'all']
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0, defconfig[1])


def build_otherconfigs(self, cfg):
    for cfg_target in ['allmodconfig', 'allnoconfig', 'tinyconfig']:
        log_str = f"arm {cfg_target}"
        if cfg_target == 'allmodconfig':
            configs = []
            if disable_be(self.linux_folder):
                configs += ['CONFIG_CPU_BIG_ENDIAN']
            if 'CONFIG_WERROR' in self.configs_present:
                configs += ['CONFIG_WERROR']
            if not has_nwfpe_replexitval(self.linux_folder):
                if self.llvm_version_code >= 1500000:
                    configs += [
                        'CONFIG_FPE_NWFPE', '(https://github.com/ClangBuiltLinux/linux/issues/1666)'
                    ]
            config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
            if config_path:
                self.make_variables['KCONFIG_ALLCONFIG'] = config_path
        else:
            config_path = None
            config_str = ''
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
            pathlib.Path(config_path).unlink()
            del self.make_variables['KCONFIG_ALLCONFIG']


def build_distroconfigs(self, cfg):
    cfg_files = [('alpine', 'armv7')]
    cfg_files += [('archlinux', 'armv7')]
    cfg_files += [('debian', 'armmp')]
    cfg_files += [('fedora', 'armv7hl')]
    cfg_files += [('opensuse', 'armv7hl')]
    for cfg_file in cfg_files:
        distro = cfg_file[0]
        cfg_basename = f"{cfg_file[1]}.config"
        log_str = f"arm {distro} config"
        sc_cfg = {
            'linux_folder': self.linux_folder,
            'linux_version_code': self.linux_version_code,
            'build_folder': self.build_folder,
            'config_file': self.configs_folder.joinpath(distro, cfg_basename),
        }
        kmake_cfg = {
            'linux_folder': sc_cfg['linux_folder'],
            'build_folder': sc_cfg['build_folder'],
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['olddefconfig', 'all'],
            'variables': self.make_variables,
        }
        log_str += lib.setup_config(sc_cfg)
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        if distro != 'fedora':
            boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)


class ARM:

    def __init__(self, cfg):
        self.build_folder = cfg['build_folder'].joinpath(self.__class__.__name__.lower())
        self.commits_present = cfg['commits_present']
        self.configs_folder = cfg['configs_folder']
        self.configs_present = cfg['configs_present']
        self.linux_folder = cfg['linux_folder']
        self.linux_version_code = cfg['linux_version_code']
        self.llvm_version_code = cfg['llvm_version_code']
        self.log_folder = cfg['log_folder']
        self.make_variables = copy.deepcopy(cfg['make_variables'])
        self.save_objects = cfg['save_objects']
        self.targets_to_build = cfg['targets_to_build']

    def build(self, cfg):
        lib.header('Building arm kernels', end='')

        self.make_variables['ARCH'] = 'arm'

        for cross_compile in ['arm-linux-gnu-', 'arm-linux-gnueabihf-', 'arm-linux-gnueabi-']:
            gnu_as = f"{cross_compile}as"
            if shutil.which(gnu_as):
                break

        if self.llvm_version_code >= 1300000 and self.linux_version_code >= 513000:
            self.make_variables['LLVM_IAS'] = '1'
            if '6f5b41a2f5a63' not in self.commits_present:
                self.make_variables['CROSS_COMPILE'] = cross_compile
        else:
            self.make_variables['CROSS_COMPILE'] = cross_compile
            if not lib.check_binutils(cfg, 'arm', cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(gnu_as)
            print(f"\nbinutils version: {binutils_version}")
            print(f"binutils location: {binutils_location}")

        if 'def' in self.targets_to_build:
            build_defconfigs(self, cfg)
        if 'other' in self.targets_to_build:
            build_otherconfigs(self, cfg)
        if 'distro' in self.targets_to_build:
            build_distroconfigs(self, cfg)

        if not self.save_objects:
            shutil.rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target('arm-linux-gnueabi')
