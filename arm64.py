#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from platform import machine
from re import search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available, arch="arm64"):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)

def build_defconfigs(self, cfg):
    log_str = "arm64 defconfig"
    kmake_cfg = {
        "linux_folder": self.linux_folder,
        "build_folder": self.build_folder,
        "log_file": lib.log_file_from_str(self.log_folder, log_str),
        "targets": ["distclean", log_str.split(" ")[1], "all"],
        "variables": self.make_variables,
    }
    rc, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, rc == 0, time)
    boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)

    if self.llvm_version_code >= 1300000:
        log_str = "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y"
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": self.log_folder.joinpath("arm64-defconfig-big-endian.log"),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": self.make_variables,
        }
        lib.kmake(kmake_cfg)
        lib.modify_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], "big endian")
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0, "arm64be")

    if "CONFIG_LTO_CLANG_THIN" in self.configs_present:
        log_str = "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y"
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": self.log_folder.joinpath("arm64-defconfig-lto.log"),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": self.make_variables,
        }
        lib.kmake(kmake_cfg)
        lib.modify_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], "thinlto")
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)

    if "CONFIG_CFI_CLANG" in self.configs_present:
        log_str = "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y"
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": self.log_folder.joinpath("arm64-defconfig-lto-scs-cfi.log"),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": self.make_variables,
        }
        lib.kmake(kmake_cfg)
        lib.modify_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], "clang hardening")
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)

def build_otherconfigs(self, cfg):
    log_str = "arm64 allmodconfig"
    configs = []
    if not has_d8e85e144bbe1(self.linux_folder):
            config += ["CONFIG_CPU_BIG_ENDIAN"]
    if "CONFIG_WERROR" in self.configs_present:
        configs += ["CONFIG_WERROR"]
    config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
    if config_path:
        self.make_variables["KCONFIG_ALLCONFIG"] = config_path
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

    if "CONFIG_LTO_CLANG_THIN" in self.configs_present:
        log_str = "arm64 allmodconfig"
        configs = ["CONFIG_GCOV_KERNEL", "CONFIG_KASAN", "CONFIG_LTO_CLANG_THIN=y"]
        if "CONFIG_WERROR" in self.configs_present:
            configs += ["CONFIG_WERROR"]
        config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
        log_str += config_str
        if config_path:
            self.make_variables["KCONFIG_ALLCONFIG"] = config_path
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": self.log_folder.joinpath("arm64-allmodconfig-thinlto.log"),
            "targets": ["distclean", log_str.split(" ")[1], "all"],
            "variables": self.make_variables,
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        if config_path:
            Path(config_path).unlink()
            del self.make_variables["KCONFIG_ALLCONFIG"]

    for cfg_target in ["allnoconfig", "tinyconfig"]:
        log_str = f"arm64 {cfg_target}"
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": lib.log_file_from_str(self.log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1], "all"],
            "variables": self.make_variables,
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)

def has_d8e85e144bbe1(linux_folder):
    with open(linux_folder.joinpath("arch", "arm64", "Kconfig")) as f:
        return search('prompt "Endianness"', f.read())

class ARM64:
    def __init__(self, cfg):
        self.build_folder = cfg["build_folder"].joinpath(self.__class__.__name__.lower())
        self.commits_present = cfg["commits_present"]
        self.configs_present = cfg["configs_present"]
        self.linux_folder = cfg["linux_folder"]
        self.linux_version_code = cfg["linux_version_code"]
        self.llvm_version_code = cfg["llvm_version_code"]
        self.log_folder = cfg["log_folder"]
        self.make_variables = deepcopy(cfg["make_variables"])
        self.save_objects = cfg["save_objects"]
        self.targets_to_build = cfg["targets_to_build"]

    def build(self, cfg):
        lib.header("Building arm64 kernels", end='')

        self.make_variables["ARCH"] = "arm64"

        if machine() == "aarch64":
            cross_compile = ""
        else:
            cross_compile = "aarch64-linux-gnu-"

        if self.linux_version_code >= 510000:
            self.make_variables["LLVM_IAS"] = "1"
            if not "6f5b41a2f5a63" in self.commits_present and cross_compile:
                self.make_variables["CROSS_COMPILE"] = cross_compile
        else:
            if cross_compile:
                self.make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "arm64", cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(f"{cross_compile}as")
            print(f"binutils version: {binutils_version}")
            print(f"binutils location: {binutils_location}\n")

        if "def" in self.targets_to_build:
            build_defconfigs(self, cfg)
        if "other" in self.targets_to_build:
            build_otherconfigs(self, cfg)

        if not self.save_objects:
            rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("aarch64-linux-gnu")
