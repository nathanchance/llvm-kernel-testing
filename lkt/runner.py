#!/usr/bin/env python3

import contextlib
import os
from pathlib import Path
import platform
import re
import shutil
from subprocess import PIPE, STDOUT, Popen
import sys
import tempfile
import time
from typing import TypedDict

import lkt.utils
from lkt.source import LinuxSourceManager
from lkt.version import ClangVersion

HAVE_DEV_KVM_ACCESS = os.access('/dev/kvm', os.R_OK | os.W_OK)
KNOWN_SUBSYS_WERROR_CONFIGS = ('DRM_WERROR',)


class MakeVars(TypedDict, total=False):
    ARCH: str
    CC: str
    CROSS_COMPILE: str
    LLVM: str
    LLVM_IAS: str
    LD: str
    LOCALVERSION: str
    HOSTCC: str
    HOSTLDFLAGS: str
    KBZIP2: str
    KGZIP: str
    OBJCOPY: str
    OBJDUMP: str
    O: Path  # noqa: E741


class Folders:
    def __init__(self) -> None:
        self.boot_utils: Path = lkt.utils.DEFAULT_PATH
        self.build: Path = lkt.utils.DEFAULT_PATH
        self.configs: Path = lkt.utils.DEFAULT_PATH
        self.log: Path = lkt.utils.DEFAULT_PATH
        self.source: Path = lkt.utils.DEFAULT_PATH


class Result:
    def __init__(self) -> None:
        self.boot: str = ''
        self.build: str = ''
        self.duration: str = ''
        self.log: Path = lkt.utils.DEFAULT_PATH
        self.name: str = ''
        self.reason: str = ''


