#!/usr/bin/env python3

import copy
from pathlib import Path
import shutil

import lib


def boot_qemu(cfg, log_str, build_folder, kernel_available, arch='ppc64le'):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)


def build_defconfigs(self, cfg):
    log_str = 'powerpc ppc44x_defconfig'
    if has_2255411d1d0f0(self.linux_folder):
        lib.log(
            cfg,
            f"{log_str} skipped due to 2255411d1d0f0 (https://github.com/ClangBuiltLinux/linux/issues/1679)",
        )
    else:
        targets = ['uImage']
        if not self.boot_testing_only:
            targets.insert(0, 'all')
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['distclean', log_str.split(' ')[1], *targets],
            'variables': self.make_variables,
        }
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        if self.llvm_version < (12, 0, 1) and has_48cf12d88969b(kmake_cfg['linux_folder']):
            lib.log(
                cfg,
                f"{log_str} qemu_boot skipped (https://github.com/ClangBuiltLinux/linux/issues/1345)",
            )
        else:
            boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0, 'ppc32')

    log_str = 'powerpc pmac32_defconfig'
    if has_297565aa22cfa(self.linux_folder):
        kmake_cfg = {
            'linux_folder': self.linux_folder,
            'build_folder': self.build_folder,
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['distclean', log_str.split(' ')[1]],
            'variables': self.make_variables,
        }
        lib.kmake(kmake_cfg)
        sc_args = ['-e', 'SERIAL_PMACZILOG', '-e', 'SERIAL_PMACZILOG_CONSOLE']
        lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], sc_args)
        kmake_cfg['targets'] = ['olddefconfig', 'vmlinux' if self.boot_testing_only else 'all']
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        if self.llvm_version >= (14, 0, 0):
            boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0, 'ppc32_mac')
        else:
            lib.log(cfg,
                    f"{log_str} qemu boot skipped due to LLVM < 14.0.0 (lack of 1e3c6fc7cb9d2)")
    else:
        lib.log(
            cfg,
            f"{log_str} skipped due to missing 297565aa22cf (https://github.com/ClangBuiltLinux/linux/issues/563)",
        )

    log_str = 'powerpc pseries_defconfig'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': lib.log_file_from_str(self.log_folder, log_str),
        # https://github.com/ClangBuiltLinux/linux/issues/602
        'variables': {
            **self.make_variables,
            'LD': f"{self.cross_compile}ld",
        },
    }
    pseries_targets = ['distclean', log_str.split(' ')[1]]
    # https://github.com/ClangBuiltLinux/linux/issues/1292
    wa_cbl_1292 = not has_51696f39cbee5(
        kmake_cfg['linux_folder']) and self.llvm_version >= (12, 0, 0)
    # https://github.com/ClangBuiltLinux/linux/issues/1445
    wa_cbl_1445 = self.linux_version >= (5, 18, 0) and self.llvm_version < (14, 0, 0)
    final_target = 'vmlinux' if self.boot_testing_only else 'all'
    if wa_cbl_1292 or wa_cbl_1445:
        if has_dwc(kmake_cfg['linux_folder']):
            pseries_targets += ['disable-werror.config', final_target]
        else:
            lib.kmake({**kmake_cfg, 'targets': pseries_targets})
            sc_args = ['-e', 'PPC_DISABLE_WERROR']
            lib.scripts_config(kmake_cfg['linux_folder'], kmake_cfg['build_folder'], sc_args)
            pseries_targets = ['olddefconfig', final_target]
        log_str += '+ CONFIG_PPC_DISABLE_WERROR=y'
    else:
        pseries_targets += [final_target]
    kmake_cfg['targets'] = pseries_targets
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
    boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0, 'ppc64')

    log_str = 'powerpc powernv_defconfig'
    powernv_vars = {}
    if self.llvm_version < (12, 0, 0) and 'LD' not in self.ppc64le_vars:
        powernv_vars = {'LD': f"{self.cross_compile}ld"}
    final_target = 'zImage.epapr' if self.boot_testing_only else 'all'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': lib.log_file_from_str(self.log_folder, log_str),
        'targets': ['distclean', log_str.split(' ')[1], final_target],
        'variables': {
            **self.make_variables,
            **self.ppc64le_vars,
            **powernv_vars,
        },
    }
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
    boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)

    if self.boot_testing_only:
        return

    log_str = 'powerpc ppc64le_defconfig'
    kmake_cfg = {
        'linux_folder': self.linux_folder,
        'build_folder': self.build_folder,
        'log_file': lib.log_file_from_str(self.log_folder, log_str),
        'targets': ['distclean', log_str.split(' ')[1], 'all'],
        'variables': {
            **self.make_variables,
            **self.ppc64le_vars,
        },
    }
    return_code, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])


def build_otherconfigs(self, cfg):
    other_cfgs = ['allnoconfig', 'tinyconfig']  # eventually allmodconfig...
    for cfg_target in other_cfgs:
        log_str = f"powerpc {cfg_target}"
        if cfg_target == 'allmodconfig':
            configs = []
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
            Path(config_path).unlink()
            del self.make_variables['KCONFIG_ALLCONFIG']


