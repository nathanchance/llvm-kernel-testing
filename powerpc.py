#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import escape, search
from shutil import rmtree, which

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available, arch="ppc64le"):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)

def build_defconfigs(self, cfg):
    log_str = "powerpc ppc44x_defconfig"
    kmake_cfg = {
        "linux_folder": self.linux_folder,
        "build_folder": self.build_folder,
        "log_file": lib.log_file_from_str(self.log_folder, log_str),
        "targets": ["distclean", log_str.split(" ")[1], "all", "uImage"],
        "variables": self.make_variables,
    }
    rc, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, rc == 0, time)
    boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0, "ppc32")

    log_str = "powerpc pmac32_defconfig"
    if has_297565aa22cfa(self.linux_folder):
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": lib.log_file_from_str(self.log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": self.make_variables,
        }
        lib.kmake(kmake_cfg)
        sc_args = ["-e", "SERIAL_PMACZILOG", "-e", "SERIAL_PMACZILOG_CONSOLE"]
        lib.scripts_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], sc_args)
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0, "ppc32_mac")
    else:
        lib.log(cfg, f"{log_str} skipped due to missing 297565aa22cf")

    log_str = "powerpc pseries_defconfig"
    kmake_cfg = {
        "linux_folder": self.linux_folder,
        "build_folder": self.build_folder,
        "log_file": lib.log_file_from_str(self.log_folder, log_str),
        # https://github.com/ClangBuiltLinux/linux/issues/602
        "variables": {**self.make_variables, "LD": self.cross_compile + "ld"},
    }
    pseries_targets = ["distclean", log_str.split(" ")[1]]
    if not has_51696f39cbee5(kmake_cfg["linux_folder"]) and self.llvm_version_code >= 1200000:
        if has_dwc(kmake_cfg["linux_folder"]):
            pseries_targets += ["disable-werror.config", "all"]
        else:
            lib.kmake({**kmake_cfg, "targets": pseries_targets})
            sc_args = ["-e", "PPC_DISABLE_WERROR"]
            lib.scripts_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], sc_args)
            pseries_targets = ["olddefconfig", "all"]
        log_str += "+ CONFIG_PPC_DISABLE_WERROR=y"
    else:
        pseries_targets += ["all"]
    kmake_cfg["targets"] = pseries_targets
    rc, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, rc == 0, time)
    boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0, "ppc64")

    log_str = "powerpc powernv_defconfig"
    kmake_cfg = {
        "linux_folder": self.linux_folder,
        "build_folder": self.build_folder,
        "log_file": lib.log_file_from_str(self.log_folder, log_str),
        "targets": ["distclean", log_str.split(" ")[1], "all"],
        "variables": {**self.make_variables, **self.ppc64le_vars},
    }
    rc, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, rc == 0, time)
    boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)

    log_str = "powerpc ppc64le_defconfig"
    kmake_cfg = {
        "linux_folder": self.linux_folder,
        "build_folder": self.build_folder,
        "log_file": lib.log_file_from_str(self.log_folder, log_str),
        "targets": ["distclean", log_str.split(" ")[1], "all"],
        "variables": {**self.make_variables, **self.ppc64le_vars},
    }
    rc, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, rc == 0, time)

def build_otherconfigs(self, cfg):
    # TODO: allmodconfig should eventually be a part of this.
    other_cfgs = ["allnoconfig", "tinyconfig"]
    for cfg_target in other_cfgs:
        log_str = f"powerpc {cfg_target}"
        if cfg_target == "allmodconfig":
            configs = []
            if "CONFIG_WERROR" in self.configs_present:
                configs += ["CONFIG_WERROR"]
            config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
            if config_path:
                self.make_variables["KCONFIG_ALLCONFIG"] = config_path
        else:
            config_path = None
            config_str = ""
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": lib.log_file_from_str(self.log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1], "all"],
            "variables": self.make_variables,
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, f"{log_str}{config_str}", rc == 0, time)
        if config_path:
            Path(config_path).unlink()
            del self.make_variables["KCONFIG_ALLCONFIG"]

