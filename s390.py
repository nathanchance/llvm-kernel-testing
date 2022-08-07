#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, "s390", log_str, build_folder, kernel_available)

def build_defconfigs(self, cfg):
    log_str = "s390 defconfig"
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

def build_otherconfigs(self, cfg):
    for other_cfg in ["allmodconfig", "allnoconfig", "tinyconfig"]:
        log_str = f"s390 {other_cfg}"
        if other_cfg == "allmodconfig":
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
    for distro in ["debian", "fedora", "opensuse"]:
        log_str = f"s390 {distro}"
        sc_cfg = {
            "linux_folder": self.linux_folder,
            "linux_version_code": self.linux_version_code,
            "build_folder": self.build_folder,
            "config_file": self.configs_folder.joinpath(distro, "s390x.config"),
        }
        kmake_cfg = {
            "linux_folder": sc_cfg["linux_folder"],
            "build_folder": sc_cfg["build_folder"],
            "log_file": lib.log_file_from_str(self.log_folder, log_str),
            "targets": ["olddefconfig", "all"],
            "variables": self.make_variables,
        }
        log_str += lib.setup_config(sc_cfg)
        if distro == "fedora" and not has_efe5e0fea4b24(kmake_cfg["linux_folder"]):
            log_str += " + CONFIG_MARCH_Z196=y (https://github.com/ClangBuiltLinux/linux/issues/1264)"
            sc_args = ["-d", "MARCH_ZEC12", "-e", "MARCH_Z196"]
            lib.scripts_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], sc_args)
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)

# https://git.kernel.org/linus/efe5e0fea4b24872736c62a0bcfc3f99bebd2005
def has_efe5e0fea4b24(linux_folder):
    with open(linux_folder.joinpath("arch", "s390", "include", "asm", "bitops.h")) as f:
        return not search('"(o|n|x)i\t%0,%b1\\\\n"', f.read())

def has_integrated_as_support(linux_folder):
    with open(linux_folder.joinpath("arch", "s390", "Makefile")) as f:
        return search("ifndef CONFIG_AS_IS_LLVM", f.read())
    with open(linux_folder.joinpath("arch", "s390", "kernel", "entry.S")) as f:
        return search("ifdef CONFIG_AS_IS_LLVM", f.read())

class S390:
    def __init__(self, cfg):
        self.build_folder = cfg["build_folder"].joinpath(self.__class__.__name__.lower())
        self.commits_present = cfg["commits_present"]
        self.configs_folder = cfg["configs_folder"]
        self.configs_present = cfg["configs_present"]
        self.linux_folder = cfg["linux_folder"]
        self.llvm_version_code = ["llvm_version_code"]
        self.linux_version_code = cfg["linux_version_code"]
        self.log_folder = cfg["log_folder"]
        self.make_variables = deepcopy(cfg["make_variables"])
        self.save_objects = cfg["save_objects"]
        self.targets_to_build = cfg["targets_to_build"]

    def build(self, cfg):
        if self.linux_version_code < 506000:
            lib.header("Skipping s390x kernels")
            print("Reason: s390 kernels did not build properly until Linux 5.6")
            print("        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/")
            lib.log(cfg, "s390x kernels skipped due to missing fixes from 5.6 (https://lore.kernel.org/r/your-ad-here.call-01580230449-ext-6884@work.hours/)")
            return

        cross_compile = "s390x-linux-gnu-"
        self.make_variables["ARCH"] = "s390"

        for variable in ["LD", "OBJCOPY", "OBJDUMP"]:
            self.make_variables[variable] = cross_compile + variable.lower()

        if has_integrated_as_support(self.linux_folder):
            self.make_variables["LLVM_IAS"] = "1"
        else:
            self.make_variables["CROSS_COMPILE"] = cross_compile

        lib.header("Building s390 kernels")

        if not lib.check_binutils(cfg, "s390", cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(f"{cross_compile}as")
        print(f"binutils version: {binutils_version}")
        print(f"binutils location: {binutils_location}")

        if "def" in self.targets_to_build:
            build_defconfigs(self, cfg)
        if "other" in self.targets_to_build:
            build_otherconfigs(self, cfg)
        if "distro" in self.targets_to_build:
            build_distroconfigs(self, cfg)

        if not self.save_objects:
            rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("s390x-linux-gnu")