class LLVMKernelRunner:
    def __init__(self) -> None:
        self.bootable: bool = False
        self.boot_arch: str = ''
        self.configs: list[lkt.utils.PathString] = []
        self.folders: Folders = Folders()
        self.lsm: LinuxSourceManager = LinuxSourceManager()
        self.image_target: str = ''
        self.make_args: list[lkt.utils.PathString] = [f"-skj{os.cpu_count()}"]
        self.make_targets: list[str] = []
        self.make_vars: MakeVars = {
            'HOSTLDFLAGS': '-fuse-ld=lld',
            'LLVM': '1',
            'LLVM_IAS': '1',
            'LOCALVERSION': '-cbl',
        }
        self.only_test_boot: bool = False
        self.override_make_vars: MakeVars = {}
        self.qemu_arch: str = ''
        self.result: Result = Result()

        self._config: Path = lkt.utils.DEFAULT_PATH

    def _boot_kernel(self) -> None:
        if not self.bootable:
            return
        if self.result.build == 'failed':
            self.result.boot = 'skipped'
            return
        if not self.boot_arch:
            raise RuntimeError('No boot-utils architecture set?')
        if not self.qemu_arch:
            raise RuntimeError('No QEMU architecture set?')
        if not shutil.which(qemu_bin := f"qemu-system-{self.qemu_arch}"):
            self.result.boot = f"skipped due to missing {qemu_bin}"
            return
        if not lkt.utils.path_is_set(self.folders.boot_utils):
            raise RuntimeError('No boot-utils folder set?')
        if not self.folders.boot_utils.exists():
            raise RuntimeError('boot-utils could not be found?')
        if not (boot_qemu := Path(self.folders.boot_utils, 'boot-qemu.py')).exists():
            raise RuntimeError('boot-qemu.py could not be found?')
        boot_utils_cmd: lkt.utils.CmdList = [
            boot_qemu,
            '-a',
            self.boot_arch,
            '-k',
            self.folders.build,
        ]
        if (boot_utils_json := Path(self.folders.log, '.boot-utils.json')).exists():
            boot_utils_cmd += ['--gh-json-file', boot_utils_json]
        # This hardcodes some internal boot-utils logic but that's fine since I
        # help maintain that tool :)
        using_kvm = False
        if (machine := platform.machine()) == 'aarch64':
            if self.boot_arch == 'arm32_v7':
                el1_32 = Path(boot_qemu.parent, 'utils/aarch64_32_bit_el1_supported')
                using_kvm = lkt.utils.run_check_rc_zero(el1_32) and HAVE_DEV_KVM_ACCESS
            else:
                using_kvm = self.boot_arch in ('arm64', 'arm64be') and HAVE_DEV_KVM_ACCESS
        elif machine == 'x86_64':
            using_kvm = self.boot_arch in ('x86', 'x86_64') and HAVE_DEV_KVM_ACCESS
        # i386 may not have highmem automatically enabled after
        # x86/mm: Remove CONFIG_HIGHMEM64G support
        # v6.14-rc3-38-gbbeb69ce3013 (Thu Feb 27 11:21:53 2025 +0100)
        # https://git.kernel.org/linus/bbeb69ce301323e84f1677484eb8e4cd8fb1f9f8
        # and it does not need this workaround because it can only have 8 CPUs.
        if using_kvm and self.boot_arch != 'x86':
            boot_utils_cmd += ['-m', '2G']
        lkt.utils.show_cmd(boot_utils_cmd)
        sys.stderr.flush()
        sys.stdout.flush()
        with self.result.log.open('a', encoding='utf-8') as file:
            proc = lkt.utils.run(
                boot_utils_cmd, check=False, errors='replace', stderr=STDOUT, stdout=PIPE
            )
            file.write(proc.stdout)
            if proc.returncode == 0:
                self.result.boot = 'successful'
            else:
                self.result.boot = 'failed'
                print(proc.stdout, end='')

    def _build_kernel(self) -> None:
        self.make_args += ['-C', self.folders.source]
        self.make_vars.update(self.override_make_vars)

        # Clean up build folder if it exists
        if self.folders.build.exists():
            shutil.rmtree(self.folders.build)

        # Adjust O relative to source folder if possible
        self.make_vars['O'] = self.folders.build
        with contextlib.suppress(ValueError):
            self.make_vars['O'] = self.folders.build.relative_to(self.folders.source)

        # Remove LLVM_IAS if the value is the default
        llvm_ias = self.make_vars['LLVM_IAS']
        makefile_clang = Path(self.folders.source, 'scripts/Makefile.clang')
        llvm_ias_def_on = (
            makefile_clang.exists()
            and 'ifeq ($(LLVM_IAS),0)' in makefile_clang.read_text(encoding='utf-8')
        )
        if (llvm_ias_def_on and llvm_ias == '1') or (not llvm_ias_def_on and llvm_ias == '0'):
            del self.make_vars['LLVM_IAS']

        base_make_cmd: lkt.utils.CmdList = [
            'make',
            *self.make_args,
            *[f"{var}={self.make_vars[var]}" for var in sorted(self.make_vars)],
        ]

        ##########################
        # configuration handling #
        ##########################
        base_config: lkt.utils.PathString = self.configs[0]
        requested_fragments: list[str] = []
        requested_options: list[str] = []
        for item in self.configs[1:]:
            if not isinstance(item, str):
                raise ValueError(f"{item} is not a string?")
            if item.endswith('.config'):
                requested_fragments.append(item)
            elif item.startswith('CONFIG_'):
                if '=' not in item:
                    raise ValueError(f"{item} does not contain '='?")
                requested_options.append(item)
            else:
                raise ValueError(f"Cannot handle {item}?")
        extra_configs = requested_options.copy()
        need_olddefconfig = False

        cmds_to_log: list[lkt.utils.ValidCmd] = []

        if isinstance(base_config, str):
            if extra_configs:
                # Generate .config for merge_config.sh
                make_cmd: lkt.utils.CmdList = [*base_make_cmd, base_config, *requested_fragments]
                cmds_to_log.append(make_cmd)
                lkt.utils.chronic(make_cmd, show_cmd=True)
            else:
                base_make_cmd += [base_config, *requested_fragments]
        elif isinstance(base_config, Path):
            if requested_fragments:
                raise RuntimeError(
                    'config fragments are not supported with out of tree configurations! Add support if this is needed.',
                )

            self.folders.build.mkdir(parents=True)

            copy_cmd: lkt.utils.CmdList = ['cp', base_config, self._config]
            lkt.utils.show_cmd(copy_cmd)
            cmds_to_log.append(copy_cmd)
            shutil.copy(base_config, self._config)
            extra_configs += self._distro_adjustments()

            need_olddefconfig = True

            # Nothing is explicitly wrong with this configuration option but it
            # changes the default image target, which boot-utils does not expect,
            # so explicitly add the bootable image target to the end of the command
            if base_config.stem in ('aarch64', 'arm64', 'riscv64') and lkt.utils.is_set(
                self.folders.source, base_config, 'EFI_ZBOOT'
            ):
                self.make_targets.append(self.image_target)

        if extra_configs:
            _, config_path = tempfile.mkstemp(dir=self.folders.build, text=True)

            # Certain configuration options are choices and Kconfig warns when
            # choices are overridden. Disable the default choice when a choice
            # is present.
            if 'CONFIG_LTO_CLANG_THIN=y' in extra_configs:
                extra_configs.append('CONFIG_LTO_NONE=n')
            if 'CONFIG_CPU_BIG_ENDIAN=y' in extra_configs:
                extra_configs.append('CONFIG_CPU_LITTLE_ENDIAN=n')
            if 'CONFIG_CPU_LITTLE_ENDIAN=y' in extra_configs:
                extra_configs.append('CONFIG_CPU_BIG_ENDIAN=n')

            extra_config_txt = ''.join(f"{config}\n" for config in extra_configs)
            cmds_to_log.append(f"cat {config_path}\n{extra_config_txt.strip()}")
            Path(config_path).write_text(extra_config_txt, encoding='utf-8')

            merge_config: lkt.utils.CmdList = [
                Path(self.folders.source, 'scripts/kconfig/merge_config.sh'),
                '-m',
                '-O',
                self.folders.build,
                self._config,
                config_path,
            ]
            cmds_to_log.append(merge_config)
            lkt.utils.chronic(merge_config, cwd=self.folders.build, show_cmd=True)

            need_olddefconfig = True

        if need_olddefconfig:
            base_make_cmd.append('olddefconfig')
        base_make_cmd.append(self.image_target if self.only_test_boot else 'all')
        base_make_cmd += self.make_targets

        # Actually build kernel
        lkt.utils.show_cmd(base_make_cmd)
        cmds_to_log.append(base_make_cmd)
        start_time = time.time()
        sys.stderr.flush()
        sys.stdout.flush()
        with Popen(base_make_cmd, stderr=STDOUT, stdout=PIPE) as proc, self.result.log.open(
            'bw'
        ) as file:
            cmd_log_str = '\n'.join(f"{lkt.utils.cmd_str(cmd)}\n" for cmd in cmds_to_log)
            file.write(cmd_log_str.encode('utf-8'))
            if not proc.stdout:
                raise RuntimeError('proc.stdout is None??')
            while byte := proc.stdout.read(1):
                sys.stdout.buffer.write(byte)
                sys.stdout.flush()
                file.write(byte)

        # Make sure requested configurations are their expected value
        if need_olddefconfig:
            missing_configs = []

            config_text = self._config.read_text(encoding='utf-8')
            for item in requested_options:
                cfg_name, cfg_val = item.split('=', 1)

                # 'CONFIG_FOO=n' does not appear in the final config, it is
                # '# CONFIG_FOO is not set'
                search = f"# {cfg_name} is not set" if cfg_val == 'n' else item
                # If we find a match, move on
                if re.search(f"^{search}$", config_text, flags=re.M):
                    continue

                # If we did not find a match for '# CONFIG_FOO is not set' or
                # CONFIG_FOO="", we should only add it to the missing configs
                # list if it is present with some other value because it may
                # not be visible, which means it is implicitly 'n' or '""'.
                if cfg_val in ('n', '""') and re.search(f"^{cfg_name}=", config_text, flags=re.M):
                    missing_configs.append(item)

            if missing_configs:
                warning_msg = f"\nWARNING: {type(self).__name__}(): Missing requested configurations after olddefconfig: {', '.join(missing_configs)}"
                print(warning_msg)
                with self.result.log.open('a', encoding='utf-8') as file:
                    file.write(f"{warning_msg}\n")

        self.result.build = 'successful' if proc.returncode == 0 else 'failed'

        self.result.duration = lkt.utils.get_time_diff(start_time)
        time_str = f"\nReal\t{self.result.duration}\n"
        print(time_str, end='')
        with self.result.log.open('a', encoding='utf-8') as file:
            file.write(time_str)

    def _distro_adjustments(self) -> list[str]:
        configs: list[str] = []

        config = self.configs[0]
        if not isinstance(config, Path):
            raise ValueError(f"{config} must be a Path object!")
        distro = config.parts[-2]

        if distro == 'alpine':
            # CONFIG_UNIX was not enabled in the linux-edge to linux-stable
            # transition but it is needed to avoid a warning on shutdown
            configs.append('CONFIG_UNIX=y')
            # CONFIG_INET is needed to avoid a warning about setting up lo
            configs.append('CONFIG_INET=y')
            # The new Alpine configurations are defconfig style, which means
            # that on 5.15, CONFIG_BPF_UNPRIV_DEFAULT_OFF is not on by default
            # because of a lack of commit 8a03e56b253e ("bpf: Disallow
            # unprivileged bpf by default"), which causes a warning on boot.
            configs.append('CONFIG_BPF_UNPRIV_DEFAULT_OFF=y')

        if distro == 'debian':
            # The Android drivers are not modular in upstream
            for android_cfg in ('ANDROID_BINDER_IPC', 'ASHMEM'):
                if lkt.utils.is_modular(self.folders.source, self.folders.build, android_cfg):
                    configs.append(f"CONFIG_{android_cfg}=y")

        if 'ppc64le' in config.name or 'powerpc64le' in config.name:
            text = Path(self.folders.source, 'arch/powerpc/Kconfig').read_text(encoding='utf-8')
            search = (
                'int "Order of maximal physically contiguous allocations"\n'
                '\tdefault "8" if PPC64 && PPC_64K_PAGES'
            )
            configs.append(f"CONFIG_ARCH_FORCE_MAX_ORDER={8 if search in text else 9}")

        mtk_common_clk_cfgs: dict[str, tuple[str, ...]] = {
            # clk: mediatek: mt2712: Change Kconfig options to allow module build
            # v6.3-rc1-45-g650fcdf9181e (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/650fcdf9181e4551cd22d651a8e637c800045c97
            'MT2712': (
                '',
                '_BDPSYS',
                '_IMGSYS',
                '_JPGDECSYS',
                '_MFGCFG',
                '_MMSYS',
                '_VDECSYS',
                '_VENCSYS',
            ),
            # clk: mediatek: Allow building most MT6765 clock drivers as modules
            # v6.3-rc1-51-gcfe2c864f0cc (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/cfe2c864f0cc80ef292c0b01bb7b83b4cc393516
            'MT6765': (
                '_AUDIOSYS',
                '_CAMSYS',
                '_GCESYS',
                '_MMSYS',
                '_IMGSYS',
                '_VCODECSYS',
                '_MFGSYS',
                '_MIPI0ASYS',
                '_MIPI0BSYS',
                '_MIPI1ASYS',
                '_MIPI1BSYS',
                '_MIPI2ASYS',
                '_MIPI2BSYS',
            ),
            # clk: mediatek: support COMMON_CLK_MT6779 module build
            # v5.15-rc1-27-gf09b9460a5e4 (Tue Sep 14 18:20:21 2021 -0700)
            # https://git.kernel.org/linus/f09b9460a5e448dac8fb4f645828c0668144f9e6
            'MT6779': (
                '',
                '_AUDSYS',
                '_CAMSYS',
                '_IMGSYS',
                '_IPESYS',
                '_MFGCFG',
                '_MMSYS',
                '_VDECSYS',
                '_VENCSYS',
            ),
            # clk: mediatek: Allow building most MT6797 clock drivers as modules
            # v6.3-rc1-52-g6f0d2e07f2db (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/6f0d2e07f2dbcafdc4018839bc99971dd1a7232d
            'MT6797': ('_MMSYS', '_IMGSYS', '_VDECSYS', '_VENCSYS'),
            # clk: mediatek: Allow MT7622 clocks to be built as modules
            # v6.3-rc1-48-gc8f0ef997329 (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/c8f0ef997329728a136d07967b7a97cba3f07f7b
            'MT7622': ('', '_ETHSYS', '_HIFSYS', '_AUDSYS'),
            # clk: mediatek: Allow all MT8167 clocks to be built as modules
            # v6.3-rc1-49-ga851b17059bc (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/a851b17059bc07572224045f05ee556aa4ab0303
            'MT7986': ('', '_ETHSYS'),
            'MT8167': ('', '_AUDSYS', '_IMGSYS', '_MFGCFG', '_MMSYS', '_VDECSYS'),
            # clk: mediatek: mt8173: Break down clock drivers and allow module build
            # v6.2-rc1-10-g4c02c9af3cb9 (Mon Jan 30 16:45:22 2023 -0800)
            # https://git.kernel.org/linus/4c02c9af3cb9449cd176300b288e8addb5083934
            'MT8173': ('', '_MMSYS'),
            # clk: mediatek: Allow all MT8183 clocks to be built as modules
            # v6.3-rc1-50-g95ffe65437b2 (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/95ffe65437b239db3f5a570b31cd79629c851743
            'MT8183': (
                '',
                '_AUDIOSYS',
                '_CAMSYS',
                '_IMGSYS',
                '_IPU_CORE0',
                '_IPU_CORE1',
                '_IPU_ADL',
                '_IPU_CONN',
                '_MFGCFG',
                '_MMSYS',
                '_VDECSYS',
                '_VENCSYS',
            ),
            # clk: mediatek: Split configuration options for MT8186 clock drivers
            # v6.3-rc1-53-g5baf38e06a57 (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/5baf38e06a570a2a4ed471a996aff6d6ba69cceb
            'MT8186': ('',),
            # clk: mediatek: Kconfig: Allow module build for core mt8192 clocks
            # v6.3-rc1-55-g9bfa4fb1e0d6 (Mon Mar 13 11:50:17 2023 -0700)
            # https://git.kernel.org/linus/9bfa4fb1e0d6de678a79ec5a05fac464edcee91d
            'MT8192': (
                '',
                '_AUDSYS',
                '_CAMSYS',
                '_IMGSYS',
                '_IMP_IIC_WRAP',
                '_IPESYS',
                '_MDPSYS',
                '_MFGCFG',
                '_MMSYS',
                '_MSDC',
                '_SCP_ADSP',
                '_VDECSYS',
                '_VENCSYS',
            ),
            # clk: mediatek: mt8516: Allow building clock drivers as modules
            # v6.3-rc1-37-g876d4e21aad8 (Mon Mar 13 11:50:16 2023 -0700)
            # https://git.kernel.org/linus/876d4e21aad8b60e155dbc5bbfb8c8e75c4d9f4b
            'MT8516': ('', '_AUDSYS'),
        }
        compat_changes: list[tuple[str, str] | tuple[str, tuple[str, str]]] = [
            # ACPI: HED: Always initialize before evged
            # v6.14-rc3-1-gcccf6ee090c8 (Tue Feb 18 19:24:29 2025 +0100)
            # https://git.kernel.org/linus/cccf6ee090c8c133072d5d5b52ae25f3bc907a16
            ('ACPI_HED', 'drivers/acpi/Kconfig'),
            # cpufreq: tegra124: Allow building as a module
            # v6.16-rc2-10-g0ae93389b6c8 (Wed Jul 9 13:41:58 2025 +0530)
            # https://git.kernel.org/linus/0ae93389b6c84fbbc6414a5c78f50d65eea8cf35
            ('ARM_TEGRA124_CPUFREQ', 'drivers/cpufreq/Kconfig.arm'),
            # firmware: arm_scmi: Make OPTEE transport a standalone driver
            # v6.11-rc1-14-gdb9cc5e67778 (Fri Aug 16 10:26:58 2024 +0100)
            # https://git.kernel.org/linus/db9cc5e677783a8a9157804f4a61bb81d83049ac
            ('ARM_SCMI_TRANSPORT_OPTEE', 'drivers/firmware/arm_scmi/transports/Kconfig'),
            # irqchip/irq-bcm7120-l2: Switch to IRQCHIP_PLATFORM_DRIVER
            # v5.15-rc4-13-g3ac268d5ed22 (Wed Oct 20 20:06:34 2021 +0100)
            # https://git.kernel.org/linus/3ac268d5ed2233d4a2db541d8fd744ccc13f46b0
            ('BCM7120_L2_IRQ', 'drivers/irqchip/Kconfig'),
            # can: fix build dependency
            # v6.18-3954-g6abd4577bccc (Wed Dec 10 09:19:34 2025 +0100)
            # https://git.kernel.org/linus/6abd4577bccc66f83edfdb24dc484723ae99cbe8
            ('CAN_DEV', 'drivers/net/can/Kconfig'),
            # power: supply: Allow charger manager can be built as a module
            # v5.6-rc1-3-g241eaabc3c31 (Fri Mar 6 21:31:23 2020 +0100)
            # https://git.kernel.org/linus/241eaabc3c315cdfea505725a43de848f498527f
            ('CHARGER_MANAGER', 'drivers/power/supply/Kconfig'),
            # crypto/chcr: Moving chelsio's inline ipsec functionality to /drivers/net
            # v5.9-rc1-126-g1b77be463929 (Fri Aug 21 14:15:16 2020 -0700)
            # https://git.kernel.org/linus/1b77be463929e6d3cefbc929f710305714a89723
            ('CHELSIO_IPSEC_INLINE', 'drivers/net/ethernet/chelsio/inline_crypto/Kconfig'),
            # Several Mediatek common clock drivers were converted to modules over time
            *[
                (f"COMMON_CLK_{mt_rev}{cfg_suffix}", 'drivers/clk/mediatek/Kconfig')
                for mt_rev, cfg_suffixes in mtk_common_clk_cfgs.items()
                for cfg_suffix in cfg_suffixes
            ],
            # coresight: core: Allow the coresight core driver to be built as a module
            # v5.9-rc5-228-g8e264c52e1da (Mon Sep 28 19:47:42 2020 +0200)
            # https://git.kernel.org/linus/8e264c52e1dab8a7c1e036222ef376c8920c3423
            *[
                (f"CORESIGHT{val}", 'drivers/hwtracing/coresight/Kconfig')
                for val in (
                    '',
                    '_LINKS_AND_SINKS',
                    '_LINK_AND_SINK_TMC',
                    '_CATU',
                    '_SINK_TPIU',
                    '_SINK_ETBV10',
                    '_SOURCE_ETM3X',
                    '_SOURCE_ETM4X',
                    '_STM',
                )
            ],
            # cpufreq: dt-platdev: Support building as module
            # v6.4-rc1-8-g3b062a086984 (Mon Jun 5 16:33:05 2023 +0530)
            # https://git.kernel.org/linus/3b062a086984d35a3c6d3a1c7841d0aa73aa76af
            ('CPUFREQ_DT_PLATDEV', 'drivers/cpufreq/Kconfig'),
            # platform/chrome: cros_ec_proto: Allow to build as module
            # v6.15-rc1-5-gccf395bde6ae (Mon Apr 7 02:51:00 2025 +0000)
            # https://git.kernel.org/linus/ccf395bde6aeefac139f4f250287feb139e3355d
            ('CROS_EC_PROTO', 'drivers/platform/chrome/Kconfig'),
            # crypto: lib/Kconfig - Fix lib built-in failure when arch is modular
            # v6.14-rc1-40-g1047e21aecdf (Sat Feb 22 15:56:03 2025 +0800)
            # https://git.kernel.org/linus/1047e21aecdf17c8a9ab9fd4bd24c6647453f93d
            *[
                (f"CRYPTO_ARCH_HAVE_LIB_{alg}", 'lib/crypto/Kconfig')
                for alg in ('CHACHA', 'CURVE25519', 'POLY1305')
            ],
            # lib/crypto: curve25519: Consolidate into single module
            # v6.17-rc3-35-g68546e5632c0 (Sat Sep 6 16:32:43 2025 -0700)
            # https://git.kernel.org/linus/68546e5632c0b982663af575ae12cc5d81facc91
            ('CRYPTO_LIB_CURVE25519_GENERIC', 'lib/crypto/Kconfig'),
            # lib/crypto: poly1305: Consolidate into single module
            # v6.17-rc3-12-gb646b782e522 (Fri Aug 29 09:49:18 2025 -0700)
            # https://git.kernel.org/linus/b646b782e522da3509e61f971e5502fccb3a3723
            ('CRYPTO_LIB_POLY1305_GENERIC', 'lib/crypto/Kconfig'),
            # cs89x0: rework driver configuration
            # v5.14-rc3-913-g47fd22f2b847 (Tue Aug 3 13:05:25 2021 +0100)
            # https://git.kernel.org/linus/47fd22f2b84765a2f7e3f150282497b902624547
            ('CS89x0_PLATFORM', 'drivers/net/ethernet/cirrus/Kconfig'),
            # lib: Allow for the DIM library to be modular
            # v6.9-rc6-1525-g0d5044b4e774 (Tue May 7 16:42:45 2024 -0700)
            # https://git.kernel.org/linus/0d5044b4e7749099b12da5f2c8618f04bb4fa82f
            ('DIMLIB', 'lib/Kconfig'),
            # drivers: base: test: Make property entry API test modular
            # v6.6-rc4-8-g98ad1dd06a02 (Thu Oct 5 13:11:44 2023 +0200)
            # https://git.kernel.org/linus/98ad1dd06a02096fff6c65703a85b9f3c3de1a7d
            ('DRIVER_PE_KUNIT_TEST', 'drivers/base/test/Kconfig'),
            # drm/client: Add client-lib module
            # v6.12-rc2-592-gdadd28d4142f (Fri Oct 18 09:25:51 2024 +0200)
            # https://git.kernel.org/linus/dadd28d4142f9ad39eefb7b45ee7518bd4d2459c
            ('DRM_CLIENT_SELECTION', 'drivers/gpu/drm/Kconfig'),
            # drm: Move GEM memory managers into modules
            # v5.15-rc1-380-g4b2b5e142ff4 (Fri Oct 22 16:20:23 2021 +0200)
            # https://git.kernel.org/linus/4b2b5e142ff499a2bef2b8db0272bbda1088a3fe
            *[(f"DRM_GEM_{val}_HELPER", 'drivers/gpu/drm/Kconfig') for val in ('CMA', 'SHMEM')],
            # fbdev: Fix recursive dependencies wrt BACKLIGHT_CLASS_DEVICE
            # v6.13-rc1-32-g8fc38062be3f (Tue Dec 17 18:06:10 2024 +0100)
            # https://git.kernel.org/linus/8fc38062be3f692ff8816da84fde71972530bcc4
            ('FB_BACKLIGHT', 'drivers/video/fbdev/core/Kconfig'),
            # netfs, fscache: Combine fscache with netfs
            # v6.7-rc7-4-g915cd30cdea8 (Sun Dec 24 15:08:46 2023 +0000)
            # https://git.kernel.org/linus/915cd30cdea8811cddd8f59e57dd9dd0a814b76c
            # While the new configuration location is fs/netfs/Kconfig, we
            # check for whether or not FSCACHE can be a module in
            # fs/fscache/Kconfig; if it does not exist, we know it cannot be
            # 'm' due to the change above.
            ('FSCACHE', 'fs/fscache/Kconfig'),
            # char: misc: add test cases
            # v6.16-rc3-21-g74d8361be344 (Tue Jun 24 16:46:13 2025 +0100)
            # https://git.kernel.org/linus/74d8361be3441dff0d3bd00840545288451c77a5
            ('TEST_MISC_MINOR', 'lib/Kconfig.debug'),
            *[
                (f"GPIO_{val}", 'drivers/gpio/Kconfig')
                for val in (
                    # gpio: davinci: add support of module build
                    # v6.1-rc1-42-g8dab99c9eab3 (Thu Nov 10 15:24:34 2022 +0100)
                    # https://git.kernel.org/linus/8dab99c9eab3162bfb4326c35579a3388dbf68f2
                    'DAVINCI',
                    # gpio: mxc: Support module build
                    # v5.9-rc1-39-g12d16b397ce0 (Tue Sep 29 15:04:31 2020 +0200)
                    # https://git.kernel.org/linus/12d16b397ce0a999d13762c4c0cae2fb82eb60ee
                    'MXC',
                    # gpio: palmas: Allow building as a module
                    # v6.16-rc1-90-gcfbbf275ffcf (Thu Jul 3 10:37:04 2025 +0200)
                    # https://git.kernel.org/linus/cfbbf275ffcf05c82994b8787b0d1974aa1569d8
                    'PALMAS',
                    # gpio: pl061: Support building as module
                    # v5.7-rc1-3-g616844408de7 (Tue Apr 14 16:23:46 2020 +0200)
                    # https://git.kernel.org/linus/616844408de7f21546c3c2a71ea7f8d364f45e0d
                    'PL061',
                    # gpio: tps68470: Allow building as module
                    # v5.17-rc1-5-ga1ce76e89907 (Mon Jan 24 17:23:15 2022 +0200)
                    # https://git.kernel.org/linus/a1ce76e89907a69713f729ff21db1efa00f3bb47
                    'TPS68470',
                )
            ],
            # KVM: Allow building irqbypass.ko as as module when kvm.ko is a module
            # v6.14-rc7-245-g459a35111b0a (Fri Apr 4 07:07:40 2025 -0400)
            # https://git.kernel.org/linus/459a35111b0a890172a78d51c01b204e13a34a18
            ('HAVE_KVM_IRQ_BYPASS', 'virt/kvm/Kconfig'),
            # Drivers: hv: Make CONFIG_HYPERV bool
            # v6.17-rc1-16-ge3ec97c3abaf (Wed Oct 1 00:00:45 2025 +0000)
            # https://git.kernel.org/linus/e3ec97c3abaf2fb68cc755cae3229288696b9f3d
            ('HYPERV', 'drivers/hv/Kconfig'),
            # firmware: imx: Allow IMX DSP to be selected as module
            # v5.5-rc1-4-gf52cdcce9197 (Thu Jan 9 17:21:33 2020 +0800)
            # https://git.kernel.org/linus/f52cdcce9197fef9d4a68792dd3b840ad2b77117
            ('IMX_DSP', 'drivers/firmware/imx/Kconfig'),
            # RDMA/hns: Clean up the legacy CONFIG_INFINIBAND_HNS
            # v6.13-rc1-49-g8977b561216c (Mon Jan 6 08:41:06 2025 -0500)
            # https://git.kernel.org/linus/8977b561216c7e693d61c6442657e33f134bfeb5
            ('INFINIBAND_HNS_HIP08', 'drivers/infiniband/hw/hns/Kconfig'),
            # kprobes: convert tests to kunit
            # v5.15-rc3-62-ge44e81c5b90f (Thu Oct 21 14:19:01 2021 -0400)
            # https://git.kernel.org/linus/e44e81c5b90f698025eadceb7eef8661eda117d5
            ('KPROBES_SANITY_TEST', 'lib/Kconfig.debug'),
            # mfd: palmas: Add support of module build for Ti palmas chip
            # v6.1-rc1-86-gd4b15e447c35 (Wed Dec 7 13:28:08 2022 +0000)
            # https://git.kernel.org/linus/d4b15e447c352ae74b18261bdaf0023fa9a7d1bd
            ('MFD_PALMAS', 'drivers/mfd/Kconfig'),
            # iommu/mediatek: Allow building as module
            # v5.12-rc3-2-g18d8c74ec598 (Wed Apr 7 10:33:58 2021 +0200)
            # https://git.kernel.org/linus/18d8c74ec5987a78bd1e9c1c629dfdd04a151a89
            ('MTK_IOMMU', 'drivers/iommu/Kconfig'),
            # mtk-mmsys: Change mtk-mmsys & mtk-mutex to modules
            # v6.2-rc1-7-ga7596e62dac7 (Mon Jan 9 17:17:47 2023 +0100)
            # https://git.kernel.org/linus/a7596e62dac7318456c1aa9af5bfccf0f8e6ad7e
            ('MTK_MMSYS', 'drivers/soc/mediatek/Kconfig'),
            # memory: mtk-smi: Allow building as module
            # v5.11-rc1-7-g50fc8d9232cd (Tue Jan 26 20:47:51 2021 +0100)
            # https://git.kernel.org/linus/50fc8d9232cdc64b9e9d1b9488452f153de52b69
            ('MTK_SMI', 'drivers/memory/Kconfig'),
            # mux: add visible config symbol to enable multiplexer subsystem
            # v7.0-rc1-8-gce5c7c17e706 (Mon Mar 9 13:44:45 2026 +0100)
            # https://git.kernel.org/linus/ce5c7c17e70640fc5635fd2252d0bdf4664d452b
            ('MULTIPLEXER', 'drivers/mux/Kconfig'),
            # net/9p/usbg: allow building as standalone module
            # v6.12-rc7-5-ge0260d530b73 (Fri Nov 22 23:48:14 2024 +0900)
            # https://git.kernel.org/linus/e0260d530b73ee969ae971d14daa02376dcfc93f
            ('NET_9P_USBG', 'net/9p/Kconfig'),
            # net: dsa: realtek: merge rtl83xx and interface modules into realtek_dsa
            # v6.8-rc3-845-g98b75c1c149c (Mon Feb 12 10:42:17 2024 +0000)
            # https://git.kernel.org/linus/98b75c1c149c653ad11a440636213eb070325158
            *[
                (f"NET_DSA_REALTEK_{val}", 'drivers/net/dsa/realtek/Kconfig')
                for val in ('MDIO', 'SMI')
            ],
            # nvme: common: make keyring and auth separate modules
            # v6.6-14662-g6affe08aea5f (Tue Nov 7 10:05:15 2023 -0800)
            # https://git.kernel.org/linus/6affe08aea5f3b630565676e227b41d55a6f009c
            ('NVME_AUTH', 'drivers/nvme/common/Kconfig'),
            # nvmem: xilinx: zynqmp: make modular
            # v6.3-rc3-32-gbcd1fe07def0 (Wed Apr 5 19:41:10 2023 +0200)
            # https://git.kernel.org/linus/bcd1fe07def0f070eb5f31594620aaee6f81d31a
            ('NVMEM_ZYNQMP', 'drivers/nvmem/Kconfig'),
            *[
                (f"PCI_{val}", 'drivers/pci/controller/dwc/Kconfig')
                for val in (
                    # nvme: common: make keyring and auth separate modules
                    # v6.6-14662-g6affe08aea5f (Tue Nov 7 10:05:15 2023 -0800)
                    # https://git.kernel.org/linus/6affe08aea5f3b630565676e227b41d55a6f009c
                    'DRA7XX',
                    'DRA7XX_EP',
                    'DRA7XX_HOST',
                    # PCI: dwc: exynos: Rework the driver to support Exynos5433 variant
                    # v5.10-rc3-23-g778f7c194b1d (Tue Dec 1 10:22:30 2020 +0000)
                    # https://git.kernel.org/linus/778f7c194b1dac351d345ce723f8747026092949
                    'EXYNOS',
                    # PCI: meson: Build as module by default
                    # v5.9-rc1-1-ga98d2187efd9 (Mon Oct 5 13:01:42 2020 +0100)
                    # https://git.kernel.org/linus/a98d2187efd9e6d554efb50e3ed3a2983d340fe5
                    'MESON',
                )
            ],
            # PCI: mvebu: Add support for compiling driver as module
            # v5.16-rc1-22-g0746ae1be121 (Thu Jan 6 13:37:47 2022 +0000)
            # https://git.kernel.org/linus/0746ae1be12177ebda0666eefa82583cbaeeefd6
            ('PCI_MVEBU', 'drivers/pci/controller/Kconfig'),
            # pinctrl: rockchip: make driver be tristate module
            # v5.12-rc2-17-gbe786ac5a6c4 (Mon Mar 15 16:36:44 2021 +0100)
            # https://git.kernel.org/linus/be786ac5a6c4bf4ef3e4c569a045d302c1e60fe6
            ('PINCTRL_ROCKCHIP', 'drivers/pinctrl/Kconfig'),
            # pinctrl: spacemit: enable config option
            # v6.14-rc4-3-g7ff4faba6357 (Tue Feb 25 17:22:36 2025 +0100)
            # https://git.kernel.org/linus/7ff4faba63571c51004280f7eb5d6362b15ec61f
            ('PINCTRL_SPACEMIT_K1', 'drivers/pinctrl/spacemit/Kconfig'),
            # power: reset: sc27xx: Allow the SC27XX poweroff driver building into a module
            # v5.6-rc1-26-gf78c55e3b480 (Wed Mar 11 23:32:09 2020 +0100)
            # https://git.kernel.org/linus/f78c55e3b4806974f7d590b2aab8683232b7bd25
            ('POWER_RESET_SC27XX', 'drivers/power/reset/Kconfig'),
            # thermal: int340x: processor_thermal: Refactor MMIO interface
            # v5.10-rc1-30-ga5923b6c3137 (Thu Dec 10 12:29:47 2020 +0100)
            # https://git.kernel.org/linus/a5923b6c3137b9d4fc2ea1c997f6e4d51ac5d774
            ('PROC_THERMAL_MMIO_RAPL', 'drivers/thermal/intel/int340x_thermal/Kconfig'),
            # pwm: crc: Allow compilation as module and with COMPILE_TEST
            # v6.6-rc1-8-g91a69d38cf97 (Fri Oct 13 10:07:17 2023 +0200)
            # https://git.kernel.org/linus/91a69d38cf97b195fef1a10ea53cf429aa134497
            ('PWM_CRC', 'drivers/pwm/Kconfig'),
            # mailbox: qcom-ipcc: Enable loading QCOM_IPCC as a module
            # v5.14-rc7-2-g8d7e5908c0bc (Sun Aug 29 23:50:15 2021 -0500)
            # https://git.kernel.org/linus/8d7e5908c0bcf8a0abc437385e58e49abab11a93
            ('QCOM_IPCC', 'drivers/mailbox/Kconfig'),
            *[
                # pmdomain: qcom: Move Kconfig options to the pmdomain subsystem
                # v6.6-rc1-20-g4eb42e5bd86d (Wed Oct 4 23:41:18 2023 +0200)
                # https://git.kernel.org/linus/4eb42e5bd86da528be604845f52732742ef74e6b
                (f"QCOM_RPM{val}PD", ('drivers/pmdomain/qcom/Kconfig', 'drivers/soc/qcom/Kconfig'))
                for val in (
                    # soc: qcom: rpmpd: Allow RPMPD driver to be loaded as a module
                    # v5.7-rc1-22-gf29808b2fb85 (Tue Apr 14 15:39:56 2020 -0700)
                    # https://git.kernel.org/linus/f29808b2fb85a7ff2d4830aa1cb736c8c9b986f4
                    '',
                    # soc: qcom: rpmhpd: Allow RPMHPD driver to be loaded as a module
                    # v5.7-rc1-21-gd4889ec1fc6a (Tue Apr 14 15:39:46 2020 -0700)
                    # https://git.kernel.org/linus/d4889ec1fc6ac6321cc1e8b35bb656f970926a09
                    'H',
                )
            ],
            # media: make RADIO_ADAPTERS tristate
            # v5.18-rc3-170-g215d49a41709 (Fri May 13 11:02:19 2022 +0200)
            # https://git.kernel.org/linus/215d49a41709610b9e82a49b27269cfaff1ef0b6
            ('RADIO_ADAPTERS', 'drivers/media/radio/Kconfig'),
            # math: make RATIONAL tristate
            # v5.14-65-gbcda5fd34417 (Wed Sep 8 11:50:26 2021 -0700)
            # https://git.kernel.org/linus/bcda5fd34417c89f653cc0912cc0608b36ea032c
            ('RATIONAL', 'lib/math/Kconfig'),
            # reset: imx7: Support module build
            # v5.9-rc1-1-ga442abbbe186 (Wed Sep 23 14:25:31 2020 +0200)
            # https://git.kernel.org/linus/a442abbbe186e14128d18bc3e42fb0fbf1a62210
            ('RESET_IMX7', 'drivers/reset/Kconfig'),
            # reset: meson: make it possible to build as a module
            # v5.10-rc1-2-g3bfe8933f9d1 (Mon Nov 16 17:05:29 2020 +0100)
            # https://git.kernel.org/linus/3bfe8933f9d187f93f0d0910b741a59070f58c4c
            # reset: amlogic: move drivers to a dedicated directory
            # v6.12-rc1-7-g2c138ee3354f (Tue Oct 1 10:40:32 2024 +0200)
            # https://git.kernel.org/linus/2c138ee3354f8088769d05701a2e16d1cb4cc22d
            ('RESET_MESON', ('drivers/reset/amlogic/Kconfig', 'drivers/reset/Kconfig')),
            # rtw88: extract: make 8822b an individual kernel module
            # v5.7-rc4-1504-g416e87fcc780 (Mon May 18 15:16:19 2020 +0300)
            # https://git.kernel.org/linus/416e87fcc780cae8d72cb9370fa0f46007faa69a
            # rtw88: extract: make 8822c an individual kernel module
            # v5.7-rc4-1503-gba0fbe236fb8 (Mon May 18 15:16:18 2020 +0300)
            # https://git.kernel.org/linus/ba0fbe236fb8a7b992e82d6eafb03a600f5eba43
            *[
                (f"RTW88_8822{val}E", 'drivers/net/wireless/realtek/rtw88/Kconfig')
                for val in ('B', 'C')
            ],
            # serial: sc16is7xx: split into core and I2C/SPI parts (core)
            # v6.9-rc3-58-gd49216438139 (Thu Apr 11 14:08:08 2024 +0200)
            # https://git.kernel.org/linus/d49216438139bca0454e69b6c4ab8a01af2b72ed
            *[(f"SERIAL_SC16IS7XX_{val}", 'drivers/tty/serial/Kconfig') for val in ('I2C', 'SPI')],
            # serial: lantiq: Make driver modular
            # v5.7-rc5-26-gad406341bdd7 (Fri May 15 12:22:19 2020 +0200)
            # https://git.kernel.org/linus/ad406341bdd7d22ba9497931c2df5dde6bb9440e
            ('SERIAL_LANTIQ', 'drivers/tty/serial/Kconfig'),
            # ASoC: SOF: Convert the generic probe support to SOF client
            # v5.17-rc1-108-g3dc0d7091778 (Thu Feb 10 15:19:12 2022 +0000)
            # https://git.kernel.org/linus/3dc0d709177828a22dfc9d0072e3ac937ef90d06
            ('SND_SOC_SOF_DEBUG_PROBES', 'sound/soc/sof/Kconfig'),
            # ASoC: SOF: Kconfig: Make SND_SOC_SOF_HDA_PROBES tristate
            # v5.18-rc1-175-ge18610eaa66a (Tue Apr 19 16:30:31 2022 +0100)
            # https://git.kernel.org/linus/e18610eaa66a1849aaa00ca43d605fb1a6fed800
            ('SND_SOC_SOF_HDA_PROBES', 'sound/soc/sof/intel/Kconfig'),
            # ASoC: sprd: Allow the MCDT driver to build into modules
            # v5.6-rc1-220-gfd357ec595d3 (Thu Mar 5 13:15:17 2020 +0000)
            # https://git.kernel.org/linus/fd357ec595d36676c239d8d16706a270a961ac32
            ('SND_SOC_SPRD_MCDT', 'sound/soc/sprd/Kconfig'),
            # clk: sunxi-ng: Allow the CCU core to be built as a module
            # v5.16-rc1-4-g91389c390521 (Tue Nov 23 10:29:05 2021 +0100)
            # https://git.kernel.org/linus/91389c390521a02ecfb91270f5b9d7fae4312ae5
            ('SUNXI_CCU', 'drivers/clk/sunxi-ng/Kconfig'),
            # clk: sunxi-ng: Allow drivers to be built as modules
            # v5.16-rc1-2-gc8c525b06f53 (Mon Nov 22 10:02:21 2021 +0100)
            # https://git.kernel.org/linus/c8c525b06f532923d21d99811a7b80bf18ffd2be
            ('SUN8I_DE2_CCU', 'drivers/clk/sunxi-ng/Kconfig'),
            # kunit: allow kunit tests to be loaded as a module
            # v5.5-rc5-4-gc475c77d5b56 (Thu Jan 9 16:42:29 2020 -0700)
            # https://git.kernel.org/linus/c475c77d5b56398303e726969e81208196b3aab3
            ('SYSCTL_KUNIT_TEST', 'lib/Kconfig.debug'),
            *[
                (f"TEGRA{ver}_EMC", 'drivers/memory/tegra/Kconfig')
                for ver in (
                    # memory: tegra124-emc: Make driver modular
                    # v5.11-rc1-1-g281462e59348 (Tue Jan 5 18:00:09 2021 +0100)
                    # https://git.kernel.org/linus/281462e593483350d8072a118c6e072c550a80fa
                    '124',
                    # memory: tegra20-emc: Make driver modular
                    # v5.10-rc1-27-g0260979b018f (Thu Nov 26 18:50:35 2020 +0100)
                    # https://git.kernel.org/linus/0260979b018faaf90ff5a7bb04ac3f38e9dee6e3
                    '20',
                    # memory: tegra30-emc: Make driver modular
                    # v5.10-rc1-36-g0c56eda86f8c (Thu Nov 26 18:50:36 2020 +0100)
                    # https://git.kernel.org/linus/0c56eda86f8cad705d7d14e81e0e4efaeeaf4613
                    '30',
                )
            ],
            # net: ethernet: ti: Remove TI_CPTS_MOD workaround
            # v5.7-rc4-192-g92db978f0d68 (Tue May 12 12:33:27 2020 -0700)
            # https://git.kernel.org/linus/92db978f0d686468e527d49268e7c7e8d97d334b
            ('TI_CPTS', 'drivers/net/ethernet/ti/Kconfig'),
            # dmaengine: ti: convert PSIL to be buildable as module
            # v6.1-rc1-9-gd15aae73a9f6 (Wed Oct 19 18:58:05 2022 +0530)
            # https://git.kernel.org/linus/d15aae73a9f6c321167b9120f263df7dbc08d2ba
            ('TI_K3_PSIL', 'drivers/dma/ti/Kconfig'),
            # soc: ti: k3-ringacc: Allow the driver to be built as module
            # v6.1-rc1-5-gc07f216a8b72 (Thu Nov 3 01:42:50 2022 -0500)
            # https://git.kernel.org/linus/c07f216a8b72bac0c6e921793ad656a3b77f3545
            ('TI_K3_RINGACC', 'drivers/soc/ti/Kconfig'),
            # dmaengine: ti: convert k3-udma to module
            # v6.1-rc1-8-g56b0a668cb35 (Wed Oct 19 18:58:05 2022 +0530)
            # https://git.kernel.org/linus/56b0a668cb35c5f04ef98ffc22b297f116fe7108
            *[(f"TI_K3_UDMA{suffix}", 'drivers/dma/ti/Kconfig') for suffix in ('', '_GLUE_LAYER')],
            *[
                (f"TI_SCI_INT{val}_IRQCHIP", 'drivers/irqchip/Kconfig')
                for val in (
                    # irqchip/ti-sci-intr: Add module build support
                    # v6.13-rc1-8-g2d95ffaecbc2 (Wed Jan 15 09:54:29 2025 +0100)
                    # https://git.kernel.org/linus/2d95ffaecbc2a29cf4a0fa8e63ce99ded7184991
                    'A',
                    # irqchip/ti-sci-inta : Add module build support
                    # v6.13-rc1-9-gb8b26ae398c4 (Wed Jan 15 09:54:29 2025 +0100)
                    # https://git.kernel.org/linus/b8b26ae398c4577893a4c43195dba0e75af6e33f
                    'R',
                )
            ],
            # unicode: clean up the Kconfig symbol confusion
            # v5.16-10497-g5298d4bfe80f (Thu Jan 20 19:57:24 2022 -0500)
            # https://git.kernel.org/linus/5298d4bfe80f6ae6ae2777bcd1357b0022d98573
            ('UNICODE', 'fs/unicode/Kconfig'),
            # vfio: Fold vfio_virqfd.ko into vfio.ko
            # v6.1-rc4-20-ge2d55709398e (Mon Dec 5 12:04:32 2022 -0700)
            # https://git.kernel.org/linus/e2d55709398e62cf53e5c7df3758ae52cc62d63a
            ('VFIO_VIRQFD', 'drivers/vfio/Kconfig'),
            # iommu/virtio: Build virtio-iommu as module
            # v5.6-rc3-1-gfa4afd78ea12 (Fri Feb 28 16:19:57 2020 +0100)
            # https://git.kernel.org/linus/fa4afd78ea12cf31113f8b146b696c500d6a9dc3
            ('VIRTIO_IOMMU', 'drivers/iommu/Kconfig'),
            # xen/pvcalls: backend can be a module
            # v5.14-16-g45da234467f3 (Wed Sep 15 08:42:04 2021 +0200)
            # https://git.kernel.org/linus/45da234467f381239d87536c86597149f189d375
            ('XEN_PVCALLS_BACKEND', 'drivers/xen/Kconfig'),
        ]
        for config_sym, locations in compat_changes:
            # Check if the symbol is modular in the current configuration and move on if not
            if not lkt.utils.is_modular(self.folders.source, self.folders.build, config_sym):
                continue

            if isinstance(locations, str):
                files = (locations,)
            elif isinstance(locations, tuple):
                files = locations
            else:
                raise ValueError('locations neither a string nor a tuple?')

            can_be_m = False
            for file in files:
                if (kconfig_file := Path(self.folders.source, file)).exists():
                    kconfig_text = ''.join(kconfig_file.read_text(encoding='utf-8').split())
                    if f"config{config_sym}tristate" in kconfig_text:
                        can_be_m = True
                        break

            if not can_be_m:
                configs.append(f"CONFIG_{config_sym}=y")
                if config_sym == 'CS89x0_PLATFORM':
                    configs.append('CONFIG_CS89x0=y')

        # mfd: arizona: Allow building arizona MFD-core as module
        # v5.13-rc1-54-g33d550701b91 (Wed Jun 2 10:50:04 2021 +0100)
        # https://git.kernel.org/linus/33d550701b915938bd35ca323ee479e52029adf2
        # Done manually because 'tristate'/'bool' is not right after 'config MFD_ARIZONA'...
        mfd_arizona_is_m = lkt.utils.is_modular(
            self.folders.source, self.folders.build, 'MFD_ARIZONA'
        )
        file_text = Path(self.folders.source, 'drivers/mfd/Makefile').read_text(encoding='utf-8')
        if mfd_arizona_is_m and 'arizona-objs' not in file_text:
            configs.append('CONFIG_MFD_ARIZONA=y')

        changed_type_cfgs: list[tuple[str, str]] = [
            # printk: Change type of CONFIG_BASE_SMALL to bool
            # v6.8-5294-gb3e90f375b3c (Mon May 6 17:39:09 2024 +0200)
            # https://git.kernel.org/linus/b3e90f375b3c7ab85aef631ebb0ad8ce66cbf3fd
            ('BASE_SMALL', 'init/Kconfig'),
            # hung_task: panic when there are more than N hung tasks at the same time
            # v6.18-rc5-15-g9544f9e6947f (Wed Nov 12 10:00:14 2025 -0800)
            # https://git.kernel.org/linus/9544f9e6947f6508d29f0d0cc2dacaa749fc1613
            ('BOOTPARAM_HUNG_TASK_PANIC', 'lib/Kconfig.debug'),
            # watchdog: softlockup: panic when lockup duration exceeds N thresholds
            # v6.19-rc6-56-ge700f5d15607 (Tue Jan 20 19:44:20 2026 -0800)
            # https://git.kernel.org/linus/e700f5d1560798aacf0e56fdcc70ee2c20bf56ec
            ('BOOTPARAM_SOFTLOCKUP_PANIC', 'lib/Kconfig.debug'),
        ]
        for cfg, file in changed_type_cfgs:
            file_text = ''.join(Path(self.folders.source, file).read_text(encoding='utf-8').split())
            val = lkt.utils.get_config_val(self.folders.source, self.folders.build, cfg)

            if f"config{cfg}int" in file_text and val == 'n':
                configs.append(f"CONFIG_{cfg}=0")
            if f"config{cfg}bool" in file_text and val == '0':
                configs.append(f"CONFIG_{cfg}=n")

        file_text = Path(self.folders.source, 'lib/Kconfig.ubsan').read_text(encoding='utf-8')
        check_cfg = (
            f"UBSAN_{'SIGNED' if 'config UBSAN_INTEGER_WRAP' in file_text else 'INTEGER'}_WRAP"
        )
        if not lkt.utils.is_set(self.folders.source, self.folders.build, check_cfg):
            configs.append(
                f"CONFIG_UBSAN_{'INTEGER' if check_cfg == 'UBSAN_SIGNED_WRAP' else 'SIGNED'}_WRAP=n",
            )

        # clocksource/drivers/arm_global_timer: Add auto-detection for initial prescaler values
        # v6.17-rc1-49-g1c4b87c921fb (Tue Sep 23 12:41:58 2025 +0200)
        # https://git.kernel.org/linus/1c4b87c921fb158d853adcb8fd48c2dc07fc6f91
        if lkt.utils.is_set(self.folders.source, self.folders.build, 'ARM_GLOBAL_TIMER'):
            file_text = ''.join(
                Path(self.folders.source, 'drivers/clocksource/Kconfig')
                .read_text(encoding='utf-8')
                .split()
            )
            have_1c4b87c921fb1 = (
                'config ARM_GT_INITIAL_PRESCALER_VALint "ARM global timer initial prescaler value"default 0'
                in file_text
            )
            have_zero_prescalar_val = (
                lkt.utils.get_config_val(
                    self.folders.source, self.folders.build, cfg := 'ARM_GT_INITIAL_PRESCALER_VAL'
                )
                == '0'
            )
            if not have_1c4b87c921fb1 and have_zero_prescalar_val:
                configs.append(f"CONFIG_{cfg}=1")

        return configs

    def _initial_distro_prep(self) -> None:
        config = self.configs[0]
        if not isinstance(config, Path):
            raise ValueError(f"{config} must be a Path object!")
        distro = config.parts[-2]

        # CONFIG_DEBUG_INFO_BTF has two conditions:
        #
        #   * pahole needs to be available
        #
        #   * The kernel needs https://git.kernel.org/linus/90ceddcb495008ac8ba7a3dce297841efcd7d584,
        #     which is first available in 5.7: https://github.com/ClangBuiltLinux/linux/issues/871
        #
        # If either of those conditions are false, we need to disable this config so
        # that the build does not error.
        debug_info_btf_y = lkt.utils.is_set(self.folders.source, config, 'DEBUG_INFO_BTF')
        pahole_available = shutil.which('pahole')
        if debug_info_btf_y and not (pahole_available and self.lsm.version >= (5, 7, 0)):
            self.configs.append('CONFIG_DEBUG_INFO_BTF=n')

        if (
            'e96f2d64c812d' not in self.lsm.commits
            and 'CONFIG_BPF_PRELOAD' in self.lsm.configs
            and lkt.utils.is_set(self.folders.source, config, 'BPF_PRELOAD')
        ):
            self.configs.append('CONFIG_BPF_PRELOAD=n')

        if distro == 'archlinux' and lkt.utils.is_set(
            self.folders.source, config, 'EXTRA_FIRMWARE'
        ):
            self.configs.append('CONFIG_EXTRA_FIRMWARE=""')

        if distro == 'debian' and lkt.utils.is_set(
            self.folders.source, config, 'SYSTEM_TRUSTED_KEYS'
        ):
            self.configs.append('CONFIG_SYSTEM_TRUSTED_KEYS=n')

        if (
            distro == 'fedora'
            and config.stem in ('aarch64', 'riscv64', 'x86_64')
            and lkt.utils.is_set(self.folders.source, config, 'EFI_SBAT_FILE')
        ):
            self.configs.append('CONFIG_EFI_SBAT_FILE=""')

        for val in KNOWN_SUBSYS_WERROR_CONFIGS:
            if lkt.utils.is_set(self.folders.source, config, val):
                self.configs.append(f"CONFIG_{val}=n")

    def run(self) -> Result:
        if not lkt.utils.path_is_set(self.folders.source):
            raise RuntimeError('No source location set?')
        if not lkt.utils.path_is_set(self.folders.build):
            raise RuntimeError('No build folder set?')
        if not self.configs:
            raise RuntimeError('No configuration to build?')
        if not self.lsm:
            raise RuntimeError('No source manager set?')

        self._config = Path(self.folders.build, '.config')

        if 'allmodconfig' in self.configs and 'CONFIG_WERROR' in self.lsm.configs:
            self.configs.append('CONFIG_WERROR=n')

        if 'CONFIG_WERROR=n' in self.configs:
            # We do not want to have to maintain these in the callers but it is
            # important to note them in the build logs, so we add them here.
            # We should not add configurations that do not exist in the
            # tree that we are testing.
            self.configs += [
                f"{full_cfg}=n"
                for val in KNOWN_SUBSYS_WERROR_CONFIGS
                if (full_cfg := f"CONFIG_{val}") in self.lsm.configs
            ]

        # Handle distribution configurations that need to disable
        # configurations to build properly, as those configuration
        # changes should be visible in the log.
        if isinstance(self.configs[0], Path):
            configs: list[str] = [f"{self.configs[0].parts[-2]} config"]
            self._initial_distro_prep()
            if len(self.configs) > 1:
                configs += map(str, self.configs[1:])
        else:
            configs: list[str] = list(map(str, self.configs))
        self.result.name = f"{self.make_vars['ARCH']} {' + '.join(configs)}"
        print(f"\nBuilding {self.result.name}...")

        self.folders.log.mkdir(exist_ok=True, parents=True)
        log_name = self.result.name.replace(' ', '-').replace('-+-', '-').replace('""', '')
        self.result.log = Path(self.folders.log, f"{log_name[0:251]}.log")

        self._build_kernel()
        self._boot_kernel()

        return self.result


