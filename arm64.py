#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from platform import machine
from re import search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available, arch="arm64"):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)

class ARM64:
    def build(self, cfg):
        build_folder = cfg["build_folder"].joinpath("arm64")
        commits_present = cfg["commits_present"]
        configs_present = cfg["configs_present"]
        defconfigs_only = cfg["defconfigs_only"]
        linux_folder = cfg["linux_folder"]
        linux_version_code = cfg["linux_version_code"]
        llvm_version_code = cfg["llvm_version_code"]
        log_folder = cfg["log_folder"]
        make_variables = deepcopy(cfg["make_variables"])
        save_objects = cfg["save_objects"]

        lib.header("Building arm64 kernels", end='')

        make_variables["ARCH"] = "arm64"

        if machine() == "aarch64":
            cross_compile = ""
        else:
            cross_compile = "aarch64-linux-gnu-"

        if linux_version_code >= 510000:
            make_variables["LLVM_IAS"] = "1"
            if not "6f5b41a2f5a63" in commits_present and cross_compile:
                make_variables["CROSS_COMPILE"] = cross_compile
        else:
            if cross_compile:
                make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "arm64", cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(f"{cross_compile}as")
            print(f"binutils version: {binutils_version}")
            print(f"binutils location: {binutils_location}\n")

        log_str = "arm64 defconfig"
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

        if llvm_version_code >= 1300000:
            log_str = "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y"
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": log_folder.joinpath("arm64-defconfig-big-endian.log"),
                "targets": ["distclean", log_str.split(" ")[1]],
                "variables": make_variables,
            }
            lib.kmake(kmake_cfg)
            lib.modify_config(linux_folder, build_folder, "big endian")
            kmake_cfg["targets"] = ["olddefconfig", "all"]
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            boot_qemu(cfg, log_str, build_folder, rc == 0, "arm64be")

        if "CONFIG_LTO_CLANG_THIN" in configs_present:
            log_str = "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y"
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": log_folder.joinpath("arm64-defconfig-lto.log"),
                "targets": ["distclean", log_str.split(" ")[1]],
                "variables": make_variables,
            }
            lib.kmake(kmake_cfg)
            lib.modify_config(linux_folder, build_folder, "thinlto")
            kmake_cfg["targets"] = ["olddefconfig", "all"]
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            boot_qemu(cfg, log_str, build_folder, rc == 0)

        if "CONFIG_CFI_CLANG" in configs_present:
            log_str = "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y"
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": log_folder.joinpath("arm64-defconfig-lto-scs-cfi.log"),
                "targets": ["distclean", log_str.split(" ")[1]],
                "variables": make_variables,
            }
            lib.kmake(kmake_cfg)
            lib.modify_config(linux_folder, build_folder, "clang hardening")
            kmake_cfg["targets"] = ["olddefconfig", "all"]
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            boot_qemu(cfg, log_str, build_folder, rc == 0)

        if defconfigs_only:
            if not save_objects:
                rmtree(build_folder)
            return

        log_str = "arm64 allmodconfig"
        configs = []
        with open(linux_folder.joinpath("arch", "arm64", "Kconfig")) as f:
            if not search('prompt "Endianness"', f.read()):
                config += ["CONFIG_CPU_BIG_ENDIAN"]
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

        if "CONFIG_LTO_CLANG_THIN" in configs_present:
            log_str = "arm64 allmodconfig"
            configs = ["CONFIG_GCOV_KERNEL", "CONFIG_KASAN", "CONFIG_LTO_CLANG_THIN=y"]
            if "CONFIG_WERROR" in configs_present:
                configs += ["CONFIG_WERROR"]
            config_path, config_str = lib.gen_allconfig(build_folder, configs)
            log_str += config_str
            if config_path:
                make_variables["KCONFIG_ALLCONFIG"] = config_path
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": log_folder.joinpath("arm64-allmodconfig-thinlto.log"),
                "targets": ["distclean", log_str.split(" ")[1], "all"],
                "variables": make_variables,
            }
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            if config_path:
                Path(config_path).unlink()
                del make_variables["KCONFIG_ALLCONFIG"]

        for cfg_target in ["allnoconfig", "tinyconfig"]:
            log_str = f"arm64 {cfg_target}"
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": lib.log_file_from_str(log_folder, log_str),
                "targets": ["distclean", log_str.split(" ")[1], "all"],
                "variables": make_variables,
            }
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)

        if not save_objects:
            rmtree(build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("aarch64-linux-gnu")
