#!/usr/bin/env python3

import copy
import pathlib
import re
import shutil

import lib


def boot_qemu(self, cfg, log_str, build_folder, kernel_available):
    if self.qemu_version_code < 600000:
        qemu_ver = lib.get_qemu_version(self.qemu_exec)
        lib.log(
            cfg,
            f"{log_str} qemu boot skipped due to skipped due to a QEMU binary older than 6.0.0 (found {qemu_ver})"
        )
    lib.boot_qemu(cfg, 's390', log_str, build_folder, kernel_available)


def build_defconfigs(self, cfg):
    log_str = 's390 defconfig'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': lib.log_file_from_str(self.log_folder, log_str),
        'targets': ['distclean', log_str.split(' ')[1], 'all'],
        'variables': self.make_variables,
    }
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
    boot_qemu(self, cfg, log_str, kmake_cfg['build_folder'], return_code == 0)


def build_otherconfigs(self, cfg):
    other_cfgs = ['allmodconfig']
    skipped_cfgs = []
    if self.binutils_version_code < 239050 or not is_relocatable_a_choice(self.linux_folder):
        other_cfgs += ['allnoconfig', 'tinyconfig']
    else:
        skipped_cfgs += ['allnoconfig', 'tinyconfig']
    for other_cfg in other_cfgs:
        log_str = f"s390 {other_cfg}"
        if other_cfg == 'allmodconfig':
            configs = []
            if has_925d046e7e52(self.linux_folder):
                configs += ['CONFIG_INFINIBAND_ADDR_TRANS']
                configs += ['(https://github.com/ClangBuiltLinux/linux/issues/1687)']
            if 'CONFIG_WERROR' in self.configs_present:
                configs += ['CONFIG_WERROR']
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
            del self.make_variables["KCONFIG_ALLCONFIG"]
    if skipped_cfgs:
        for skipped_cfg in skipped_cfgs:
            lib.log(
                cfg,
                f"s390 {skipped_cfg} skipped due to linker error with CONFIG_RELOCATABLE=n (https://github.com/ClangBuiltLinux/linux/issues/1747)"
            )


def build_distroconfigs(self, cfg):
    for distro in ['debian', 'fedora', 'opensuse']:
        log_str = f"s390 {distro} config"
        sc_cfg = {
            'linux_folder': self.linux_folder,
            'linux_version_code': self.linux_version_code,
            'build_folder': self.build_folder,
            'config_file': self.configs_folder.joinpath(distro, 's390x.config'),
        }
        kmake_cfg = {
            'linux_folder': sc_cfg['linux_folder'],
            'build_folder': sc_cfg['build_folder'],
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['olddefconfig', 'all'],
            'variables': self.make_variables,
        }
        log_str += lib.setup_config(sc_cfg)
        if distro == 'fedora' and not has_efe5e0fea4b24(kmake_cfg['linux_folder']):
            log_str += ' + CONFIG_MARCH_Z196=y (https://github.com/ClangBuiltLinux/linux/issues/1264)'
            sc_args = ['-d', 'MARCH_ZEC12', '-e', 'MARCH_Z196']
            lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], sc_args)
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        boot_qemu(self, cfg, log_str, kmake_cfg['build_folder'], return_code == 0)


# https://github.com/ClangBuiltLinux/linux/issues/1687
# https://git.kernel.org/linus/925d046e7e52c71c3531199ce137e141807ef740
def has_925d046e7e52(linux_folder):
    with open(linux_folder.joinpath('drivers', 'infiniband', 'core', 'cma.c'),
              encoding='utf-8') as file:
        return re.search('static void cma_netevent_work_handler', file.read())


# https://git.kernel.org/linus/efe5e0fea4b24872736c62a0bcfc3f99bebd2005
def has_efe5e0fea4b24(linux_folder):
    with open(linux_folder.joinpath('arch', 's390', 'include', 'asm', 'bitops.h'),
              encoding='utf-8') as file:
        return not re.search('"(o|n|x)i\t%0,%b1\\\\n"', file.read())


