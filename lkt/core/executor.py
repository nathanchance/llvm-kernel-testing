import os
import shutil
import time
from pathlib import Path

import lkt.utils

from .env import EnvInfo
from .job import MakeJob, TestJob
from .matrix import ArchMatrix
from .source import LinuxSourceTree

KNOWN_SUBSYS_WERROR_CONFIGS = ('DRM_WERROR',)


def using_kvm(boot_utils_arch: str, boot_utils_folder: Path) -> bool:
    if lkt.utils.MACHINE == 'aarch64':
        if boot_utils_arch in {'arm', 'arm32_v7'}:
            can_use_kvm = lkt.utils.run_check_rc_zero(
                Path(boot_utils_folder, 'utils/aarch64_32_bit_el1_supported')
            )
        else:
            can_use_kvm = boot_utils_arch in {'arm64', 'arm64be'}
    elif lkt.utils.MACHINE == 'x86_64':
        can_use_kvm = boot_utils_arch in {'x86', 'x86_64'}
    else:
        can_use_kvm = False
    return can_use_kvm and lkt.utils.HAVE_DEV_KVM_ACCESS


def gen_log_cmd(cmd_str: str) -> str:
    return f"@echo '$$ {cmd_str}' $(LOG_OUTPUT_SILENT)"


def initial_distro_prep(lst: LinuxSourceTree, config: Path) -> list[str]:
    configs: list[str] = []

    if lst.is_config_set(config, 'DEBUG_INFO_BTF') and not shutil.which('pahole'):
        configs.append('CONFIG_DEBUG_INFO_BTF=n')

    if (
        # bpf: Drop libbpf, libelf, libz dependency from bpf preload.
        # v5.16-11580-ge96f2d64c812 (Tue Feb 1 23:56:18 2022 +0100)
        # https://git.kernel.org/linus/e96f2d64c812d9c20adea38a9b5e08feaa21fcf5
        'e96f2d64c812d9c20adea38a9b5e08feaa21fcf5' not in lst.commits
        and lst.is_config_set(config, 'BPF_PRELOAD')
    ):
        configs.append('CONFIG_BPF_PRELOAD=n')

    return configs


