#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import escape, search
from shutil import rmtree

import lib


def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, "riscv", log_str, build_folder, kernel_available)


def build_defconfigs(self, cfg):
    log_str = "riscv defconfig"
    kmake_cfg = {
        "linux_folder": self.linux_folder,
        "build_folder": self.build_folder,
        "log_file": lib.log_file_from_str(self.log_folder, log_str),
        "targets": ["distclean", log_str.split(" ")[1]],
        "variables": self.make_variables,
    }
    if self.llvm_version_code < 1300000 and has_efi(self.linux_folder):
        lib.kmake(kmake_cfg)
        lib.scripts_config(kmake_cfg["linux_folder"], kmake_cfg["build_folder"], ["-d", "EFI"])
        kmake_cfg["targets"] = ["olddefconfig", "all"]
    else:
        kmake_cfg["targets"] += ["all"]
    rc, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, rc == 0, time, kmake_cfg["log_file"])
    boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)


def build_otherconfigs(self, cfg):
    if self.linux_version_code > 508000 and has_ec3a5cb61146c(self.linux_folder):
        log_str = "riscv allmodconfig"
        configs = []
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
        lib.log_result(cfg, f"{log_str}{config_str}", rc == 0, time, kmake_cfg["log_file"])
        if config_path:
            Path(config_path).unlink()
            del self.make_variables["KCONFIG_ALLCONFIG"]


def build_distroconfigs(self, cfg):
    if self.linux_version_code > 508000 and has_ec3a5cb61146c(self.linux_folder):
        for cfg_file in [("opensuse", "riscv64")]:
            distro = cfg_file[0]
            cfg_basename = f"{cfg_file[1]}.config"
            log_str = f"riscv {distro} config"
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
                "variables": self.make_variables,
            }
            log_str += lib.setup_config(sc_cfg)
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time, kmake_cfg["log_file"])
            boot_qemu(cfg, log_str, kmake_cfg["build_folder"], rc == 0)


def has_ec3a5cb61146c(linux_folder):
    with open(linux_folder.joinpath("arch", "riscv", "Makefile")) as f:
        return search(escape("KBUILD_CFLAGS += -mno-relax"), f.read())


def has_efi(linux_folder):
    with open(linux_folder.joinpath("arch", "riscv", "Kconfig")) as f:
        return search("config EFI", f.text())


class RISCV:

    def __init__(self, cfg):
        self.build_folder = cfg["build_folder"].joinpath(self.__class__.__name__.lower())
        self.commits_present = cfg["commits_present"]
        self.configs_folder = cfg["configs_folder"]
        self.configs_present = cfg["configs_present"]
        self.linux_folder = cfg["linux_folder"]
        self.linux_version_code = cfg["linux_version_code"]
        self.llvm_version_code = cfg["llvm_version_code"]
        self.log_folder = cfg["log_folder"]
        self.make_variables = deepcopy(cfg["make_variables"])
        self.save_objects = cfg["save_objects"]
        self.targets_to_build = cfg["targets_to_build"]

    def build(self, cfg):
        if self.linux_version_code < 507000:
            lib.header("Skipping riscv kernels")
            print("Reason: RISC-V needs the following fixes from Linux 5.7 to build properly:\n")
            print("        * https://git.kernel.org/linus/52e7c52d2ded5908e6a4f8a7248e5fa6e0d6809a")
            print("        * https://git.kernel.org/linus/fdff9911f266951b14b20e25557278b5b3f0d90d")
            print("        * https://git.kernel.org/linus/abc71bf0a70311ab294f97a7f16e8de03718c05a")
            print("\nProvide a kernel tree with Linux 5.7 or newer to build RISC-V kernels.")
            lib.log(
                cfg,
                "riscv kernels skipped due to missing 52e7c52d2ded, fdff9911f266, and/or abc71bf0a703"
            )
            return

        cross_compile = "riscv64-linux-gnu-"

        self.make_variables["ARCH"] = "riscv"
        if self.llvm_version_code >= 1300000:
            lib.header("Building riscv kernels", end='')

            self.make_variables["LLVM_IAS"] = "1"
            if not "6f5b41a2f5a63" in self.commits_present:
                self.make_variables["CROSS_COMPILE"] = cross_compile
        else:
            lib.header("Building riscv kernels")

            self.make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "riscv", cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(gnu_as)
            print(f"binutils version: {binutils_version}")
            print(f"binutils location: {binutils_location}")

        if self.llvm_version_code < 1300000 or not has_ec3a5cb61146c(self.linux_folder):
            self.make_variables["LD"] = f"{cross_compile}ld"
        else:
            # linux-5.10.y has a build problem with ld.lld
            if self.linux_version_code <= 510999:
                self.make_variables["LD"] = f"{cross_compile}ld"

        if "def" in self.targets_to_build:
            build_defconfigs(self, cfg)
        if "other" in self.targets_to_build:
            build_otherconfigs(self, cfg)
        if "distro" in self.targets_to_build:
            build_distroconfigs(self, cfg)

        if not self.save_objects:
            rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("riscv64-linux-gnu")
