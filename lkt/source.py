#!/usr/bin/env python3

from pathlib import Path
import re
from typing import Optional

import lkt.utils
from lkt.version import LinuxVersion, MinToolVersion


class LinuxSourceManager:
    def __init__(self, linux_source: Optional[Path] = None) -> None:
        self.folder: Path = linux_source if linux_source else lkt.utils.DEFAULT_PATH
        if not lkt.utils.path_is_set(self.folder):
            return

        # Perform same check as Linux for clean source tree to catch early failures
        if (
            Path(self.folder, '.config').is_file()
            or Path(self.folder, 'include/config').is_dir()
            or list(self.folder.glob('arch/*/include/generated'))
        ):
            raise RuntimeError(f"Supplied Linux source ('{self.folder}') is not clean!")

        self.commits: list[str] = []
        self.configs: list[str] = []

        self.version: LinuxVersion = LinuxVersion(folder=self.folder)

        self._cfi_y_config: str = ''

        # bcachefs: Initial commit
        # v6.6-rc1-17-g1c6fdbd8f246 (Sun Oct 22 17:08:07 2023 -0400)
        # https://git.kernel.org/linus/1c6fdbd8f2465ddfb73a01ec620cbf3d14044e1a
        self._add_config('CONFIG_BCACHEFS_FS', 'fs/bcachefs/Kconfig')

        # drm: Add CONFIG_DRM_WERROR
        # v6.8-rc6-1133-gf89632a9e5fa (Tue Mar 5 18:19:54 2024 +0200)
        # https://git.kernel.org/linus/f89632a9e5fa6c4787c14458cd42a9ef42025434
        self._add_config('CONFIG_DRM_WERROR', 'drivers/gpu/drm/Kconfig')

        # futex: Remove futex_cmpxchg detection
        # v5.16-rc1-3-g3297481d688a (Thu Nov 25 00:02:28 2021 +0100)
        # https://git.kernel.org/linus/3297481d688a5cc2973ea58bd78e66b8639748b1
        self._add_config('CONFIG_HAVE_FUTEX_CMPXCHG', 'init/Kconfig')

        # kbuild: link symbol CRCs at final link, removing CONFIG_MODULE_REL_CRCS
        # v5.18-rc1-54-g7b4537199a4a (Tue May 24 16:33:20 2022 +0900)
        # https://git.kernel.org/linus/7b4537199a4a8480b8c3ba37a2d44765ce76cd9b
        self._add_config('CONFIG_MODULE_REL_CRCS', 'init/Kconfig')

        # powerpc/64: Option to build big-endian with ELFv2 ABI
        # v6.1-rc2-115-g5017b4594672 (Fri Dec 2 17:54:07 2022 +1100)
        # https://git.kernel.org/linus/5017b45946722bdd20ac255c9ae7273b78d1f12e
        self._add_config('CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2', 'arch/powerpc/Kconfig')

        # bpf: Add kernel module with user mode driver that populates bpffs.
        # v5.9-rc1-124-gd71fa5c9763c (Thu Aug 20 16:02:36 2020 +0200)
        # https://git.kernel.org/linus/d71fa5c9763c24dd997a2fa4feb7a13a95bab42c
        if Path(self.folder, 'kernel/bpf/preload/Kconfig').exists():
            self.configs.append('CONFIG_BPF_PRELOAD')

        # powerpc/pmac32: enable serial options by default in defconfig
        # v6.5-rc3-36-g0b5e06e9cb15 (Mon Aug 14 21:54:04 2023 +1000)
        # https://git.kernel.org/linus/0b5e06e9cb156e7e97bfb4e1ebf6acd62497eaf5
        self._add_commit(
            '0b5e06e9cb156',
            'CONFIG_SERIAL_PMACZILOG_CONSOLE=y',
            'arch/powerpc/configs/pmac32_defconfig',
        )

        # arm64: Restrict CPU_BIG_ENDIAN to GNU as or LLVM IAS 15.x or newer
        # v6.6-rc3-8-g146a15b87335 (Thu Oct 26 16:33:20 2023 +0100)
        # https://git.kernel.org/linus/146a15b873353f8ac28dc281c139ff611a3c4848
        self._add_commit(
            '146a15b873353',
            'https://github.com/llvm/llvm-project/commit/1379b150991f70a5782e9a143c2ba5308da1161c',
            'arch/arm64/Kconfig',
        )

        # powerpc/44x: Fix build failure with GCC 12 (unrecognized opcode: `wrteei')
        # v5.19-rc2-164-g2255411d1d0f (Wed Jul 27 21:36:06 2022 +1000)
        # https://git.kernel.org/linus/2255411d1d0f0661d1e5acd5f6edf4e6652a345a
        self._add_commit(
            '2255411d1d0f0',
            'config POWERPC_CPU\n\tbool "Generic 32 bits powerpc"\n\tdepends on PPC_BOOK3S_32',
            'arch/powerpc/platforms/Kconfig.cputype',
        )

        # LoongArch: Allow building with kcov coverage
        # v6.5-114-g2363088eba2e (Wed Sep 6 22:53:55 2023 +0800)
        # https://git.kernel.org/linus/2363088eba2ecccfb643725e4864af73c4226a04
        self._add_commit('2363088eba2ec', 'select ARCH_HAS_KCOV', 'arch/loongarch/Kconfig')

        # lib/xor: make xor prototypes more friendly to compiler vectorization
        # v5.17-rc1-61-g297565aa22cf (Fri Feb 11 20:39:39 2022 +1100)
        # https://git.kernel.org/linus/297565aa22cfa80ab0f88c3569693aea0b6afb6d
        if Path(self.folder, 'lib/raid/xor/powerpc/xor_vmx.c').exists():
            self.commits.append('297565aa22cfa')
        else:
            self._add_commit('297565aa22cfa', '__restrict', 'arch/powerpc/lib/xor_vmx.c')

        # Makefile: Add loongarch target flag for Clang compilation
        # v6.4-21-g65eea6b44a5d (Thu Jun 29 20:58:43 2023 +0800)
        # https://git.kernel.org/linus/65eea6b44a5dd332c50390fdaeda7e197802c484
        self._add_commit('65eea6b44a5dd', 'loongarch64-linux-gnusf', 'scripts/Makefile.clang')

        # s390: always build relocatable kernel
        # v6.1-rc2-13-g80ddf5ce1c92 (Tue Nov 8 19:32:32 2022 +0100)
        # https://git.kernel.org/linus/80ddf5ce1c9291cb175d52ed1227134ad48c47ee
        self._add_commit('80ddf5ce1c929', 'config RELOCATABLE\n\tdef_bool y', 'arch/s390/Kconfig')

        # RDMA/cma: Distinguish between sockaddr_in and sockaddr_in6 by size
        # v6.2-rc3-52-g876e480da2f7 (Thu Feb 16 11:20:20 2023 -0400)
        # https://git.kernel.org/linus/876e480da2f74715fc70e37723e77ca16a631e35
        self._add_commit(
            '876e480da2f74',
            r"__builtin_object_size\(sa, 0\) >= sizeof\(struct sockaddr_in",
            'drivers/infiniband/core/cma.c',
        )

        # cfi: Switch to -fsanitize=kcfi
        # v6.0-rc4-5-g89245600941e (Mon Sep 26 10:13:13 2022 -0700)
        # https://git.kernel.org/linus/89245600941e4e0f87d77f60ee269b5e61ef4e49
        self._add_commit('89245600941e4', '-fsanitize=kcfi', 'Makefile')

        # RDMA/core: Add a netevent notifier to cma
        # v5.19-rc1-4-g925d046e7e52 (Thu Jun 16 09:54:42 2022 +0300)
        # https://git.kernel.org/linus/925d046e7e52c71c3531199ce137e141807ef740
        self._add_commit(
            '925d046e7e52', 'static void cma_netevent_work_handler', 'drivers/infiniband/core/cma.c'
        )

        # ARM: 9122/1: select HAVE_FUTEX_CMPXCHG
        # v5.15-rc1-1-g9d417cbe36ee (Tue Oct 19 10:37:34 2021 +0100)
        # https://git.kernel.org/linus/9d417cbe36eee7afdd85c2e871685f8dab7c2dba
        self._add_commit('9d417cbe36eee', 'select HAVE_FUTEX_CMPXCHG if FUTEX', 'arch/arm/Kconfig')

        # x86/Kconfig: Do not allow CONFIG_X86_X32_ABI=y with llvm-objcopy
        # v5.17-rc8-55-gaaeed6ecc125 (Tue Mar 15 10:32:48 2022 +0100)
        # https://git.kernel.org/linus/aaeed6ecc1253ce1463fa1aca0b70a4ccbc9fa75
        self._add_commit(
            'aaeed6ecc1253',
            'https://github.com/ClangBuiltLinux/linux/issues/514',
            'arch/x86/Kconfig',
        )

        # MIPS: Malta: Enable BLK_DEV_INITRD
        # v5.17-rc3-5-gc47c7ab9b536 (Wed Feb 9 13:57:50 2022 +0100)
        # https://git.kernel.org/linus/c47c7ab9b53635860c6b48736efdd22822d726d7
        self._add_commit(
            'c47c7ab9b5363', 'CONFIG_BLK_DEV_INITRD=y', 'arch/mips/configs/malta_defconfig'
        )

        # bpf: Drop libbpf, libelf, libz dependency from bpf preload.
        # v5.16-11580-ge96f2d64c812 (Tue Feb 1 23:56:18 2022 +0100)
        # https://git.kernel.org/linus/e96f2d64c812d9c20adea38a9b5e08feaa21fcf5
        if (
            preload_make := Path(self.folder, 'kernel/bpf/preload/Makefile')
        ).exists() and 'LIBBPF_OUT' not in preload_make.read_text(encoding='utf-8'):
            self.commits.append('e96f2d64c812d')

        # riscv: set default pm_power_off to NULL
        # v5.15-rc1-6-gf2928e224d85 (Mon Oct 4 14:16:57 2021 -0700)
        # https://git.kernel.org/linus/f2928e224d85e7cc139009ab17cefdfec2df5d11
        self._add_commit(
            'f2928e224d85e', r"void \(\*pm_power_off\)\(void\) = NULL;", 'arch/riscv/kernel/reset.c'
        )

        # hexagon: export raw I/O routines for modules
        # v5.16-rc1-318-gffb92ce826fd (Sat Nov 20 10:35:54 2021 -0800)
        # https://git.kernel.org/linus/ffb92ce826fd801acb0f4e15b75e4ddf0d189bde
        self._add_commit('ffb92ce826fd8', r"EXPORT_SYMBOL\(__raw_readsw\)", 'arch/hexagon/lib/io.c')

    def _add_commit(self, commit: str, regex: str, file_path: Path | str) -> None:
        if not (file := Path(self.folder, file_path)).exists():
            return
        file_text = file.read_text(encoding='utf-8')
        if re.search(regex, file_text):
            self.commits.append(commit)

    def _add_config(self, config: str, file_path: Path | str) -> None:
        if not (file := Path(self.folder, file_path)).exists():
            return
        definition = config.replace('CONFIG_', 'config ')
        file_text = file.read_text(encoding='utf-8')
        if definition in file_text:
            self.configs.append(config)

    def arch_supports_kcfi(self, srcarch: str) -> bool:
        arch_kconfig_txt = Path(self.folder, 'arch', srcarch, 'Kconfig').read_text(encoding='utf-8')
        return 'select ARCH_SUPPORTS_CFI' in arch_kconfig_txt

    # kcfi: Rename CONFIG_CFI_CLANG to CONFIG_CFI
    # v6.17-rc2-7-g23ef9d439769 (Wed Sep 24 14:29:14 2025 -0700)
    # https://git.kernel.org/linus/23ef9d439769d5f35353650e771c63d13824235b
    def get_cfi_y_config(self) -> str:
        if not self._cfi_y_config:
            arch_kconfig_txt = Path(self.folder, 'arch/Kconfig').read_text(encoding='utf-8')
            if match := re.search(r"config (CFI(?:_CLANG)?)$", arch_kconfig_txt, flags=re.M):
                self._cfi_y_config = f"CONFIG_{match.groups()[0]}=y"
            else:
                self._cfi_y_config = 'CONFIG_CFI_CLANG=y'
        return self._cfi_y_config

    def get_min_llvm_ver(self, arch=None) -> MinToolVersion:
        return MinToolVersion(folder=self.folder, arch=arch, tool='llvm')
