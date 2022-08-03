#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from platform import machine
from re import search
from shutil import rmtree

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available):
    lib.boot_qemu(cfg, "x86_64", log_str, build_folder, kernel_available)

class X86_64:
    def build(self, cfg):
        build_folder = cfg["build_folder"].joinpath("x86_64")
        commits_present = cfg["commits_present"]
        configs_present = cfg["configs_present"]
        defconfigs_only = cfg["defconfigs_only"]
        linux_folder = cfg["linux_folder"]
        linux_version_code = cfg["linux_version_code"]
        log_folder = cfg["log_folder"]
        make_variables = deepcopy(cfg["make_variables"])
        save_objects = cfg["save_objects"]

        if machine() == "x86_64":
            cross_compile = ""
        else:
            makefile = linux_folder.joinpath("arch", "x86", "boot", "compressed", "Makefile")
            with open(makefile) as f:
                if not search("CLANG_FLAGS", f.read()):
                    lib.header("Skipping x86_64 kernels")
                    print("x86 kernels do not cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f")
                    lib.log(cfg, "x86_64 kernels skipped due to missing d5cbd80e302d on a non-x86_64 host")
                    return
            cross_compile = "x86_64-linux-gnu-"

        lib.header("Building x86_64 kernels", end='')

        make_variables["ARCH"] = "x86_64"

        if linux_version_code >= 510000:
            make_variables["LLVM_IAS"] = "1"
            if not "6f5b41a2f5a63" in commits_present and cross_compile:
                make_variables["CROSS_COMPILE"] = cross_compile
        else:
            if cross_compile:
                make_variables["CROSS_COMPILE"] = cross_compile
            if not lib.check_binutils(cfg, "x86_64", cross_compile):
                return
            binutils_version, binutils_location = lib.get_binary_info(f"{cross_compile}as")
            print(f"binutils version: {binutils_version}")
            print(f"binutils location: {binutils_location}\n")

        log_str = "x86_64 defconfig"
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

        if "CONFIG_LTO_CLANG_THIN" in configs_present:
            log_str = "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y"
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": log_folder.joinpath("x86_64-defconfig-lto.log"),
                "targets": ["distclean", log_str.split(" ")[1]],
                "variables": make_variables,
            }
            lib.kmake(kmake_cfg)
            lib.modify_config(linux_folder, build_folder, "thinlto")
            kmake_cfg["targets"] = ["olddefconfig", "all"]
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            boot_qemu(cfg, log_str, build_folder, rc == 0)

        if defconfigs_only:
            if not save_objects:
                rmtree(build_folder)
            return

        log_str = "x86_64 allmodconfig"
        configs = []
        if "CONFIG_WERROR" in configs_present:
            configs += ["CONFIG_WERROR"]
        if linux_version_code < 507000:
            configs += ["CONFIG_STM", "CONFIG_TEST_MEMCAT_P", "(https://github.com/ClangBuiltLinux/linux/issues/515)"]
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
            log_str = "x86_64 allmodconfig"
            configs = ["CONFIG_GCOV_KERNEL", "CONFIG_KASAN", "CONFIG_LTO_CLANG_THIN=y"]
            if "CONFIG_WERROR" in configs_present:
                configs += ["CONFIG_WERROR"]
            config_path, config_str = lib.gen_allconfig(build_folder, configs)
            log_str += config_str
            make_variables["KCONFIG_ALLCONFIG"] = config_path
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": log_folder.joinpath("x86_64-allmodconfig-thinlto.log"),
                "targets": ["distclean", log_str.split(" ")[1], "all"],
                "variables": make_variables,
            }
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            if config_path:
                Path(config_path).unlink()
                del make_variables["KCONFIG_ALLCONFIG"]

        if not save_objects:
            rmtree(build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("x86_64-linux-gnu")
