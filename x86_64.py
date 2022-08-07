#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from platform import machine
from re import search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, "x86_64", log_str, build_folder, kernel_available)

def build_defconfigs(self, cfg):
    log_str = "x86_64 defconfig"
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

    if "CONFIG_LTO_CLANG_THIN" in self.configs_present:
        log_str = "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y"
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": self.log_folder.joinpath("x86_64-defconfig-lto.log"),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": self.make_variables,
        }
        lib.kmake(kmake_cfg)
        lib.modify_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], "thinlto")
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)

def build_otherconfigs(self, cfg):
    log_str = "x86_64 allmodconfig"
    configs = []
    if "CONFIG_WERROR" in self.configs_present:
        configs += ["CONFIG_WERROR"]
    if self.linux_version_code < 507000:
        configs += ["CONFIG_STM", "CONFIG_TEST_MEMCAT_P", "(https://github.com/ClangBuiltLinux/linux/issues/515)"]
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
        log_str = "x86_64 allmodconfig"
        configs = ["CONFIG_GCOV_KERNEL", "CONFIG_KASAN", "CONFIG_LTO_CLANG_THIN=y"]
        if "CONFIG_WERROR" in self.configs_present:
            configs += ["CONFIG_WERROR"]
        config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
        log_str += config_str
        self.make_variables["KCONFIG_ALLCONFIG"] = config_path
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": self.log_folder.joinpath("x86_64-allmodconfig-thinlto.log"),
            "targets": ["distclean", log_str.split(" ")[1], "all"],
            "variables": self.make_variables,
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        if config_path:
            Path(config_path).unlink()
            del self.make_variables["KCONFIG_ALLCONFIG"]

# https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f
def has_d5cbd80e302df(linux_folder):
    with open(linux_folder.joinpath("arch", "x86", "boot", "compressed", "Makefile")) as f:
        return search("CLANG_FLAGS", f.read())

class X86_64:
    def __init__(self, cfg):
        self.build_folder = cfg["build_folder"].joinpath(self.__class__.__name__.lower())
        self.commits_present = cfg["commits_present"]
        self.configs_present = cfg["configs_present"]
        self.linux_folder = cfg["linux_folder"]
        self.linux_version_code = cfg["linux_version_code"]
        self.log_folder = cfg["log_folder"]
        self.make_variables = deepcopy(cfg["make_variables"])
        self.save_objects = cfg["save_objects"]
        self.targets_to_build = cfg["targets_to_build"]

    def build(self, cfg):
        if machine() == "x86_64":
            cross_compile = ""
        else:
            if not has_d5cbd80e302df(self.linux_folder):
                lib.header("Skipping x86_64 kernels")
                print("x86_64 kernels do not cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f")
                lib.log(cfg, "x86_64 kernels skipped due to missing d5cbd80e302d on a non-x86_64 host")
                return
            cross_compile = "x86_64-linux-gnu-"

        lib.header("Building x86_64 kernels", end='')

        self.make_variables["ARCH"] = "x86_64"

        if self.linux_version_code >= 510000:
            self.make_variables["LLVM_IAS"] = "1"
            if not "6f5b41a2f5a63" in self.commits_present and cross_compile:
                self.make_variables["CROSS_COMPILE"] = cross_compile
        else:
            if cross_compile:
                self.make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "x86_64", cross_compile):
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
        return lib.clang_supports_target("x86_64-linux-gnu")
