#!/usr/bin/env python3

from copy import deepcopy
from pathlib import Path
from re import escape, search
from shutil import rmtree

import lib

def build_defconfigs(self, cfg):
    log_str = "hexagon defconfig"
    kmake_cfg = {
        "linux_folder": self.linux_folder,
        "build_folder": self.build_folder,
        "log_file": lib.log_file_from_str(self.log_folder, log_str),
        "targets": ["distclean", log_str.split(" ")[1], "all"],
        "variables": self.make_variables,
    }
    rc, time = lib.kmake(kmake_cfg)
    lib.log_result(cfg, log_str, rc == 0, time)

def build_otherconfigs(self, cfg):
    if has_ffb92ce826fd8(self.linux_folder):
        log_str = "hexagon allmodconfig"
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
        lib.log_result(cfg, f"{log_str}{config_str}", rc == 0, time)
        if config_path:
            Path(config_path).unlink()
            del self.make_variables["KCONFIG_ALLCONFIG"]

def has_ffb92ce826fd8(linux_folder):
    with open(linux_folder.joinpath("arch", "hexagon", "lib", "io.c")) as f:
        return search(escape("EXPORT_SYMBOL(__raw_readsw)"), f.read())

class HEXAGON:
    def __init__(self, cfg):
        self.build_folder = cfg["build_folder"].joinpath("hexagon")
        self.commits_present = cfg["commits_present"]
        self.configs_present = cfg["configs_present"]
        self.linux_folder = cfg["linux_folder"]
        self.log_folder = cfg["log_folder"]
        self.make_variables = deepcopy(cfg["make_variables"])
        self.save_objects = cfg["save_objects"]
        self.targets_to_build = cfg["targets_to_build"]

    def build(self, cfg):
        self.make_variables["ARCH"] = "hexagon"
        self.make_variables["LLVM_IAS"] = "1"
        if not "6f5b41a2f5a63" in self.commits_present:
            self.make_variables["CROSS_COMPILE"] = "hexagon-linux-musl-"

        with open(self.linux_folder.joinpath("arch", "hexagon", "Makefile")) as f:
            has_788dcee0306e1 = search(escape("KBUILD_CFLAGS += -mlong-calls"), f.read())
            has_f1f99adf05f21 = self.linux_folder.joinpath("arch", "hexagon", "lib", "divsi3.S").exists()
            if not (has_788dcee0306e1 and has_f1f99adf05f21):
                lib.header("Skipping hexagon kernels")
                print("Hexagon needs the following fixes from Linux 5.13 to build properly:\n")
                print("  * https://git.kernel.org/linus/788dcee0306e1bdbae1a76d1b3478bb899c5838e")
                print("  * https://git.kernel.org/linus/6fff7410f6befe5744d54f0418d65a6322998c09")
                print("  * https://git.kernel.org/linus/f1f99adf05f2138ff2646d756d4674e302e8d02d")
                print("\nProvide a kernel tree with Linux 5.13+ or one with these fixes to build Hexagon kernels.")
                lib.log(cfg, "hexagon kernels skipped due to missing 788dcee0306e, 6fff7410f6be, and/or f1f99adf05f2")
                return

        lib.header("Building hexagon kernels", end='')

        if "defconfigs" in self.targets_to_build:
            build_defconfigs(self, cfg)
        if "otherconfigs" in self.targets_to_build:
            build_otherconfigs(self, cfg)

        if not self.save_objects:
            rmtree(self.build_folder)

    def clang_supports_target(self):
        return lib.clang_supports_target("hexagon-linux-musl")