class LKTRunner:
    def __init__(self, arch: str, clang_target: str) -> None:
        self.folders: Folders = Folders()
        self.lsm: LinuxSourceManager = LinuxSourceManager()
        self.make_vars: MakeVars = {'ARCH': arch}
        self.only_test_boot: bool = False
        self.targets: list[str] = []
        self.save_objects: bool = False

        self._llvm_version: ClangVersion = ClangVersion()

        self._clang_target: str = clang_target
        self._results: list[Result] = []
        self._runners: list[LLVMKernelRunner] = []

    def _skip_all(self, log_reason: str, print_reason: str) -> list[Result]:
        result = Result()
        result.name = f"{self.make_vars['ARCH']} kernels"
        result.build = 'skipped'
        result.reason = log_reason
        self._results = [result]

        lkt.utils.header(f"Skipping {result.name}")
        print(f"Reason: {print_reason}")

        return self._results

    def _skip_one(self, name: str, reason: str) -> None:
        result = Result()
        result.name = name
        result.build = 'skipped'
        result.reason = reason
        self._results.append(result)
        print(f"Skipping {name} due to {reason}")

    def run(self) -> list[Result]:
        if not lkt.utils.clang_supports_target(self._clang_target):
            return self._skip_all(
                'missing clang target', f"Missing {self._clang_target} target in clang"
            )

        if (
            'CROSS_COMPILE' in self.make_vars
            and self.make_vars.get('LLVM_IAS', '1') == '0'
            and not shutil.which(f"{self.make_vars['CROSS_COMPILE']}as")
        ):
            return self._skip_all('missing binutils', 'Cannot find binutils')

        lkt.utils.header(f"Building {self.make_vars['ARCH']} kernels", end='')

        self.folders.build = Path(self.folders.build, self.make_vars['ARCH'])

        for runner in self._runners:
            runner.folders = self.folders
            if not lkt.utils.path_is_set(runner.lsm.folder):
                if not lkt.utils.path_is_set(self.lsm.folder):
                    raise RuntimeError('LinuxSourceManager is completely uninitialized!')
                runner.lsm = self.lsm
            runner.make_vars.update(self.make_vars)
            self._results.append(runner.run())

        if not self.save_objects:
            shutil.rmtree(self.folders.build)

        return self._results