def distro_adjustments(lst: LinuxSourceTree, config: Path) -> list[str]:
    configs: list[str] = []
    distro = config.parts[-2]

    if distro == 'alpine':
        configs += [
            # CONFIG_UNIX was not enabled in the linux-edge to linux-stable
            # transition but it is needed to avoid a warning on shutdown
            'CONFIG_UNIX=y',
            # CONFIG_INET is needed to avoid a warning about setting up lo
            'CONFIG_INET=y',
            # The new Alpine configurations are defconfig style, which
            # means that on 5.15, CONFIG_BPF_UNPRIV_DEFAULT_OFF is not on
            # by default because of a lack of commit 8a03e56b253e ("bpf:
            # Disallow unprivileged bpf by default"), which causes a
            # warning on boot.
            'CONFIG_BPF_UNPRIV_DEFAULT_OFF=y',
        ]

    if distro == 'debian':
        # The Android drivers are not modular in upstream
        configs.extend(
            f"CONFIG_{android_cfg}=y"
            for android_cfg in ('ANDROID_BINDER_IPC', 'ASHMEM')
            if lst.is_config_modular(config, android_cfg)
        )

    if 'ppc64le' in config.name or 'powerpc64le' in config.name:
        text = lst.read_text('arch/powerpc/Kconfig')
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
        # Several Mediatek common clock drivers were converted to modules over time
        *[
            (f"COMMON_CLK_{mt_rev}{cfg_suffix}", 'drivers/clk/mediatek/Kconfig')
            for mt_rev, cfg_suffixes in mtk_common_clk_cfgs.items()
            for cfg_suffix in cfg_suffixes
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
                # gpio: palmas: Allow building as a module
                # v6.16-rc1-90-gcfbbf275ffcf (Thu Jul 3 10:37:04 2025 +0200)
                # https://git.kernel.org/linus/cfbbf275ffcf05c82994b8787b0d1974aa1569d8
                'PALMAS',
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
        # pmdomain: imx: Make IMX8M/IMX9 BLK_CTRL tristate
        # v7.2-rc2-19-gce2bf9837092 (Tue Jul 14 15:21:18 2026 +0200)
        # https://git.kernel.org/linus/ce2bf9837092be587050697a4d64ee43a1ead2f2
        ('IMX9_BLK_CTRL', 'drivers/pmdomain/imx/Kconfig'),
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
        # mtk-mmsys: Change mtk-mmsys & mtk-mutex to modules
        # v6.2-rc1-7-ga7596e62dac7 (Mon Jan 9 17:17:47 2023 +0100)
        # https://git.kernel.org/linus/a7596e62dac7318456c1aa9af5bfccf0f8e6ad7e
        ('MTK_MMSYS', 'drivers/soc/mediatek/Kconfig'),
        # mux: add visible config symbol to enable multiplexer subsystem
        # v7.0-rc1-8-gce5c7c17e706 (Mon Mar 9 13:44:45 2026 +0100)
        # https://git.kernel.org/linus/ce5c7c17e70640fc5635fd2252d0bdf4664d452b
        ('MULTIPLEXER', 'drivers/mux/Kconfig'),
        # net/9p/usbg: allow building as standalone module
        # v6.12-rc7-5-ge0260d530b73 (Fri Nov 22 23:48:14 2024 +0900)
        # https://git.kernel.org/linus/e0260d530b73ee969ae971d14daa02376dcfc93f
        ('NET_9P_USBG', 'net/9p/Kconfig'),
        # netfilter: allow nfnetlink built-in only
        # v7.1-rc4-953-gd4349ba9872d (Sun May 24 22:55:47 2026 +0200)
        # https://git.kernel.org/linus/d4349ba9872d0c97a31fb2a18789297731061e88
        ('NETFILTER_NETLINK', 'net/netfilter/Kconfig'),
        # net: dsa: realtek: merge rtl83xx and interface modules into realtek_dsa
        # v6.8-rc3-845-g98b75c1c149c (Mon Feb 12 10:42:17 2024 +0000)
        # https://git.kernel.org/linus/98b75c1c149c653ad11a440636213eb070325158
        *[(f"NET_DSA_REALTEK_{val}", 'drivers/net/dsa/realtek/Kconfig') for val in ('MDIO', 'SMI')],
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
            )
        ],
        # PCI: mvebu: Add support for compiling driver as module
        # v5.16-rc1-22-g0746ae1be121 (Thu Jan 6 13:37:47 2022 +0000)
        # https://git.kernel.org/linus/0746ae1be12177ebda0666eefa82583cbaeeefd6
        ('PCI_MVEBU', 'drivers/pci/controller/Kconfig'),
        # pinctrl: mediatek: enable module build support for all SoC drivers
        # v7.2-rc1-51-g5f30668104fe (Mon Jul 27 11:11:13 2026 +0200)
        # https://git.kernel.org/linus/5f30668104fe7ed2959ffeb67459a0288022b50e
        ('PINCTRL_MT6397', 'drivers/pinctrl/mediatek/Kconfig'),
        # pinctrl: spacemit: enable config option
        # v6.14-rc4-3-g7ff4faba6357 (Tue Feb 25 17:22:36 2025 +0100)
        # https://git.kernel.org/linus/7ff4faba63571c51004280f7eb5d6362b15ec61f
        ('PINCTRL_SPACEMIT_K1', 'drivers/pinctrl/spacemit/Kconfig'),
        # pwm: crc: Allow compilation as module and with COMPILE_TEST
        # v6.6-rc1-8-g91a69d38cf97 (Fri Oct 13 10:07:17 2023 +0200)
        # https://git.kernel.org/linus/91a69d38cf97b195fef1a10ea53cf429aa134497
        ('PWM_CRC', 'drivers/pwm/Kconfig'),
        # media: make RADIO_ADAPTERS tristate
        # v5.18-rc3-170-g215d49a41709 (Fri May 13 11:02:19 2022 +0200)
        # https://git.kernel.org/linus/215d49a41709610b9e82a49b27269cfaff1ef0b6
        ('RADIO_ADAPTERS', 'drivers/media/radio/Kconfig'),
        # serial: sc16is7xx: split into core and I2C/SPI parts (core)
        # v6.9-rc3-58-gd49216438139 (Thu Apr 11 14:08:08 2024 +0200)
        # https://git.kernel.org/linus/d49216438139bca0454e69b6c4ab8a01af2b72ed
        *[(f"SERIAL_SC16IS7XX_{val}", 'drivers/tty/serial/Kconfig') for val in ('I2C', 'SPI')],
        # ASoC: SOF: Convert the generic probe support to SOF client
        # v5.17-rc1-108-g3dc0d7091778 (Thu Feb 10 15:19:12 2022 +0000)
        # https://git.kernel.org/linus/3dc0d709177828a22dfc9d0072e3ac937ef90d06
        ('SND_SOC_SOF_DEBUG_PROBES', 'sound/soc/sof/Kconfig'),
        # ASoC: amd: acp: Fix linker error with SDCA quirks
        # v7.2-rc2-3-gdbbb5bc5176e (Mon Jul 6 14:41:50 2026 +0100)
        # https://git.kernel.org/linus/dbbb5bc5176e36b13aa22e2174ab4779c5ae1dca
        ('SND_SOC_ACPI_AMD_SDCA_QUIRKS', 'sound/soc/amd/acp/Kconfig'),
        # ASoC: SOF: Kconfig: Make SND_SOC_SOF_HDA_PROBES tristate
        # v5.18-rc1-175-ge18610eaa66a (Tue Apr 19 16:30:31 2022 +0100)
        # https://git.kernel.org/linus/e18610eaa66a1849aaa00ca43d605fb1a6fed800
        ('SND_SOC_SOF_HDA_PROBES', 'sound/soc/sof/intel/Kconfig'),
        # clk: sunxi-ng: Allow the CCU core to be built as a module
        # v5.16-rc1-4-g91389c390521 (Tue Nov 23 10:29:05 2021 +0100)
        # https://git.kernel.org/linus/91389c390521a02ecfb91270f5b9d7fae4312ae5
        ('SUNXI_CCU', 'drivers/clk/sunxi-ng/Kconfig'),
        # clk: sunxi-ng: Allow drivers to be built as modules
        # v5.16-rc1-2-gc8c525b06f53 (Mon Nov 22 10:02:21 2021 +0100)
        # https://git.kernel.org/linus/c8c525b06f532923d21d99811a7b80bf18ffd2be
        ('SUN8I_DE2_CCU', 'drivers/clk/sunxi-ng/Kconfig'),
        # net: ethernet: ti: Remove TI_CPTS_MOD workaround
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
    ]
    for config_sym, locations in compat_changes:
        # Check if the symbol is modular in the current configuration and move on if not
        if not lst.is_config_modular(config, config_sym):
            continue

        if isinstance(locations, str):
            files = (locations,)
        elif isinstance(locations, tuple):
            files = locations
        else:
            msg = 'locations neither a string nor a tuple?'
            raise TypeError(msg)

        can_be_m = False
        for file in files:
            if f"config{config_sym}tristate" in ''.join(lst.read_text(file).split()):
                can_be_m = True
                break

        if not can_be_m:
            configs.append(f"CONFIG_{config_sym}=y")

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
        file_text = ''.join(lst.read_text(file).split())
        val = lst.get_config_val(config, cfg)

        if f"config{cfg}int" in file_text and val == 'n':
            configs.append(f"CONFIG_{cfg}=0")
        if f"config{cfg}bool" in file_text and val == '0':
            configs.append(f"CONFIG_{cfg}=n")

    ubsan_kfg_txt = lst.read_text('lib/Kconfig.ubsan')
    for ubsan_check_cfg in ('UBSAN_INTEGER_WRAP', 'UBSAN_SIGNED_WRAP'):
        if ubsan_check_cfg not in ubsan_kfg_txt:
            continue
        if lst.is_config_set(config, ubsan_check_cfg):
            configs.append(f"CONFIG_{ubsan_check_cfg}=n")
            break

    # clocksource/drivers/arm_global_timer: Add auto-detection for initial prescaler values
    # v6.17-rc1-49-g1c4b87c921fb (Tue Sep 23 12:41:58 2025 +0200)
    # https://git.kernel.org/linus/1c4b87c921fb158d853adcb8fd48c2dc07fc6f91
    if lst.is_config_set(config, 'ARM_GLOBAL_TIMER'):
        file_text = ''.join(lst.read_text('drivers/clocksource/Kconfig').split())
        have_1c4b87c921fb1 = (
            'config ARM_GT_INITIAL_PRESCALER_VALint "ARM global timer initial prescaler value"default 0'
            in file_text
        )
        have_zero_prescalar_val = (
            lst.get_config_val(config, cfg := 'ARM_GT_INITIAL_PRESCALER_VAL') == 0
        )
        if not have_1c4b87c921fb1 and have_zero_prescalar_val:
            configs.append(f"CONFIG_{cfg}=1")

    return configs


