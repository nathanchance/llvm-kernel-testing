#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, "s390", log_str, build_folder, kernel_available)

def has_integrated_as_support(linux_folder):
    with open(linux_folder.joinpath("arch", "s390", "Makefile")) as f:
        return search("ifndef CONFIG_AS_IS_LLVM", f.read())
    with open(linux_folder.joinpath("arch", "s390", "kernel", "entry.S")) as f:
        return search("ifdef CONFIG_AS_IS_LLVM", f.read())

class S390:
    def build(self, cfg):
        build_folder = cfg["build_folder"].joinpath("s390")
        commits_present = cfg["commits_present"]
        configs_present = cfg["configs_present"]
        defconfigs_only = cfg["defconfigs_only"]
        linux_folder = cfg["linux_folder"]
        llvm_version_code = ["llvm_version_code"]
        linux_version_code = cfg["linux_version_code"]
        log_folder = cfg["log_folder"]
        make_variables = deepcopy(cfg["make_variables"])
        save_objects = cfg["save_objects"]

        if linux_version_code < 506000:
            lib.header("Skipping s390x kernels")
            print("Reason: s390 kernels did not build properly until Linux 5.6")
            print("        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/")
            lib.log(cfg, "s390x kernels skipped due to missing fixes from 5.6 (https://lore.kernel.org/r/your-ad-here.call-01580230449-ext-6884@work.hours/)")
            return

        cross_compile = "s390x-linux-gnu-"
        make_variables["ARCH"] = "s390"

        for variable in ["LD", "OBJCOPY", "OBJDUMP"]:
            make_variables[variable] = cross_compile + variable.lower()

        if has_integrated_as_support(linux_folder):
            make_variables["LLVM_IAS"] = "1"
        else:
            make_variables["CROSS_COMPILE"] = cross_compile

        lib.header("Building s390 kernels")

        if not lib.check_binutils(cfg, "s390", cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(f"{cross_compile}as")
        print(f"binutils version: {binutils_version}")
        print(f"binutils location: {binutils_location}")

        log_str = "s390 defconfig"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": lib.log_file_from_str(log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1], "all"],
            "variables": make_variables,
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, build_folder, rc == 0)

        if defconfigs_only:
            if not save_objects:
                rmtree(build_folder)
            return

        for other_cfg in ["allmodconfig", "allnoconfig", "tinyconfig"]:
            log_str = f"s390 {other_cfg}"
            if other_cfg == "allmodconfig":
                configs = []
                if "CONFIG_WERROR" in configs_present:
                    configs += ["CONFIG_WERROR"]
                config_path, config_str = lib.gen_allconfig(build_folder, configs)
                if config_path:
                    make_variables["KCONFIG_ALLCONFIG"] = config_path
            else:
                config_path = None
                config_str = ""
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
        return lib.clang_supports_target("s390x-linux-gnu")