def build_distroconfigs(self, cfg):
    for cfg_file in [("debian", "powerpc64le"), ("fedora", "ppc64le"), ("opensuse", "ppc64le")]:
        distro = cfg_file[0]
        cfg_basename = cfg_file[1] + ".config"
        log_str = f"powerpc {distro}"
        if distro == "opensuse":
            if has_231b232df8f67(self.linux_folder) and self.llvm_version_code <= 1200000:
                lib.log(cfg, f"{log_str} config skipped (https://github.com/ClangBuiltLinux/linux/issues/1160)")
                continue
        sc_cfg = {
            "linux_folder": self.linux_folder,
            "linux_version_code": self.linux_version_code,
            "build_folder": self.build_folder,
            "config_file": self.configs_folder.joinpath(distro, cfg_basename),
        }
        kmake_cfg = {
            "linux_folder": sc_cfg["linux_folder"],
            "build_folder": sc_cfg["build_folder"],
            "log_file": lib.log_file_from_str(self.log_folder, log_str),
            "targets": ["olddefconfig", "all"],
            "variables": {**self.make_variables, **self.ppc64le_vars},
        }
        log_str += lib.setup_config(sc_cfg)
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)

# https://github.com/ClangBuiltLinux/linux/issues/811
def has_0355785313e21(linux_folder):
    with open(linux_folder.joinpath("arch", "powerpc", "Makefile")) as f:
        return search(escape("LDFLAGS_vmlinux-$(CONFIG_RELOCATABLE) += -z notext"), f.read())

# https://github.com/ClangBuiltLinux/linux/issues/1160
def has_231b232df8f67(linux_folder):
    with open(linux_folder.joinpath("arch", "powerpc", "platforms", "Kconfig.cputype")) as f:
        return search("depends on PPC32 || COMPAT", f.read())

# https://github.com/ClangBuiltLinux/linux/issues/563
def has_297565aa22cfa(linux_folder):
    with open(linux_folder.joinpath("arch", "powerpc", "lib", "xor_vmx.c")) as f:
        return search("__restrict", f.read())

# https://github.com/ClangBuiltLinux/linux/issues/1292
def has_51696f39cbee5(linux_folder):
    with open(linux_folder.joinpath("arch", "powerpc", "kvm", "book3s_hv_nested.c")) as f:
        return search("noinline_for_stack void byteswap_pt_regs", f.read())

def has_dwc(linux_folder):
    return linux_folder.joinpath("arch", "powerpc", "configs", "disable-werror.config").exists()

class POWERPC:
    def __init__(self, cfg):
        self.build_folder = cfg["build_folder"].joinpath(self.__class__.__name__.lower())
        self.configs_folder = cfg["configs_folder"]
        self.configs_present = cfg["configs_present"]
        self.linux_folder = cfg["linux_folder"]
        self.linux_version_code = cfg["linux_version_code"]
        self.llvm_version_code = cfg["llvm_version_code"]
        self.log_folder = cfg["log_folder"]
        self.make_variables = deepcopy(cfg["make_variables"])
        self.save_objects = cfg["save_objects"]
        self.targets_to_build = cfg["targets_to_build"]

        self.ppc64le_vars = {}

    def build(self, cfg):
        self.make_variables["ARCH"] = "powerpc"
        for cross_compile in ["powerpc64-linux-gnu-", "powerpc-linux-gnu-"]:
            gnu_as = cross_compile + "as"
            if which(gnu_as):
                break
        self.cross_compile = cross_compile
        self.make_variables["CROSS_COMPILE"] = self.cross_compile

        lib.header("Building powerpc kernels")

        if not lib.check_binutils(cfg, "powerpc", self.cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(gnu_as)
        print(f"binutils version: {binutils_version}")
        print(f"binutils location: {binutils_location}")

        if not has_0355785313e21(self.linux_folder):
            self.ppc64le_vars["LD"] = self.cross_compile + "ld"
        if self.linux_version_code >= 518000 and self.llvm_version_code >= 1400000:
            self.ppc64le_vars["LLVM_IAS"] = "1"

        if "def" in self.targets_to_build:
            build_defconfigs(self, cfg)
        if "other" in self.targets_to_build:
            build_otherconfigs(self, cfg)
        if "distro" in self.targets_to_build:
            build_distroconfigs(self, cfg)

        if not self.save_objects:
            rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("powerpc-linux-gnu")