def has_integrated_as_support(linux_folder):
    with open(linux_folder.joinpath('arch', 's390', 'Makefile'), encoding='utf-8') as file:
        has_bb31074db95f735 = re.search('ifndef CONFIG_AS_IS_LLVM', file.read())
    with open(linux_folder.joinpath('arch', 's390', 'kernel', 'entry.S'), encoding='utf-8') as file:
        has_4c25f0ff6336738 = re.search('ifdef CONFIG_AS_IS_LLVM', file.read())
    return has_bb31074db95f735 and has_4c25f0ff6336738


def is_relocatable_a_choice(linux_folder):
    with open(linux_folder.joinpath('arch', 's390', 'Kconfig'), encoding='utf-8') as file:
        return re.search('config RELOCATABLE\n\tbool "', file.read())


class S390:

    def __init__(self, cfg):
        self.build_folder = cfg['build_folder'].joinpath(self.__class__.__name__.lower())
        self.commits_present = cfg['commits_present']
        self.configs_folder = cfg['configs_folder']
        self.configs_present = cfg['configs_present']
        self.cross_compile = 's390x-linux-gnu-'
        self.binutils_version_code = lib.create_binutils_version_code(f"{self.cross_compile}as")
        self.linux_folder = cfg['linux_folder']
        self.llvm_version_code = cfg['llvm_version_code']
        self.linux_version_code = cfg['linux_version_code']
        self.log_folder = cfg['log_folder']
        self.make_variables = copy.deepcopy(cfg['make_variables'])
        self.qemu_exec = 'qemu-system-s390x'
        self.qemu_version_code = lib.create_qemu_version_code(self.qemu_exec)
        self.save_objects = cfg['save_objects']
        self.targets_to_build = cfg['targets_to_build']

    def build(self, cfg):
        if self.linux_version_code < 506000:
            lib.header('Skipping s390x kernels')
            print('Reason: s390 kernels did not build properly until Linux 5.6')
            print(
                '        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/'
            )
            lib.log(
                cfg,
                's390x kernels skipped due to missing fixes from 5.6 (https://lore.kernel.org/r/your-ad-here.call-01580230449-ext-6884@work.hours/)'
            )
            return
        if self.linux_version_code >= 514000 and self.llvm_version_code < 1300000:
            lib.header('Skipping s390x kernels')
            print('Reason: s390 kernels cannot build with LLVM versions prior to 13.0.0 on 5.14+.')
            print('        https://git.kernel.org/linus/e2bc3e91d91ede6710801fa0737e4e4ed729b19e')
            lib.log(cfg,
                    's390x kernels skipped due to LLVM < 13.0.0 and Linux 5.14+ (e2bc3e91d91ed)')
            return
        if self.linux_version_code >= 519000 and self.llvm_version_code < 1400000:
            lib.header('Skipping s390x kernels')
            print('Reason: s390 kernels cannot build with LLVM versions prior to 14.0.0 on 5.19+.')
            print('        https://git.kernel.org/linus/8218827b73c6e41029438a2d3cc573286beee914')
            lib.log(cfg,
                    's390x kernels skipped due to LLVM < 14.0.0 and Linux 5.19+ (8218827b73c6e)')
            return

        self.make_variables['ARCH'] = 's390'

        for variable in ['LD', 'OBJCOPY', 'OBJDUMP']:
            self.make_variables[variable] = f"{self.cross_compile}{variable.lower()}"

        if has_integrated_as_support(self.linux_folder):
            self.make_variables['LLVM_IAS'] = '1'
        else:
            self.make_variables['CROSS_COMPILE'] = self.cross_compile

        lib.header('Building s390 kernels')

        if not lib.check_binutils(cfg, 's390', self.cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(f"{self.cross_compile}as")
        print(f"binutils version: {binutils_version}")
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
        return lib.clang_supports_target('s390x-linux-gnu')