def pretty_name_to_make_name(pretty_job_name: str) -> str:
    return pretty_job_name.replace(' ', '_').replace('_+_', '_').replace('""', '').replace('=', '_')


class Executor:
    def __init__(
        self,
        matrices: list[ArchMatrix],
        lst: LinuxSourceTree,
        env_info: EnvInfo,
        boot_utils_folder: Path,
        build_folder: Path,
        output_folder: Path,
        save_objects: bool = False,
        verbose: bool = False,
    ) -> None:
        self.matrices: list[ArchMatrix] = matrices
        self.lst: LinuxSourceTree = lst
        self.env_info: EnvInfo = env_info
        self.boot_utils_folder: Path = boot_utils_folder
        self.build_folder: Path = build_folder
        self.logs_folder: Path = Path(output_folder, 'logs')
        self.make_vars: lkt.utils.MakeVars = {}
        self.results_folder: Path = Path(output_folder, 'results')
        self.save_objects: bool = save_objects
        self.verbose: bool = verbose

        self.duration: str = ''

        makefile_txt = self.lst.folder.joinpath('Makefile').read_text(encoding='utf-8')
        if 'HOSTLDFLAGS += -fuse-ld=lld' not in makefile_txt:
            self.make_vars['HOSTLDFLAGS'] = '-fuse-ld=lld'

        clang_prefix = self.env_info.clang.location.parent
        found_libclang: Path | None = None
        # upstream
        if (libclang := clang_prefix.joinpath('lib/libclang.so')).exists():
            found_libclang = libclang
        # debian
        elif possible_libclangs := list(clang_prefix.glob('lib/libclang-*.so.1')):
            found_libclang = possible_libclangs[0]
        if found_libclang:
            self.make_vars['LIBCLANG_PATH'] = found_libclang.as_posix()

    def _transform_test_into_make(self, job: TestJob) -> MakeJob:
        # base make command to run
        base_make_cmd: list[str] = ['$(MAKE_KERNEL) $(MAKE_VARIABLES)']

        # initial make job information
        make_job_prereqs = ['prepare']
        make_job_variables: dict[str, str] = {}
        make_job_cmds: list[str] = [
            # clean up previous build output if present
            '@rm -fr $(BUILD_OUTPUT)',
            # create results directory
            '@mkdir -p $(RESULTS)/$@',
            # save build name
            "@echo '$(PRETTY_JOB_NAME)' >$(NAME_RESULT)",
        ]

        # delete LLVM_IAS if it is the default
        if job.make_vars['LLVM_IAS'] == '1':
            del job.make_vars['LLVM_IAS']
        # update job make variables with executor wide make variables
        job.make_vars.update(self.make_vars)

        # sift configurations
        base_config: lkt.utils.PathString = job.configs[0]
        requested_fragments: list[str] = []
        requested_options: list[str] = []
        if isinstance(base_config, Path):
            job.configs += initial_distro_prep(self.lst, base_config)
            pretty_configs: list[str] = [
                f"{base_config.parts[-2]} config",
                *list(map(str, job.configs[1:])),
            ]
        else:
            pretty_configs: list[str] = list(map(str, job.configs))
        if base_config == 'allmodconfig':
            requested_options.append('CONFIG_WERROR=n')
        for item in job.configs[1:]:
            if not isinstance(item, str):
                msg = f"{item} is not a string?"
                raise TypeError(msg)
            if item.endswith('.config'):
                requested_fragments.append(item)
            elif item.startswith('CONFIG_'):
                if '=' not in item:
                    msg = f"{item} does not contain '='?"
                    raise ValueError(msg)
                requested_options.append(item)
            else:
                msg = f"Cannot handle {item}?"
                raise ValueError(msg)
        if 'CONFIG_WERROR=n' in requested_options:
            # We do not want to have to maintain these in the callers but it is
            # important to note them in the build logs, so we add them here.
            # We should not add configurations that do not exist in the
            # tree that we are testing.
            requested_options += [
                f"{full_cfg}=n"
                for val in KNOWN_SUBSYS_WERROR_CONFIGS
                if (full_cfg := f"CONFIG_{val}") in self.lst.configs
            ]
        make_job_variables['REQUESTED_CONFIGS'] = ' '.join(requested_options)
        extra_configs = requested_options.copy()
        need_olddefconfig = False

        make_job_variables['PRETTY_JOB_NAME'] = (
            f"{job.make_vars['ARCH']} {' + '.join(pretty_configs)}"
        )
        make_job_name = pretty_name_to_make_name(make_job_variables['PRETTY_JOB_NAME'])
        if job.skip_build_reason:
            make_job_variables['SKIP_BUILD_REASON'] = job.skip_build_reason
            make_job_cmds += [
                # log skip reason into result
                '@echo "skipped due to $(SKIP_BUILD_REASON)" >$(BUILD_RESULT)',
                # show skipped build to user
                '@echo >&2 "Skipping $(PRETTY_JOB_NAME) due to $(SKIP_BUILD_REASON)"',
            ]
            return MakeJob(
                name=make_job_name,
                prereqs=make_job_prereqs,
                cmds=make_job_cmds,
                variables=make_job_variables,
            )

        failed_build_handling = f"; if [ $${{PIPESTATUS[0]}} -ne 0 ]; then echo failed >$(BUILD_RESULT);{' echo skipped >$(BOOT_RESULT);' if job.bootable else ''} exit 1; fi"
        make_job_variables['MAKE_VARIABLES'] = ' '.join(
            f"{var}={job.make_vars[var]}"  # ty: ignore[invalid-key]
            for var in sorted(job.make_vars)
        )
        make_job_cmds.append("@echo >&2 'Building $(PRETTY_JOB_NAME)'")

        if isinstance(base_config, str):
            make_job_variables['INITIAL_MAKE_TARGETS'] = ' '.join(
                [base_config, *requested_fragments]
            )
            if extra_configs:
                # generate .config file for merge_config.sh
                initial_make_cmd_str: str = ' '.join([*base_make_cmd, '$(INITIAL_MAKE_TARGETS)'])
                make_job_cmds += [
                    gen_log_cmd(initial_make_cmd_str),
                    f"+{initial_make_cmd_str} $(LOG_OUTPUT){failed_build_handling}",
                ]
            else:
                base_make_cmd.append('$(INITIAL_MAKE_TARGETS)')
        elif isinstance(base_config, Path):
            if requested_fragments:
                msg = 'config fragments are not supported with out of tree configurations! Add support if this is needed.'
                raise RuntimeError(msg)

            make_job_variables['SRC_CONFIG_FILE'] = str(base_config).replace(
                str(lkt.utils.CONFIGS), '$(CONFIGS)'
            )
            mkdir_cmd = 'mkdir -p $(BUILD_OUTPUT)'
            cp_cmd = 'cp -v $(SRC_CONFIG_FILE) $(CONFIG_FILE)'
            make_job_cmds += [
                gen_log_cmd(mkdir_cmd),
                f"@{mkdir_cmd}",
                gen_log_cmd(cp_cmd),
                f"@{cp_cmd} $(LOG_OUTPUT_SILENT)",
            ]

            extra_configs += distro_adjustments(self.lst, base_config)

            need_olddefconfig = True
        else:
            msg = f"Unsupported base configuration: {base_config}"
            raise TypeError(msg)

        if extra_configs:
            # Certain configuration options are choices and Kconfig warns when
            # choices are overridden. Disable the default choice when a choice
            # is present.
            if 'CONFIG_LTO_CLANG_THIN=y' in extra_configs:
                extra_configs.append('CONFIG_LTO_NONE=n')
            if 'CONFIG_CPU_BIG_ENDIAN=y' in extra_configs:
                extra_configs.append('CONFIG_CPU_LITTLE_ENDIAN=n')
            if 'CONFIG_CPU_LITTLE_ENDIAN=y' in extra_configs:
                extra_configs.append('CONFIG_CPU_BIG_ENDIAN=n')

            make_job_variables['EXTRA_CONFIGS'] = ' '.join(extra_configs)

            # generate .merge.config from extra_configs
            make_job_cmds.append("@printf '%s\\n' $(EXTRA_CONFIGS) >$(MERGE_CONFIG_FILE)")

            # show .merge.config in log for reproduction
            cat_cmd: str = 'cat $(MERGE_CONFIG_FILE)'
            make_job_cmds += [gen_log_cmd(cat_cmd), f"@{cat_cmd} $(LOG_OUTPUT_SILENT)"]

            # run merge_config.sh
            merge_config_cmd: str = (
                '$(MERGE_CONFIG_SH) -m -O $(BUILD_OUTPUT) $(CONFIG_FILE) $(MERGE_CONFIG_FILE)'
            )
            make_job_cmds += [
                gen_log_cmd(merge_config_cmd),
                f"@{merge_config_cmd} $(LOG_OUTPUT_SILENT)",
            ]

            need_olddefconfig = True

        # build kernel and additional targets
        make_targets = job.make_targets.copy() if job.make_targets else ['all']
        if need_olddefconfig:
            make_targets.insert(0, 'olddefconfig')
        if job.extra_make_targets:
            make_targets += job.extra_make_targets
        make_job_variables['FINAL_MAKE_TARGETS'] = ' '.join(make_targets)
        final_make_cmd = ' '.join([*base_make_cmd, '$(FINAL_MAKE_TARGETS)'])
        make_job_cmds += [
            gen_log_cmd(final_make_cmd),
            f"+{final_make_cmd} $(LOG_OUTPUT){failed_build_handling}",
            '@echo successful >$(BUILD_RESULT)',
        ]
        if need_olddefconfig:
            chk_cmd = '$(CHKCFG) $(CONFIG_FILE) $(REQUESTED_CONFIGS)'
            make_job_cmds += [
                gen_log_cmd(chk_cmd),
                f"@{chk_cmd} $(LOG_OUTPUT)",
            ]

        # handle skipped boot if reason is provided
        if job.skip_boot_reason:
            make_job_variables['SKIP_BOOT_REASON'] = job.skip_boot_reason
            make_job_cmds += [
                # log skip reason into result
                "@echo 'skipped due to $(SKIP_BOOT_REASON)' >$(BOOT_RESULT)",
                # show skipped build to user
                "@echo >&2 'Skipping $(PRETTY_JOB_NAME) boot due to $(SKIP_BOOT_REASON)'",
            ]
        # boot kernel if requested
        elif job.bootable:
            make_job_prereqs.append('$(BOOT_UTILS_JSON)')
            make_job_variables['BOOT_UTILS_ARCH'] = job.boot_utils_arch
            if using_kvm(job.boot_utils_arch, self.boot_utils_folder):
                make_job_variables['ADDITIONAL_BOOT_QEMU_ARGS'] = '-m 2G'
            make_job_cmds += [
                "@echo >&2 'Booting $(PRETTY_JOB_NAME)'",
                gen_log_cmd('$(BOOT_KERNEL)'),
                '$(BOOT_KERNEL) $(LOG_OUTPUT_SILENT) || { echo failed >$(BOOT_RESULT); exit 1; }',
                '@echo successful >$(BOOT_RESULT)',
            ]

        if not self.save_objects:
            make_job_cmds.append('@rm -fr $(BUILD_OUTPUT)')

        return MakeJob(
            name=make_job_name,
            prereqs=make_job_prereqs,
            cmds=make_job_cmds,
            variables=make_job_variables,
        )

    def generate_makefile(self) -> Path:
        test_jobs: list[TestJob] = [job for matrix in self.matrices for job in matrix.jobs]
        make_jobs: list[MakeJob] = [self._transform_test_into_make(job) for job in test_jobs]

        if self.build_folder.exists():
            shutil.rmtree(self.build_folder)
        self.build_folder.mkdir(parents=True)

        makefile = self.build_folder.joinpath('Makefile')
        makefile_txt = f"""\
SHELL := /bin/bash

# Folders
BOOT_UTILS := {self.boot_utils_folder}
BUILD := {self.build_folder}
CONFIGS := {lkt.utils.CONFIGS}
LOGS := {self.logs_folder}
RESULTS := {self.results_folder}
SRC := {self.lst.folder}

# Files
BOOT_UTILS_JSON := {self.logs_folder.parent.joinpath('.boot-utils.json')}
CHKCFG := {lkt.utils.CONFIGS.parent.joinpath('scripts/check_olddefconfig.py')}
MERGE_CONFIG_SH := $(SRC)/scripts/kconfig/merge_config.sh

# Recursive macros
BUILD_OUTPUT = $(BUILD)/$@
CONFIG_FILE = $(BUILD_OUTPUT)/.config
MERGE_CONFIG_FILE = $(BUILD_OUTPUT)/.merge.config

BUILD_RESULT = $(RESULTS)/$@/build
BOOT_RESULT = $(RESULTS)/$@/boot
NAME_RESULT = $(RESULTS)/$@/name

LOG_OUTPUT = 2>&1 | tee -a $(LOGS)/$@.log
LOG_OUTPUT_SILENT = 2>&1 >>$(LOGS)/$@.log

MAKE_KERNEL = $(MAKE) -C $(SRC) -s O=$(BUILD_OUTPUT)
BOOT_KERNEL = $(BOOT_UTILS)/boot-qemu.py -a $(BOOT_UTILS_ARCH) --ephemeral-initrd -k $(BUILD_OUTPUT) --gh-json-file $(BOOT_UTILS_JSON) $(ADDITIONAL_BOOT_QEMU_ARGS)

# Rules
.PHONY: all
all: {' '.join(job.name for job in make_jobs)}

.PHONY: prepare
prepare:
\t@rm -fr $(LOGS) $(RESULTS)
\t@mkdir -p $(LOGS) $(RESULTS)

$(BOOT_UTILS_JSON): prepare
\t@curl -LSso $(BOOT_UTILS_JSON) https://api.github.com/repos/ClangBuiltLinux/boot-utils/releases/latest || test -f $(BOOT_UTILS_JSON)

{'\n'.join(str(job) for job in make_jobs)}
"""
        makefile.write_text(makefile_txt, encoding='utf-8')
        return makefile

    def run(self) -> None:
        lkt.utils.header('Running test matrix', end='')

        makefile = self.generate_makefile()
        start = time.time()
        make_cmd = ['make', '-f', makefile, f"-kj{os.cpu_count()}"]
        if not self.verbose:
            make_cmd.append('-s')
        lkt.utils.run(make_cmd, check=False, show_cmd=True)
        self.duration = lkt.utils.get_time_diff(start)
