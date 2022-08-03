#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import search
from shutil import rmtree, which

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available, arch="arm32_v7"):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)

def disable_be(linux_folder):
    with open(linux_folder.joinpath("arch", "arm", "mm", "Kconfig")) as f:
        text = f.read()
        first_pattern = 'bool "Build big-endian kernel"'
        second_pattern = "depends on ARCH_SUPPORTS_BIG_ENDIAN"
        return not search(f"({first_pattern}|{second_pattern})\n\tdepends on !LD_IS_LLD", text)

# https://github.com/ClangBuiltLinux/linux/issues/325
def thumb2_ok(linux_folder):
    with open(linux_folder.joinpath("arch", "arm", "Kconfig")) as f:
        has_9d417cbe36eee = search("select HAVE_FUTEX_CMPXCHG if FUTEX", f.read())
    with open(linux_folder.joinpath("init", "Kconfig")) as f:
        has_3297481d688a5 = not search("config HAVE_FUTEX_CMPXCHG", f.read())
    return has_9d417cbe36eee or has_3297481d688a5

class ARM:
    def build(self, cfg):
        build_folder = cfg["build_folder"].joinpath("arm")
        commits_present = cfg["commits_present"]
        configs_present = cfg["configs_present"]
        defconfigs_only = cfg["defconfigs_only"]
        linux_folder = cfg["linux_folder"]
        linux_version_code = cfg["linux_version_code"]
        llvm_version_code = cfg["llvm_version_code"]
        log_folder = cfg["log_folder"]
        make_variables = deepcopy(cfg["make_variables"])
        save_objects = cfg["save_objects"]

        lib.header("Building arm kernels", end='')

        make_variables["ARCH"] = "arm"

        for cross_compile in ["arm-linux-gnu-", "arm-linux-gnueabihf-", "arm-linux-gnueabi-"]:
            gnu_as = cross_compile + "as"
            if which(gnu_as):
                break

        if llvm_version_code >= 1300000 and linux_version_code >= 513000:
            make_variables["LLVM_IAS"] = "1"
            if not "6f5b41a2f5a63" in commits_present:
                make_variables["CROSS_COMPILE"] = cross_compile
        else:
            make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "arm", cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(gnu_as)
            print(f"binutils version: {binutils_version}")
            print(f"binutils location: {binutils_location}\n")

        defconfigs = [("multi_v5_defconfig", "arm32_v5")]
        defconfigs += [("aspeed_g5_defconfig", "arm32_v6")]
        defconfigs += [("multi_v7_defconfig", "arm32_v7")]
        for defconfig in defconfigs:
            log_str = f"arm {defconfig[0]}"
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": lib.log_file_from_str(log_folder, log_str),
                "targets": ["distclean", log_str.split(" ")[1], "all"],
                "variables": make_variables,
            }
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            boot_qemu(cfg, log_str, build_folder, rc == 0, defconfig[1])

        if thumb2_ok(linux_folder):
            log_str = "arm multi_v7_defconfig + CONFIG_THUMB2_KERNEL=y"
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": log_folder.joinpath("arm-defconfig-thumb2.log"),
                "targets": ["distclean", log_str.split(" ")[1]],
                "variables": make_variables,
            }
            lib.kmake(kmake_cfg)
            lib.scripts_config(linux_folder, build_folder, ["-e", "THUMB2_KERNEL"])
            kmake_cfg["targets"] = ["olddefconfig", "all"]
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            boot_qemu(cfg, log_str, build_folder, rc == 0)

        if defconfigs_only:
            if not save_objects:
                rmtree(build_folder)
            return

        for cfg_target in ["allmodconfig", "allnoconfig", "tinyconfig"]:
            log_str = f"arm {cfg_target}"
            if cfg_target == "allmodconfig":
                configs = []
                if disable_be(linux_folder):
                    configs += ["CONFIG_CPU_BIG_ENDIAN"]
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
        return lib.clang_supports_target("arm-linux-gnueabi")
