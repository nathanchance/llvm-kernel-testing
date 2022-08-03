#!/usr/bin/env python3

from copy import deepcopy
from re import search
from shutil import rmtree, which

import lib

def boot_qemu(cfg, log_str, build_folder, kernel_available, arch="mipsel"):
    lib.boot_qemu(cfg, arch, log_str, build_folder, kernel_available)

class MIPS:
    def build(self, cfg):
        build_folder = cfg["build_folder"].joinpath("mips")
        configs_present = cfg["configs_present"]
        defconfigs_only = cfg["defconfigs_only"]
        linux_folder = cfg["linux_folder"]
        linux_version_code = cfg["linux_version_code"]
        llvm_version_code = cfg["llvm_version_code"]
        log_folder = cfg["log_folder"]
        make_variables = deepcopy(cfg["make_variables"])
        save_objects = cfg["save_objects"]

        make_variables["ARCH"] = "mips"

        lib.header("Building mips kernels")

        for cross_compile in ["mips64-linux-gnu-", "mipsel-linux-gnu-"]:
            gnu_as = cross_compile + "as"
            if which(gnu_as):
                break

        if linux_version_code >= 515000:
            make_variables["LLVM_IAS"] = "1"
        else:
            make_variables["CROSS_COMPILE"] = cross_compile

        if not lib.check_binutils(cfg, "mips", cross_compile):
            return
        binutils_version, binutils_location = lib.get_binary_info(gnu_as)
        print(f"binutils version: {binutils_version}")
        print(f"binutils location: {binutils_location}")

        # https://git.kernel.org/mips/c/c47c7ab9b53635860c6b48736efdd22822d726d7
        config_str = ""
        sc_args = []
        with open(linux_folder.joinpath("arch", "mips", "configs", "malta_defconfig")) as f:
            if not search("CONFIG_BLK_DEV_INITRD=y", f.read()):
                config_str = " + CONFIG_BLK_DEV_INITRD=y"
                sc_args += ["-e", "BLK_DEV_INITRD"]

        # https://github.com/ClangBuiltLinux/linux/issues/1025
        ld_bfd = {}
        has_e91946d6d93ef = linux_folder.joinpath("arch", "mips", "vdso", "Kconfig").exists()
        if has_e91946d6d93ef: # and llvm_version_code < 1300000:
            cross_compile = "mipsel-linux-gnu-"
            ld_bfd = {"LD": f"{cross_compile}ld"}

        log_str = "mips malta_defconfig"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": lib.log_file_from_str(log_folder, log_str),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": make_variables,
        }
        lib.kmake(kmake_cfg)
        if sc_args:
            lib.scripts_config(linux_folder, build_folder, sc_args)
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, f"{log_str}{config_str}", rc == 0, time)
        boot_qemu(cfg, f"{log_str}{config_str}", build_folder, rc == 0)

        log_str = "mips malta_defconfig + CONFIG_RANDOMIZE_BASE=y"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": log_folder.joinpath("mips-malta_defconfig-kaslr.log"),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": make_variables,
        }
        lib.kmake(kmake_cfg)
        kaslr_sc_args = ["-e", "RELOCATABLE"]
        kaslr_sc_args += ["--set-val", "RELOCATION_TABLE_SIZE", "0x00200000"]
        kaslr_sc_args += ["-e", "RANDOMIZE_BASE"]
        lib.scripts_config(linux_folder, build_folder, sc_args + kaslr_sc_args)
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, f"{log_str}{config_str}", rc == 0, time)
        boot_qemu(cfg, f"{log_str}{config_str}", build_folder, rc == 0)

        log_str = "mips malta_defconfig + CONFIG_CPU_BIG_ENDIAN=y"
        kmake_cfg = {
            "linux_folder": linux_folder,
            "build_folder": build_folder,
            "log_file": log_folder.joinpath("mips-malta_defconfig-big-endian.log"),
            "targets": ["distclean", log_str.split(" ")[1]],
            "variables": {**make_variables, **ld_bfd},
        }
        lib.kmake(kmake_cfg)
        lib.modify_config(linux_folder, build_folder, "big endian")
        if sc_args:
            lib.scripts_config(linux_folder, build_folder, sc_args)
        kmake_cfg["targets"] = ["olddefconfig", "all"]
        rc, time = lib.kmake(kmake_cfg)
        lib.log_result(cfg, f"{log_str}{config_str}", rc == 0, time)
        boot_qemu(cfg, f"{log_str}{config_str}", build_folder, rc == 0, "mips")

        generic_cfgs = ["32r1", "32r1el", "32r2", "32r2el"]
        if llvm_version_code >= 1200000:
            generic_cfgs += ["32r6", "32r6el"]
        for generic_cfg in generic_cfgs:
            log_str = f"mips {generic_cfg}_defconfig"
            generic_make_variables = {}
            if "32r1" in generic_cfg:
                generic_make_variables["CROSS_COMPILE"] = cross_compile
                generic_make_variables["LLVM_IAS"] = "0"
            if not "el" in generic_cfg:
                generic_make_variables.update(ld_bfd)
            kmake_cfg = {
                "linux_folder": linux_folder,
                "build_folder": build_folder,
                "log_file": lib.log_file_from_str(log_folder, log_str),
                "targets": ["distclean", log_str.split(" ")[1], "all"],
                "variables": {**make_variables, **generic_make_variables},
            }
            rc, time = lib.kmake(kmake_cfg)
            lib.log_result(cfg, log_str, rc == 0, time)

        if defconfigs_only:
            if not save_objects:
                rmtree(build_folder)
            return

        for other_cfg in ["allnoconfig", "tinyconfig"]:
            log_str = f"mips {other_cfg}"
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
        return lib.clang_supports_target("mips-linux-gnu")
