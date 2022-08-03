#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import escape, search
from shutil import rmtree, which

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available, arch="ppc64le"):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)

# https://github.com/ClangBuiltLinux/linux/issues/811
def has_0355785313e21(linux_folder):
    with open(linux_folder.joinpath("arch", "powerpc", "Makefile")) as f:
        return search(escape("LDFLAGS_vmlinux-$(CONFIG_RELOCATABLE) += -z notext"), f.read())

# https://github.com/ClangBuiltLinux/linux/issues/563
def has_297565aa22cfa(linux_folder):
    with open(linux_folder.joinpath("arch", "powerpc", "lib", "xor_vmx.c")) as f:
        return search("__restrict", f.read())

# https://github.com/ClangBuiltLinux/linux/issues/1292
def has_51696f39cbee5(linux_folder):
    with open(linux_folder.joinpath("arch", "powerpc", "kvm", "book3s_hv_nested.c")) as f:
        return search("noinline_for_stack void byteswap_pt_regs", f.read())

def has_dwc(linux_folder):
    return linux_folder.joinpath("arch", "powerpc", "configs", "disable-werror.config").exists()

class POWERPC:
    def build(self, cfg):
        build_folder = cfg["build_folder"].joinpath("powerpc")
        configs_present = cfg["configs_present"]
        defconfigs_only = cfg["defconfigs_only"]
        linux_folder = cfg["linux_folder"]
        linux_version_code = cfg["linux_version_code"]
        llvm_version_code = cfg["llvm_version_code"]
        log_folder = cfg["log_folder"]
        make_variables = deepcopy(cfg["make_variables"])
        save_objects = cfg["save_objects"]

        make_variables["ARCH"] = "powerpc"
        for cross_compile in ["powerpc64-linux-gnu-", "powerpc-linux-gnu-"]:
            gnu_as = cross_compile + "as"
            if which(gnu_as):
                break
        make_variables["CROSS_COMPILE"] = cross_compile

        lib.header("Building powerpc kernels")

        if not lib.check_binutils(cfg, "powerpc", cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(gnu_as)
        print(f"binutils version: {binutils_version}")
        print(f"binutils location: {binutils_location}")

        log_str = "powerpc ppc44x_defconfig"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": lib.log_file_from_str(log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1], "all", "uImage"],
            "variables": make_variables,
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, build_folder, rc == 0, "ppc32")

        log_str = "powerpc pmac32_defconfig"
        if has_297565aa22cfa(linux_folder):
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": lib.log_file_from_str(log_folder, log_str),
                "targets": ["distclean", log_str.split(" ")[1]],
                "variables": make_variables,
            }
            lib.kmake(kmake_cfg)
            sc_args = ["-e", "SERIAL_PMACZILOG", "-e", "SERIAL_PMACZILOG_CONSOLE"]
            lib.scripts_config(linux_folder, build_folder, sc_args)
            kmake_cfg["targets"] = ["olddefconfig", "all"]
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)
            boot_qemu(cfg, log_str, build_folder, rc == 0, "ppc32_mac")
        else:
            lib.log(cfg, f"{log_str} skipped due to missing 297565aa22cf")

        log_str = "powerpc pseries_defconfig"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": lib.log_file_from_str(log_folder, log_str),
            # https://github.com/ClangBuiltLinux/linux/issues/602
            "variables": {**make_variables, "LD": cross_compile + "ld"},
        }
        pseries_targets = ["distclean", log_str.split(" ")[1]]
        if not has_51696f39cbee5(linux_folder) and llvm_version_code >= 1200000:
            if has_dwc(linux_folder):
                pseries_targets += ["disable-werror.config", "all"]
            else:
                lib.kmake({**kmake_cfg, "targets": pseries_targets})
                lib.scripts_config(linux_folder, build_folder, ["-e", "PPC_DISABLE_WERROR"])
                pseries_targets = ["olddefconfig", "all"]
            log_str += "+ CONFIG_PPC_DISABLE_WERROR=y"
        else:
            pseries_targets += ["all"]
        kmake_cfg["targets"] = pseries_targets
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, build_folder, rc == 0, "ppc64")

        ppc64le_vars = {}
        if linux_version_code >= 518000 and llvm_version_code >= 1400000:
            ppc64le_vars["LLVM_IAS"] = "1"
        log_str = "powerpc powernv_defconfig"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": lib.log_file_from_str(log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1], "all"],
            "variables": {**make_variables, **ppc64le_vars},
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)
        boot_qemu(cfg, log_str, build_folder, rc == 0)

        log_str = "powerpc ppc64le_defconfig"
        if not has_0355785313e21(linux_folder):
            ppc64le_vars["LD"] = cross_compile + "ld"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": lib.log_file_from_str(log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1], "all"],
            "variables": {**make_variables, **ppc64le_vars},
        }
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, log_str, rc == 0, time)

        if defconfigs_only:
            if not save_objects:
                rmtree(build_folder)
            return

        # TODO: allmodconfig should eventually be a part of this.
        other_cfgs = ["allnoconfig", "tinyconfig"]
        for cfg_target in other_cfgs:
            log_str = f"powerpc {cfg_target}"
            if cfg_target == "allmodconfig":
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
        return lib.clang_supports_target("powerpc-linux-gnu")
