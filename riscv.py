#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import escape, search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, "riscv", log_str, build_folder, kernel_available)

def has_ec3a5cb61146c(linux_folder):
    with open(linux_folder.joinpath("arch", "riscv", "Makefile")) as f:
        return search(escape("KBUILD_CFLAGS += -mno-relax"), f.read())

def has_efi(linux_folder):
    with open(linux_folder.joinpath("arch", "riscv", "Kconfig")) as f:
        return search("config EFI", f.text())

class RISCV:
    def build(self, cfg):
        build_folder = cfg["build_folder"].joinpath("riscv")
        commits_present = cfg["commits_present"]
        configs_present = cfg["configs_present"]
        defconfigs_only = cfg["defconfigs_only"]
        linux_folder = cfg["linux_folder"]
        linux_version_code = cfg["linux_version_code"]
        llvm_version_code = cfg["llvm_version_code"]
        log_folder = cfg["log_folder"]
        make_variables = deepcopy(cfg["make_variables"])
        save_objects = cfg["save_objects"]

        if linux_version_code < 507000:
            lib.header("Skipping riscv kernels")
            print("Reason: RISC-V needs the following fixes from Linux 5.7 to build properly:\n")
            print("        * https://git.kernel.org/linus/52e7c52d2ded5908e6a4f8a7248e5fa6e0d6809a")
            print("        * https://git.kernel.org/linus/fdff9911f266951b14b20e25557278b5b3f0d90d")
            print("        * https://git.kernel.org/linus/abc71bf0a70311ab294f97a7f16e8de03718c05a")
            print("\nProvide a kernel tree with Linux 5.7 or newer to build RISC-V kernels.")
            lib.log(cfg, "riscv kernels skipped due to missing 52e7c52d2ded, fdff9911f266, and/or abc71bf0a703")
            return

        cross_compile = "riscv64-linux-gnu-"

        make_variables["ARCH"] = "riscv"
        if llvm_version_code >= 1300000:
            lib.header("Building riscv kernels", end='')

            make_variables["LLVM_IAS"] = "1"
            if not "6f5b41a2f5a63" in commits_present:
                make_variables["CROSS_COMPILE"] = cross_compile
        else:
            lib.header("Building riscv kernels")

            make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "riscv", cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(gnu_as)
            print(f"binutils version: {binutils_version}")
            print(f"binutils location: {binutils_location}")

        if llvm_version_code < 1300000 or not has_ec3a5cb61146c(linux_folder):
            make_variables["LD"] = cross_compile + "ld"
        else:
            # linux-5.10.y has a build problem with ld.lld
            if linux_version_code <= 510999:
                make_variables["LD"] = cross_compile + "ld"

        log_str = "riscv defconfig"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": lib.log_file_from_str(log_folder, log_str),
            "variables": make_variables,
            "targets": ["distclean", log_str.split(" ")[1]],
        }
        if llvm_version_code < 1300000 and has_efi(linux_folder):
            lib.kmake(kmake_cfg)
            lib.scripts_config(linux_folder, build_folder, ["-d", "EFI"])
            kmake_cfg["targets"] = ["olddefconfig", "all"]
        else:
            kmake_cfg["targets"] += ["all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, build_folder, rc == 0)

        if defconfigs_only:
            if not save_objects:
                rmtree(build_folder)
            return

        if linux_version_code > 508000 and has_ec3a5cb61146c(linux_folder):
            log_str = "riscv allmodconfig"
            configs = []
            if "CONFIG_WERROR" in configs_present:
                configs += ["CONFIG_WERROR"]
            config_path, config_str = lib.gen_allconfig(build_folder, configs)
            if config_path:
                make_variables["KCONFIG_ALLCONFIG"] = config_path
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": lib.log_file_from_str(log_folder, log_str),
                "targets": ["distclean", log_str.split(" ")[1], "all"],
                "variables": make_variables,
            }
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, f"{log_str}{config_str}", rc == 0, time)
            if config_path:
                Path(config_path).unlink()
                del make_variables["KCONFIG_ALLCONFIG"]

        if not save_objects:
            rmtree(build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("riscv64-linux-gnu")
