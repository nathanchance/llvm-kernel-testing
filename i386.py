#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from platform import machine
from re import search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, "x86", log_str, build_folder, kernel_available)

def build_defconfigs(self, cfg):
    log_str = "i386 defconfig"
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

    if has_583bfd484bcc(self.linux_folder):
        log_str = "i386 defconfig + CONFIG_LTO_CLANG_THIN=y"
        kmake_cfg = {
            "linux_folder": self.linux_folder,
            "build_folder": self.build_folder,
            "log_file": self.log_folder.joinpath("i386-defconfig-lto.log"),
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
    for cfg_target in ["allmodconfig", "allnoconfig", "tinyconfig"]:
        if cfg_target == "allmodconfig":
            configs = []
            if "CONFIG_WERROR" in self.configs_present:
                configs += ["CONFIG_WERROR"]
            if disable_nf_configs(self.llvm_version_code, self.linux_folder):
                configs += ["CONFIG_IP_NF_TARGET_SYNPROXY"]
                configs += ["CONFIG_IP6_NF_TARGET_SYNPROXY"]
                configs += ["CONFIG_NFT_SYNPROXY"]
                configs += ["(https://github.com/ClangBuiltLinux/linux/issues/1442)"]
            config_path, config_str = lib.gen_allconfig(self.build_folder, configs)
            if config_path:
                self.make_variables["KCONFIG_ALLCONFIG"] = config_path
        else:
            config_path = None
            config_str = ""
        log_str = f"i386 {cfg_target}"
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

# https://github.com/ClangBuiltLinux/linux/issues/1442
def disable_nf_configs(llvm_version_code, linux_folder):
    return llvm_version_code < 1500000 and fortify_broken(linux_folder)

def fortify_broken(linux_folder):
    with open(linux_folder.joinpath("security", "Kconfig")) as f:
        text = f.read()
        bug_one = "https://bugs.llvm.org/show_bug.cgi?id=50322"
        bug_two = "https://github.com/llvm/llvm-project/issues/53645"
        return search(bug_one, text) or search(bug_two, text)

# https://git.kernel.org/linus/583bfd484bcc85e9371e7205fa9e827c18ae34fb
def has_583bfd484bcc(linux_folder):
    with open(linux_folder.joinpath("arch", "x86", "Kconfig")) as f:
        text = f.read()
        lto = "select ARCH_SUPPORTS_LTO_CLANG_THIN"
        lto_x86_64 = "select ARCH_SUPPORTS_LTO_CLANG_THIN\tif X86_64"
        return search(lto, text) and not search(lto_x86_64, text)

# https://git.kernel.org/linus/bb73d07148c405c293e576b40af37737faf23a6a
def has_bb73d07148c40(linux_folder):
    with open(linux_folder.joinpath("arch", "x86", "tools", "relocs.c")) as f:
        return search("R_386_PLT32:", f.read())

# https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f
def has_d5cbd80e302df(linux_folder):
    with open(linux_folder.joinpath("arch", "x86", "boot", "compressed", "Makefile")) as f:
        return search("CLANG_FLAGS", f.read())

class I386:
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
        if self.linux_version_code < 509000:
            lib.header("Skipping i386 kernels")
            print("Reason: i386 kernels do not build properly prior to Linux 5.9.")
            print("        https://github.com/ClangBuiltLinux/linux/issues/194")
            lib.log(cfg, "x86 kernels skipped due to missing 158807de5822")
            return
        elif self.llvm_version_code >= 1200000 and not has_bb73d07148c40(self.linux_folder):
            lib.header("Skipping i386 kernels")
            print("Reason: x86 kernels do not build properly with LLVM 12.0.0+ without R_386_PLT32 handling.")
            print("        https://github.com/ClangBuiltLinux/linux/issues/1210")
            lib.log(cfg, "x86 kernels skipped due to missing bb73d07148c4 with LLVM > 12.0.0")
            return

        self.make_variables["ARCH"] = "i386"
        self.make_variables["LLVM_IAS"] = "1"
        if machine() == "i386" or machine() == "x86_64":
            lib.header("Building i386 kernels", end='')
        else:
            if not has_d5cbd80e302df(self.linux_folder):
                lib.header("Skipping i386 kernels")
                print("i386 kernels do not cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f.")
                lib.log(cfg, "i386 kernels skipped due to missing d5cbd80e302d on a non-x86_64 host")
                return
            lib.header("Building i386 kernels")
            cross_compile = "x86_64-linux-gnu-"
            if not "6f5b41a2f5a63" in self.commits_present:
                self.make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "i386", cross_compile):
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
        return lib.clang_supports_target("i386-linux-gnu")