def build_distroconfigs(self, cfg):
    for cfg_file in [('debian', 'powerpc64le'), ('fedora', 'ppc64le'), ('opensuse', 'ppc64le')]:
        distro = cfg_file[0]
        cfg_basename = f"{cfg_file[1]}.config"
        log_str = f"powerpc {distro} config"
        if distro == 'opensuse':  # noqa: SIM102
            if has_231b232df8f67(self.linux_folder) and self.llvm_version <= (12, 0, 0):
                lib.log(
                    cfg,
                    f"{log_str} config skipped (https://github.com/ClangBuiltLinux/linux/issues/1160)",
                )
                continue
        sc_cfg = {
            'linux_folder': self.linux_folder,
            'linux_version': self.linux_version,
            'build_folder': self.build_folder,
            'config_file': Path(self.configs_folder, distro, cfg_basename),
        }
        kmake_cfg = {
            'linux_folder': sc_cfg['linux_folder'],
            'build_folder': sc_cfg['build_folder'],
            'log_file': lib.log_file_from_str(self.log_folder, log_str),
            'targets': ['olddefconfig', 'zImage.epapr' if self.boot_testing_only else 'all'],
            'variables': {
                **self.make_variables,
                **self.ppc64le_vars,
            },
        }
        log_str += lib.setup_config(sc_cfg)
        return_code, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, return_code == 0, time, kmake_cfg['log_file'])
        boot_qemu(cfg, log_str, kmake_cfg['build_folder'], return_code == 0)


# https://github.com/ClangBuiltLinux/linux/issues/811
def has_0355785313e21(linux_folder):
    text = lib.get_text(linux_folder, 'arch/powerpc/Makefile')
    return 'LDFLAGS_vmlinux-$(CONFIG_RELOCATABLE) += -z notext' in text


# https://github.com/ClangBuiltLinux/linux/issues/1679
def has_2255411d1d0f0(linux_folder):
    text = lib.get_text(linux_folder, 'arch/powerpc/platforms/Kconfig.cputype')
    return 'config POWERPC_CPU\n\tbool "Generic 32 bits powerpc"\n\tdepends on PPC_BOOK3S_32' in text


# https://github.com/ClangBuiltLinux/linux/issues/1160
def has_231b232df8f67(linux_folder):
    text = lib.get_text(linux_folder, 'arch/powerpc/platforms/Kconfig.cputype')
    return 'depends on PPC32 || COMPAT' in text


# https://github.com/ClangBuiltLinux/linux/issues/563
def has_297565aa22cfa(linux_folder):
    return '__restrict' in lib.get_text(linux_folder, 'arch/powerpc/lib/xor_vmx.c')


# https://github.com/ClangBuiltLinux/linux/issues/1345
def has_48cf12d88969b(linux_folder):
    text = lib.get_text(linux_folder, 'arch/powerpc/kernel.irq.c')
    return 'static __always_inline void call_do_softirq(const void *sp)' in text


# https://github.com/ClangBuiltLinux/linux/issues/1292
def has_51696f39cbee5(linux_folder):
    text = lib.get_text(linux_folder, 'arch/powerpc/kvm/book3s_hv_nested.c')
    return 'noinline_for_stack void byteswap_pt_regs' in text


def has_dwc(linux_folder):
    return Path(linux_folder, 'arch/powerpc/configs/disable-werror.config').exists()


def get_cross_compile():
    for cross_compile in ['powerpc64-linux-gnu-', 'powerpc-linux-gnu-']:
        gnu_as = f"{cross_compile}as"
        if shutil.which(gnu_as):
            return cross_compile
    return None


class POWERPC:

    def __init__(self, cfg):
        self.boot_testing_only = cfg['boot_testing_only']
        self.build_folder = Path(cfg['build_folder'], self.__class__.__name__.lower())
        self.configs_folder = cfg['configs_folder']
        self.configs_present = cfg['configs_present']
        self.cross_compile = get_cross_compile()
        self.linux_folder = cfg['linux_folder']
        self.linux_version = cfg['linux_version']
        self.llvm_version = cfg['llvm_version']
        self.log_folder = cfg['log_folder']
        self.make_variables = copy.deepcopy(cfg['make_variables'])
        self.save_objects = cfg['save_objects']
        self.targets_to_build = cfg['targets_to_build']

        self.ppc64le_vars = {}

    def build(self, cfg):
        self.make_variables['ARCH'] = 'powerpc'
        self.make_variables['CROSS_COMPILE'] = self.cross_compile

        lib.header('Building powerpc kernels')

        if not lib.check_binutils(cfg, 'powerpc', self.cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(f"{self.cross_compile}as")
        print(f"binutils version: {binutils_version}")
        print(f"binutils location: {binutils_location}")

        if not has_0355785313e21(self.linux_folder):
            self.ppc64le_vars['LD'] = f"{self.cross_compile}ld"
        if self.linux_version >= (5, 18, 0) and self.llvm_version >= (14, 0, 0):
            self.ppc64le_vars['LLVM_IAS'] = '1'

        if 'def' in self.targets_to_build:
            build_defconfigs(self, cfg)
        if 'other' in self.targets_to_build:
            build_otherconfigs(self, cfg)
        if 'distro' in self.targets_to_build:
            build_distroconfigs(self, cfg)

        if not self.save_objects:
            shutil.rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target('powerpc-linux-gnu')
