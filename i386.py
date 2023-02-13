#!/usr/bin/env python3

import copy
from pathlib import Path
import platform
import shutil

import lib


def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, 'x86', log_str, build_folder, kernel_available)


def build_defconfigs(self, cfg):
    log_str = 'i386 defconfig'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': lib.log_file_from_str(self.log_folder, log_str),
        'targets': ['distclean', log_str.split(' ')[1], self.default_target],
        'variables': self.make_variables,
    }
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
    boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)

    if has_583bfd484bcc(self.linux_folder):
        log_str = 'i386 defconfig + CONFIG_LTO_CLANG_THIN=y'
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': Path(self.log_folder, 'i386-defconfig-lto.log'),
            'targets': ['distclean', log_str.split(' ')[1]],
            'variables': self.make_variables,
        }
        lib.kmake(kmake_cfg)
        lib.modify_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], 'thinlto')
        kmake_cfg['targets'] = ['olddefconfig', self.default_target]
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)


def build_otherconfigs(self, cfg):
    for cfg_target in ['allmodconfig', 'allnoconfig', 'tinyconfig']:
        if cfg_target == 'allmodconfig':
            configs = []
            if 'CONFIG_WERROR' in self.configs_present:
                configs += ['CONFIG_WERROR']
            if disable_nf_configs(self.llvm_version, self.linux_folder):
                configs += [
                    'CONFIG_IP_NF_TARGET_SYNPROXY',
                    'CONFIG_IP6_NF_TARGET_SYNPROXY',
                    'CONFIG_NFT_SYNPROXY',
                    '(https://github.com/ClangBuiltLinux/linux/issues/1442)',
                ]
            config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
            if config_path:
                self.make_variables['KCONFIG_ALLCONFIG'] = config_path
        else:
            config_path = None
            config_str = ''
        log_str = f"i386 {cfg_target}"
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


def build_distroconfigs(self, cfg):
    for distro in ['debian', 'opensuse']:
        log_str = f"i386 {distro} config"
        sc_cfg = {
            'linux_folder': self.linux_folder,
            'linux_version': self.linux_version,
            'build_folder': self.build_folder,
            'config_file': Path(self.configs_folder, distro, 'i386.config'),
        }
        kmake_cfg = {
            'linux_folder': sc_cfg['linux_folder'],
            'build_folder': sc_cfg['build_folder'],
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['olddefconfig', self.default_target],
            'variables': self.make_variables,
        }
        log_str += lib.setup_config(sc_cfg)
        if disable_nf_configs(self.llvm_version, self.linux_folder):
            log_str += ' + CONFIG_NETFILTER_SYNPROXY=n (https://github.com/ClangBuiltLinux/linux/issues/1442)'
            sc_args = ['-d', 'IP_NF_TARGET_SYNPROXY']
            sc_args += ['-d', 'IP6_NF_TARGET_SYNPROXY']
            sc_args += ['-d', 'NFT_SYNPROXY']
            lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], sc_args)
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])


# https://github.com/ClangBuiltLinux/linux/issues/1442
def disable_nf_configs(llvm_version, linux_folder):
    return llvm_version < (15, 0, 0) and fortify_broken(linux_folder)


def fortify_broken(linux_folder):
    text = lib.get_text(linux_folder, 'security/Kconfig')
    return 'https://bugs.llvm.org/show_bug.cgi?id=50322' in text or 'https://github.com/llvm/llvm-project/issues/53645' in text


# https://git.kernel.org/linus/583bfd484bcc85e9371e7205fa9e827c18ae34fb
def has_583bfd484bcc(linux_folder):
    return 'select ARCH_SUPPORTS_LTO_CLANG_THIN\n' in lib.get_text(linux_folder, 'arch/x86/Kconfig')


# https://git.kernel.org/linus/bb73d07148c405c293e576b40af37737faf23a6a
def has_bb73d07148c40(linux_folder):
    return 'R_386_PLT32:' in lib.get_text(linux_folder, 'arch/x86/tools/relocs.c')


# https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f
def has_d5cbd80e302df(linux_folder):
    return 'CLANG_FLAGS' in lib.get_text(linux_folder, 'arch/x86/boot/compressed/Makefile')


class I386:

    def __init__(self, cfg):
        self.build_folder = Path(cfg['build_folder'], self.__class__.__name__.lower())
        self.commits_present = cfg['commits_present']
        self.configs_folder = cfg['configs_folder']
        self.configs_present = cfg['configs_present']
        self.default_target = 'bzImage' if cfg['boot_testing_only'] else 'all'
        self.linux_folder = cfg['linux_folder']
        self.linux_version = cfg['linux_version']
        self.llvm_version = cfg['llvm_version']
        self.log_folder = cfg['log_folder']
        self.make_variables = copy.deepcopy(cfg['make_variables'])
        self.save_objects = cfg['save_objects']
        self.targets_to_build = cfg['targets_to_build']

    def build(self, cfg):
        if self.linux_version < (5, 9, 0):
            lib.header('Skipping i386 kernels')
            print('Reason: i386 kernels do not build properly prior to Linux 5.9.')
            print('        https://github.com/ClangBuiltLinux/linux/issues/194')
            lib.log(cfg, 'x86 kernels skipped due to missing 158807de5822')
            return
        if self.llvm_version >= (12, 0, 0) and not has_bb73d07148c40(self.linux_folder):
            lib.header('Skipping i386 kernels')
            print(
                'Reason: x86 kernels do not build properly with LLVM 12.0.0+ without R_386_PLT32 handling.'
            )
            print('        https://github.com/ClangBuiltLinux/linux/issues/1210')
            lib.log(cfg, 'x86 kernels skipped due to missing bb73d07148c4 with LLVM > 12.0.0')
            return

        lib.header('Building i386 kernels', end='')

        self.make_variables['ARCH'] = 'i386'
        self.make_variables['LLVM_IAS'] = '1'
        if not (platform.machine() == 'i386' or platform.machine() == 'x86_64'):
            if not has_d5cbd80e302df(self.linux_folder):
                lib.header('Skipping i386 kernels')
                print(
                    'i386 kernels do not cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f.'
                )
                lib.log(cfg,
                        'i386 kernels skipped due to missing d5cbd80e302d on a non-x86_64 host')
                return
            cross_compile = 'x86_64-linux-gnu-'
            if '6f5b41a2f5a63' not in self.commits_present:
                self.make_variables['CROSS_COMPILE'] = cross_compile

        if 'def' in self.targets_to_build:
            build_defconfigs(self, cfg)
        if 'other' in self.targets_to_build:
            build_otherconfigs(self, cfg)
        if 'distro' in self.targets_to_build:
            build_distroconfigs(self, cfg)

        if not self.save_objects:
            shutil.rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target('i386-linux-gnu')
