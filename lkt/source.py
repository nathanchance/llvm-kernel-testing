#!/usr/bin/env python3

from pathlib import Path
import re

import lkt.utils


class LinuxSourceManager:

    def __init__(self, linux_source):
        # Perform same check as Linux for clean source tree to catch early failures
        if (Path(linux_source, '.config').is_file()
                or Path(linux_source, 'include/config').is_dir()
                or list(linux_source.glob('arch/*/include/generated'))):
            raise RuntimeError(f"Supplied Linux source ('{linux_source}') is not clean!")

        self.commits = []
        self.configs = []
        self.folder = linux_source

        output = lkt.utils.chronic(['make', '-C', self.folder, '-s',
                                    'kernelversion']).stdout.strip()
        self.version = tuple(int(item) for item in output.split('-', 1)[0].split('.'))

        # Introduced by: add support for Clang CFI
        # Link: https://git.kernel.org/linus/cf68fffb66d60d96209446bfc4a15291dc5a5d41
        # First appeared: v5.13-rc1~145^2~17
        self._add_config('CONFIG_CFI_CLANG', 'arch/Kconfig')

        # Removed by: futex: Remove futex_cmpxchg detection
        # Link: https://git.kernel.org/linus/3297481d688a5cc2973ea58bd78e66b8639748b1
        # Removed in: v5.17-rc1~120^2~18
        self._add_config('CONFIG_HAVE_FUTEX_CMPXCHG', 'init/Kconfig')

        # Introduced by: kbuild: add support for Clang LTO
        # Link: https://git.kernel.org/linus/dc5723b02e523b2c4a68667f7e28c65018f7202f
        # First appeared: v5.12-rc1-dontuse~70^2~15
        self._add_config('CONFIG_LTO_CLANG_THIN', 'arch/Kconfig')

        # Removed by: kbuild: link symbol CRCs at final link, removing CONFIG_MODULE_REL_CRCS
        # Link: https://git.kernel.org/linus/7b4537199a4a8480b8c3ba37a2d44765ce76cd9b
        # Removed in: v5.19-rc1~139^2~2
        self._add_config('CONFIG_MODULE_REL_CRCS', 'init/Kconfig')

        # Introduced by: powerpc/64: Option to build big-endian with ELFv2 ABI
        # Link: https://git.kernel.org/linus/5017b45946722bdd20ac255c9ae7273b78d1f12e
        # First appeared: v6.2-rc1~52^2~57
        self._add_config('CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2', 'arch/powerpc/Kconfig')

        # Introduced by: scs: Add support for Clang's Shadow Call Stack (SCS)
        # Link: https://git.kernel.org/linus/d08b9f0ca6605e13dcb48f04e55a30545b3c71eb
        # First appeared: v5.8-rc1~213^2^2~18
        self._add_config('CONFIG_SHADOW_CALL_STACK', 'arch/Kconfig')

        # Introduced by: Enable '-Werror' by default for all kernel builds
        # Link: https://git.kernel.org/linus/3fe617ccafd6f5bb33c2391d6f4eeb41c1fd0151
        # First appeared: v5.15-rc1~89
        self._add_config('CONFIG_WERROR', 'init/Kconfig')

        # Introduced by: bpf: Add kernel module with user mode driver that populates bpffs.
        # Link: https://git.kernel.org/linus/d71fa5c9763c24dd997a2fa4feb7a13a95bab42c
        # First appeared: v5.10-rc1~107^2~394^2~78^2~1
        if Path(self.folder, 'kernel/bpf/preload/Kconfig').exists():
            self.configs.append('CONFIG_BPF_PRELOAD')

        # Commit: Makefile: move initial clang flag handling into scripts/Makefile.clang
        # Link: https://git.kernel.org/linus/6f5b41a2f5a6314614e286274eb8e985248aac60
        # First appeared: v5.15-rc1~98^2~34
        if Path(self.folder, 'scripts/Makefile.clang').exists():
            self.commits.append('6f5b41a2f5a63')

        # Commit: MIPS: VDSO: Move disabling the VDSO logic to Kconfig
        # Link: https://git.kernel.org/linus/e91946d6d93ef6167bd3b1456f163d1585095ea1
        # First appeared: v5.8-rc1~173^2~72
        if Path(self.folder, 'arch/mips/vdso/Kconfig').exists():
            self.commits.append('e91946d6d93ef')

        # Commit: Hexagon: add target builtins to kernel
        # Link: https://git.kernel.org/linus/f1f99adf05f2138ff2646d756d4674e302e8d02d
        # First appeared: v5.13-rc1~37^2
        if Path(self.folder, 'arch/hexagon/lib/divsi3.S').exists():
            self.commits.append('f1f99adf05f21')

        # Commit: powerpc: Add "-z notext" flag to disable diagnostic
        # Link: https://git.kernel.org/linus/0355785313e2191be4e1108cdbda94ddb0238c48
        # First appeared: v5.15-rc1~100^2~70
        self._add_commit('0355785313e21', r"LDFLAGS_vmlinux-\$\(CONFIG_RELOCATABLE\) \+= -z notext",
                         'arch/powerpc/Makefile')

        # Introduced by: powerpc/pmac32: enable serial options by default in defconfig
        # Link: https://git.kernel.org/linus/0b5e06e9cb156e7e97bfb4e1ebf6acd62497eaf5
        # First appeared: next-20230815~142^2~5
        self._add_commit('0b5e06e9cb156', 'CONFIG_SERIAL_PMACZILOG_CONSOLE=y',
                         'arch/powerpc/configs/pmac32_defconfig')

        # Introduced by: powerpc/64: Make VDSO32 track COMPAT on 64-bit
        # Link: https://git.kernel.org/linus/231b232df8f67e7d37af01259c21f2a131c3911e
        # First appeared: v5.10-rc1~105^2~141
        self._add_commit('231b232df8f67',
                         'config VDSO32\n\tdef_bool y\n\tdepends on PPC32 || COMPAT',
                         'arch/powerpc/platforms/Kconfig.cputype')

        # Commit: powerpc/44x: Fix build failure with GCC 12 (unrecognized opcode: `wrteei')
        # Link: https://git.kernel.org/linus/2255411d1d0f0661d1e5acd5f6edf4e6652a345a
        # First appeared: v6.0-rc1~83^2~41
        self._add_commit(
            '2255411d1d0f0',
            'config POWERPC_CPU\n\tbool "Generic 32 bits powerpc"\n\tdepends on PPC_BOOK3S_32',
            'arch/powerpc/platforms/Kconfig.cputype')

        # Commit: lib/xor: make xor prototypes more friendly to compiler vectorization
        # Link: https://git.kernel.org/linus/297565aa22cfa80ab0f88c3569693aea0b6afb6d
        # First appeared: v5.18-rc1~199^2~76
        self._add_commit('297565aa22cfa', '__restrict', 'arch/powerpc/lib/xor_vmx.c')

        # Commit: powerpc/irq: Inline call_do_irq() and call_do_softirq()
        # Link: https://git.kernel.org/linus/48cf12d88969bd4238b8769767eb476970319d93
        # First appeared: v5.13-rc1~90^2~191
        self._add_commit('48cf12d88969b',
                         r"static __always_inline void call_do_softirq\(const void \*sp\)",
                         'arch/powerpc/kernel/irq.c')

        # Commit: KVM: PPC: Book3S HV: Workaround high stack usage with clang
        # Link: https://git.kernel.org/linus/51696f39cbee5bb684e7959c0c98b5f54548aa34
        # First appeared: v5.14-rc1~104^2~71^2
        self._add_commit('51696f39cbee5', 'noinline_for_stack void byteswap_pt_regs',
                         'arch/powerpc/kvm/book3s_hv_nested.c')

        # Commit: x86, lto: Enable Clang LTO for 32-bit as well
        # Link: https://git.kernel.org/linus/583bfd484bcc85e9371e7205fa9e827c18ae34fb
        # First appeared: v5.14-rc1~126^2~4
        self._add_commit('583bfd484bcc8', 'select ARCH_SUPPORTS_LTO_CLANG_THIN\n',
                         'arch/x86/Kconfig')

        # Introduced by: powerpc: Kconfig: disable CONFIG_COMPAT for clang < 12
        # Link: https://git.kernel.org/linus/6fcb574125e673f33ff058caa54b4e65629f3a08
        # First appeared: v5.14-rc1~104^2~195
        self._add_commit(
            '6fcb574125e67',
            'config COMPAT\n\tbool "[a-zA-Z0-9 ]+"\n\tdepends on PPC64\n\tdepends on !CC_IS_CLANG',
            'arch/powerpc/Kconfig')

        # Commit: Hexagon: fix build errors
        # Link: https://git.kernel.org/linus/788dcee0306e1bdbae1a76d1b3478bb899c5838e
        # First appeared: v5.13-rc1~37^2~3
        self._add_commit('788dcee0306e1', r"KBUILD_CFLAGS \+= -mlong-calls",
                         'arch/hexagon/Makefile')

        # Commit: Makefile: Add loongarch target flag for Clang compilation
        # Link: https://git.kernel.org/linus/65eea6b44a5dd332c50390fdaeda7e197802c484
        # First appeared: v6.5-rc1
        if '6f5b41a2f5a63' in self.commits:
            self._add_commit('65eea6b44a5dd', 'loongarch64-linux-gnusf', 'scripts/Makefile.clang')

        # Commit: s390: always build relocatable kernel
        # Link: https://git.kernel.org/linus/80ddf5ce1c9291cb175d52ed1227134ad48c47ee
        # First appeared: v6.1-rc5~10^2~1
        self._add_commit('80ddf5ce1c929', 'config RELOCATABLE\n\tdef_bool y', 'arch/s390/Kconfig')

        # Commit: RDMA/cma: Distinguish between sockaddr_in and sockaddr_in6 by size
        # Link: https://git.kernel.org/linus/876e480da2f74715fc70e37723e77ca16a631e35
        # First appeared: v6.3-rc1~102^2~8
        self._add_commit('876e480da2f74',
                         r"__builtin_object_size\(sa, 0\) >= sizeof\(struct sockaddr_in",
                         'drivers/infiniband/core/cma.c')

        # Commit: cfi: Switch to -fsanitize=kcfi
        # Link: https://git.kernel.org/linus/89245600941e4e0f87d77f60ee269b5e61ef4e49
        # First appeared: v6.1-rc1~201^2~17
        self._add_commit('89245600941e4', '-fsanitize=kcfi', 'Makefile')

        # Commit: RDMA/core: Add a netevent notifier to cma
        # Link: https://git.kernel.org/linus/925d046e7e52c71c3531199ce137e141807ef740
        # First appeared: v6.0-rc1~113^2~84
        self._add_commit('925d046e7e52', 'static void cma_netevent_work_handler',
                         'drivers/infiniband/core/cma.c')

        # Introduced by: powerpc/pmac/smp: Avoid unused-variable warnings
        # Link: https://git.kernel.org/linus/9451c79bc39e610882bdd12370f01af5004a3c4f
        # First appeared: v5.7-rc1~81^2~107
        smp_c_txt = Path(self.folder,
                         'arch/powerpc/platforms/powermac/smp.c').read_text(encoding='utf-8')
        if not re.search('^volatile static long int core99_l2_cache;$', smp_c_txt, flags=re.M):
            self.commits.append('9451c79bc39e')

        # Commit: ARM: 9122/1: select HAVE_FUTEX_CMPXCHG
        # Link: https://git.kernel.org/linus/9d417cbe36eee7afdd85c2e871685f8dab7c2dba
        # First appeared: v5.15-rc7~3^2~8
        self._add_commit('9d417cbe36eee', 'select HAVE_FUTEX_CMPXCHG if FUTEX', 'arch/arm/Kconfig')

        # Introduced by: powerpc: Allow CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2 with ld.lld 15+
        # Link: https://git.kernel.org/linus/a11334d8327b3fd7987cbfb38e956a44c722d88f
        # First appeared: v6.4-rc1
        if 'CONFIG_PPC64_BIG_ENDIAN_ELF_ABI_V2' in self.configs:
            self._add_commit(
                'a11334d8327b',
                r'depends on CC_HAS_ELFV2\n\tdepends on LD_VERSION >= 22400 \|\| LLD_VERSION >= 150000',
                'arch/powerpc/Kconfig')

        # Commit: x86/Kconfig: Do not allow CONFIG_X86_X32_ABI=y with llvm-objcopy
        # Link: https://git.kernel.org/linus/aaeed6ecc1253ce1463fa1aca0b70a4ccbc9fa75
        # First appeared: v5.18-rc1~94^2~7
        self._add_commit('aaeed6ecc1253', 'https://github.com/ClangBuiltLinux/linux/issues/514',
                         'arch/x86/Kconfig')

        # Commit: x86/build: Treat R_386_PLT32 relocation as R_386_PC32
        # Link: https://git.kernel.org/linus/bb73d07148c405c293e576b40af37737faf23a6a
        # First appeared: v5.12-rc1-dontuse~180^2
        self._add_commit('bb73d07148c40', 'R_386_PLT32:', 'arch/x86/tools/relocs.c')

        # Commit: MIPS: Malta: Enable BLK_DEV_INITRD
        # Link: https://git.kernel.org/linus/c47c7ab9b53635860c6b48736efdd22822d726d7
        # First appeared: v5.18-rc1~125^2~26
        self._add_commit('c47c7ab9b5363', 'CONFIG_BLK_DEV_INITRD=y',
                         'arch/mips/configs/malta_defconfig')

        # Commit: x86/boot: Add $(CLANG_FLAGS) to compressed KBUILD_CFLAGS
        # Link: https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f
        # First appeared: v5.13-rc1~190^2~2
        self._add_commit('d5cbd80e302df', 'CLANG_FLAGS', 'arch/x86/boot/compressed/Makefile')

        # Commit: arm64: Kconfig: add a choice for endianness
        # Link: https://git.kernel.org/linus/d8e85e144bbe12e8d82c6b05d690a34da62cc991
        # First appeared: v5.5-rc1~189^2
        self._add_commit('d8e85e144bbe1', 'prompt "Endianness"', 'arch/arm64/Kconfig')

        # Commit: riscv: Use -mno-relax when using lld linker
        # Link: https://git.kernel.org/linus/ec3a5cb61146c91f0f7dcec8b7e7157a4879a9ee
        # First appeared: v5.13-rc5~8^2~3
        self._add_commit('ec3a5cb61146c', r"KBUILD_CFLAGS \+= -mno-relax", 'arch/riscv/Makefile')

        # Commit: riscv: set default pm_power_off to NULL
        # Link: https://git.kernel.org/linus/f2928e224d85e7cc139009ab17cefdfec2df5d11
        # First appeared: v5.16-rc1~32^2~13
        self._add_commit('f2928e224d85e', r"void \(\*pm_power_off\)\(void\) = NULL;",
                         'arch/riscv/kernel/reset.c')

        # Commit: hexagon: export raw I/O routines for modules
        # Link: https://git.kernel.org/linus/ffb92ce826fd801acb0f4e15b75e4ddf0d189bde
        # First appeared: v5.16-rc2~5^2~10
        self._add_commit('ffb92ce826fd8', r"EXPORT_SYMBOL\(__raw_readsw\)", 'arch/hexagon/lib/io.c')

        # Commit: s390/bitops: remove small optimization to fix clang build
        # Link: https://git.kernel.org/linus/efe5e0fea4b24872736c62a0bcfc3f99bebd2005
        # First appeared: v5.12-rc1-dontuse~138^2~63
        text = Path(self.folder, 'arch/s390/include/asm/bitops.h').read_text(encoding='utf-8')
        if not re.search('"(o|n|x)i\t%0,%b1\\\\n"', text):
            self.commits.append('efe5e0fea4b24')

    def _add_commit(self, commit, regex, file):
        file_text = Path(self.folder, file).read_text(encoding='utf-8')
        if re.search(regex, file_text):
            self.commits.append(commit)

    def _add_config(self, config, file):
        definition = config.replace('CONFIG_', 'config ')
        file_text = Path(self.folder, file).read_text(encoding='utf-8')
        if definition in file_text:
            self.configs.append(config)
