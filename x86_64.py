#!/usr/bin/env python3

import copy
from pathlib import Path
import platform
import shutil

import lib


def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, 'x86_64', log_str, build_folder, kernel_available)


def build_defconfigs(self, cfg):
    log_str = 'x86_64 defconfig'
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

    if 'CONFIG_LTO_CLANG_THIN' in self.configs_present:
        log_str = 'x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y'
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': Path(self.log_folder, 'x86_64-defconfig-lto.log'),
            'targets': ['distclean', log_str.split(' ')[1]],
            'variables': self.make_variables,
        }
        lib.kmake(kmake_cfg)
        lib.modify_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], 'thinlto')
        kmake_cfg['targets'] = ['olddefconfig', self.default_target]
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)

    if lib.has_kcfi(self.linux_folder):
        build_cfi_kernel(self, cfg)
        build_cfi_kernel(self, cfg, use_lto=True)


def build_otherconfigs(self, cfg):
    log_str = 'x86_64 allmodconfig'
    configs = []
    if 'CONFIG_WERROR' in self.configs_present:
        configs += ['CONFIG_WERROR']
    if self.linux_version < (5, 7, 0):
        configs += [
            'CONFIG_STM', 'CONFIG_TEST_MEMCAT_P',
            '(https://github.com/ClangBuiltLinux/linux/issues/515)'
        ]
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

    if 'CONFIG_LTO_CLANG_THIN' in self.configs_present:
        log_str = 'x86_64 allmodconfig'
        configs = ['CONFIG_GCOV_KERNEL', 'CONFIG_KASAN', 'CONFIG_LTO_CLANG_THIN=y']
        # https://github.com/ClangBuiltLinux/linux/issues/1704
        if self.llvm_version >= (16, 0, 0) and not has_tsan_mem_funcs(self.linux_folder):
            configs += ['CONFIG_KCSAN']
            if should_disable_kmsan(self.linux_folder, self.configs_present):
                configs += [
                    'CONFIG_KMSAN', '(https://github.com/ClangBuiltLinux/linux/issues/1741)'
                ]
        if 'CONFIG_WERROR' in self.configs_present:
            configs += ['CONFIG_WERROR']
        config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
        log_str += config_str
        self.make_variables['KCONFIG_ALLCONFIG'] = config_path
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': Path(self.log_folder, 'x86_64-allmodconfig-thinlto.log'),
            'targets': ['distclean', log_str.split(' ')[1], 'all'],
            'variables': self.make_variables,
        }
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        if config_path:
            Path(config_path).unlink()
            del self.make_variables['KCONFIG_ALLCONFIG']


def build_distroconfigs(self, cfg):
    cfg_files = [
        ('alpine', 'x86_64'),
        ('archlinux', 'x86_64'),
        ('debian', 'amd64'),
        ('fedora', 'x86_64'),
        ('opensuse', 'x86_64'),
    ]
    for cfg_file in cfg_files:
        distro = cfg_file[0]
        cfg_basename = f"{cfg_file[1]}.config"
        log_str = f"x86_64 {distro} config"
        sc_cfg = {
            'linux_folder': self.linux_folder,
            'linux_version': self.linux_version,
            'build_folder': self.build_folder,
            'config_file': Path(self.configs_folder, distro, cfg_basename),
        }
        has_x32 = lib.is_set(sc_cfg['linux_folder'], sc_cfg['build_folder'], 'X86_X32_ABI')
        need_gnu_objcopy = not has_aaeed6ecc1253(sc_cfg['linux_folder'])
        if has_x32 and need_gnu_objcopy:
            gnu_objcopy = {'OBJCOPY': f"{self.cross_compile}objcopy"}
        else:
            gnu_objcopy = {}
        kmake_cfg = {
            'linux_folder': sc_cfg['linux_folder'],
            'build_folder': sc_cfg['build_folder'],
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['olddefconfig', self.default_target],
            'variables': {
                **self.make_variables,
                **gnu_objcopy
            },
        }
        log_str += lib.setup_config(sc_cfg)
        if self.linux_version < (5, 7, 0):
            sc_args = []
            for cfg_sym in ['STM', 'TEST_MEMCAT_P']:
                if lib.is_set(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], cfg_sym):
                    log_str += f" + CONFIG_{cfg_sym}=n"
                    sc_args += ['-d', cfg_sym]
            if sc_args:
                log_str += ' (https://github.com/ClangBuiltLinux/linux/issues/515)'
                lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], sc_args)
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)


def build_cfi_kernel(self, cfg, use_lto=False):
    if use_lto:
        log_str = 'x86_64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_LTO_CLANG_THIN=y'
        log_file = 'x86_64-defconfig-cfi-lto.log'
    else:
        log_str = 'x86_64 defconfig + CONFIG_CFI_CLANG=y'
        log_file = 'x86_64-defconfig-cfi.log'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': Path(self.log_folder, log_file),
        'targets': ['distclean', log_str.split(' ')[1]],
        'variables': self.make_variables,
    }
    lib.kmake(kmake_cfg)
    sc_args = ['-e', 'CFI_CLANG']
    if use_lto:
        sc_args += ['-d', 'LTO_NONE']
        sc_args += ['-e', 'LTO_CLANG_THIN']
    lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], sc_args)
    kmake_cfg['targets'] = ['olddefconfig', self.default_target]
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
    boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)


# https://github.com/ClangBuiltLinux/linux/issues/514
# https://git.kernel.org/linus/aaeed6ecc1253ce1463fa1aca0b70a4ccbc9fa75
def has_aaeed6ecc1253(linux_folder):
    text = lib.get_text(linux_folder, 'arch/x86/Kconfig')
    return 'https://github.com/ClangBuiltLinux/linux/issues/514' in text


# https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f
def has_d5cbd80e302df(linux_folder):
    return 'CLANG_FLAGS' in lib.get_text(linux_folder, 'arch/x86/boot/compressed/Makefile')


# https://github.com/ClangBuiltLinux/linux/issues/1704
def has_tsan_mem_funcs(linux_folder):
    return '__tsan_memset' in lib.get_text(linux_folder, 'kernel/kcsan/core.c')


# https://github.com/ClangBuiltLinux/linux/issues/1741
def should_disable_kmsan(linux_folder, configs_present):
    if 'CONFIG_KMSAN' in configs_present:
        return not Path(linux_folder, 'include/linux/kmsan_string.h').exists()
    return False


class X86_64:  # pylint: disable=invalid-name

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

        self.cross_compile = ''

    def build(self, cfg):
        if platform.machine() != 'x86_64':
            if not has_d5cbd80e302df(self.linux_folder):
                lib.header('Skipping x86_64 kernels')
                print(
                    'x86_64 kernels do not cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f'
                )
                lib.log(cfg,
                        'x86_64 kernels skipped due to missing d5cbd80e302d on a non-x86_64 host')
                return
            self.cross_compile = 'x86_64-linux-gnu-'

        self.make_variables['ARCH'] = 'x86_64'

        lib.header('Building x86_64 kernels', end='')

        if self.linux_version >= (5, 10, 0):
            self.make_variables['LLVM_IAS'] = '1'
            if '6f5b41a2f5a63' not in self.commits_present and self.cross_compile:
                self.make_variables['CROSS_COMPILE'] = self.cross_compile
        else:
            if self.cross_compile:
                self.make_variables['CROSS_COMPILE'] = self.cross_compile
            if not lib.check_binutils(cfg, 'x86_64', self.cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(f"{self.cross_compile}as")
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
        return lib.clang_supports_target('x86_64-linux-gnu')
