#!/usr/bin/env python3

import contextlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

import lkt.utils
from lkt.version import ClangVersion

HAVE_DEV_KVM_ACCESS = os.access('/dev/kvm', os.R_OK | os.W_OK)


class Folders:

    def __init__(self):
        self.boot_utils = None
        self.build = None
        self.configs = None
        self.log = None
        self.source = None


class LLVMKernelRunner:

    def __init__(self):
        self.bootable = False
        self.boot_arch = ''
        self.configs = []
        self.folders = Folders()
        self.lsm = None
        self.image_target = ''
        self.make_args = [f"-skj{os.cpu_count()}"]
        self.make_targets = []
        self.make_vars = {
            'HOSTLDFLAGS': '-fuse-ld=lld',
            'LLVM': 1,
            'LLVM_IAS': 1,
            'LOCALVERSION': '-cbl',
        }
        self.only_test_boot = False
        self.override_make_vars = {}
        self.qemu_arch = ''
        self.result = {}

        self._config = None

    def _boot_kernel(self):
        if not self.bootable:
            return
        if self.result['build'] == 'failed':
            self.result['boot'] = 'skipped'
            return
        if not self.boot_arch:
            raise RuntimeError('No boot-utils architecture set?')
        if not self.qemu_arch:
            raise RuntimeError('No QEMU architecture set?')
        if not shutil.which(qemu_bin := f"qemu-system-{self.qemu_arch}"):
            self.result['boot'] = f"skipped due to missing {qemu_bin}"
            return
        if not self.folders.boot_utils.exists():
            raise RuntimeError('boot-utils could not be found?')
        if not (boot_qemu := Path(self.folders.boot_utils, 'boot-qemu.py')).exists():
            raise RuntimeError('boot-qemu.py could not be found?')
        boot_utils_cmd = [
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
                proc = subprocess.run(Path(boot_qemu.parent, 'utils/aarch64_32_bit_el1_supported'),
                                      check=False)
                using_kvm = proc.returncode == 0 and HAVE_DEV_KVM_ACCESS
            else:
                using_kvm = self.boot_arch in ('arm64', 'arm64be') and HAVE_DEV_KVM_ACCESS
        elif machine == 'x86_64':
            using_kvm = self.boot_arch in ('x86', 'x86_64') and HAVE_DEV_KVM_ACCESS
        if using_kvm:
            boot_utils_cmd += ['-m', '2G']
        lkt.utils.show_cmd(boot_utils_cmd)
        sys.stderr.flush()
        sys.stdout.flush()
        with self.result['log'].open('a') as file:
            proc = subprocess.run(boot_utils_cmd,
                                  check=False,
                                  stderr=subprocess.STDOUT,
                                  stdout=subprocess.PIPE,
                                  text=True)
            file.write(proc.stdout)
            if proc.returncode == 0:
                self.result['boot'] = 'successful'
            else:
                self.result['boot'] = 'failed'
                print(proc.stdout, end='')

    def _build_kernel(self):
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
        llvm_ias_def_on = makefile_clang.exists() and \
                          'ifeq ($(LLVM_IAS),0)' in makefile_clang.read_text(encoding='utf-8')
        if (llvm_ias_def_on and llvm_ias == 1) or (not llvm_ias_def_on and llvm_ias == 0):
            del self.make_vars['LLVM_IAS']

        base_make_cmd = [
            'make',
            *self.make_args,
            *[f"{var}={self.make_vars[var]}" for var in sorted(self.make_vars)],
        ]

        ##########################
        # configuration handling #
        ##########################
        base_config = self.configs[0]
        requested_configs = self.configs[1:]
        extra_configs = requested_configs.copy()
        need_olddefconfig = False

        if isinstance(base_config, str):
            if extra_configs:
                # Generate .config for merge_config.sh
                make_cmd = [*base_make_cmd, base_config]
                lkt.utils.show_cmd(make_cmd)
                lkt.utils.chronic(make_cmd)
            else:
                base_make_cmd += [base_config]
        elif isinstance(base_config, Path):
            self.folders.build.mkdir(parents=True)

            lkt.utils.show_cmd(['mv', base_config, self._config])
            shutil.copy(base_config, self._config)
            extra_configs += self._distro_adjustments()

            need_olddefconfig = True

        if extra_configs:
            for config in extra_configs:
                if not config.startswith('CONFIG_'):
                    raise ValueError(f"{config} does not start with 'CONFIG_'?")
                if '=' not in config:
                    raise ValueError(f"{config} does not contain '='?")

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

            Path(config_path).write_text(''.join([f"{config}\n" for config in extra_configs]),
                                         encoding='utf-8')

            merge_config = [
                Path(self.folders.source, 'scripts/kconfig/merge_config.sh'),
                '-m',
                '-O',
                self.folders.build,
                self._config,
                config_path,
            ]
            lkt.utils.show_cmd(merge_config)
            lkt.utils.chronic(merge_config)

            need_olddefconfig = True

        if need_olddefconfig:
            base_make_cmd.append('olddefconfig')
        base_make_cmd.append(self.image_target if self.only_test_boot else 'all')
        base_make_cmd += self.make_targets

        # Actually build kernel
        lkt.utils.show_cmd(base_make_cmd)
        start_time = time.time()
        sys.stderr.flush()
        sys.stdout.flush()
        with subprocess.Popen(
                base_make_cmd, stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE) as proc, self.result['log'].open('bw') as file:
            while (byte := proc.stdout.read(1)):
                sys.stdout.buffer.write(byte)
                sys.stdout.flush()
                file.write(byte)

        # Make sure requested configurations are their expected value
        if need_olddefconfig:
            missing_configs = []

            config_text = self._config.read_text(encoding='utf-8')
            for item in requested_configs:
                cfg_name, cfg_val = item.split('=', 1)
                # 'CONFIG_FOO=n' does not appear in the final config, it is
                # '# CONFIG_FOO is not set'
                search = f"# {cfg_name} is not set" if cfg_val == 'n' else item
                # If we find a match, move on
                if re.search(f"^{search}$", config_text, flags=re.M):
                    continue
                # If we did not find a match for '# CONFIG_FOO is not set', we
                # should only add it to the missing configs list if it is
                # present with some other value because it may not be visible,
                # which means it is 'n'.
                if cfg_val != 'n' or re.search(f"^{cfg_name}=", config_text, flags=re.M):
                    missing_configs.append(item)

            if missing_configs:
                warning_msg = f"\nWARNING: {type(self).__name__}(): Missing requested configurations after olddefconfig: {', '.join(missing_configs)}"
                print(warning_msg)
                with self.result['log'].open('a') as file:
                    file.write(f"{warning_msg}\n")

        self.result['build'] = 'successful' if proc.returncode == 0 else 'failed'
        self.result['duration'] = lkt.utils.get_time_diff(start_time)
        print(f"\nReal\t{self.result['duration']}")

    def _distro_adjustments(self):
        configs = []

        config = self.configs[0]
        distro = config.parts[-2]

        if distro == 'debian':
            # The Android drivers are not modular in upstream
            for android_cfg in ['ANDROID_BINDER_IPC', 'ASHMEM']:
                if lkt.utils.is_modular(self.folders.source, self.folders.build, android_cfg):
                    configs.append(f"CONFIG_{android_cfg}=y")

        if 'ppc64le' in config.name or 'powerpc64le' in config.name:
            text = Path(self.folders.source, 'arch/powerpc/Kconfig').read_text(encoding='utf-8')
            search = ('int "Order of maximal physically contiguous allocations"\n'
                      '\tdefault "8" if PPC64 && PPC_64K_PAGES')
            configs.append(f"CONFIG_ARCH_FORCE_MAX_ORDER={8 if search in text else 9}")

        compat_changes = [
            # CONFIG_BCM7120_L2_IRQ as a module is invalid before https://git.kernel.org/linus/3ac268d5ed2233d4a2db541d8fd744ccc13f46b0
            ('BCM7120_L2_IRQ', 'drivers/irqchip/Kconfig'),
            # CONFIG_CHARGER_MANAGER as a module is invalid before https://git.kernel.org/linus/241eaabc3c315cdfea505725a43de848f498527f
            ('CHARGER_MANAGER', 'drivers/power/supply/Kconfig'),
            # CONFIG_CHELSIO_IPSEC_INLINE as a module is invalid before https://git.kernel.org/linus/1b77be463929e6d3cefbc929f710305714a89723
            ('CHELSIO_IPSEC_INLINE', 'drivers/crypto/chelsio/Kconfig'),
            # CONFIG_COMMON_CLK_MT8173 and CONFIG_COMMON_CLK_MT8173_MMSYS as modules is invalid before https://git.kernel.org/linus/4c02c9af3cb9449cd176300b288e8addb5083934
            *[(f"COMMON_CLK_MT8173{val}", 'drivers/clk/mediatek/Kconfig')
              for val in ['', '_MMSYS']],
            # CONFIG_COMMON_CLK_MT8183 and all its subdrivers as modules is invalid before https://git.kernel.org/linus/95ffe65437b239db3f5a570b31cd79629c851743
            *[(f"COMMON_CLK_MT8183{val}", 'drivers/clk/mediatek/Kconfig') for val in [
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
            ]],
            # CONFIG_CORESIGHT (and all of its drivers) as a module is invalid before https://git.kernel.org/linus/8e264c52e1dab8a7c1e036222ef376c8920c3423
            *[(f"CORESIGHT{val}", 'drivers/hwtracing/coresight/Kconfig') for val in [
                '',
                '_LINKS_AND_SINKS',
                '_LINK_AND_SINK_TMC',
                '_CATU',
                '_SINK_TPIU',
                '_SINK_ETBV10',
                '_SOURCE_ETM3X',
                '_SOURCE_ETM4X',
                '_STM',
            ]],
            # CONFIG_CPUFREQ_DT_PLATDEV as a module is invalid before https://git.kernel.org/linus/3b062a086984d35a3c6d3a1c7841d0aa73aa76af
            ('CPUFREQ_DT_PLATDEV', 'drivers/cpufreq/Kconfig'),
            # CONFIG_CS89x0_PLATFORM as a module is invalid before https://git.kernel.org/linus/47fd22f2b84765a2f7e3f150282497b902624547
            ('CS89x0_PLATFORM', 'drivers/net/ethernet/cirrus/Kconfig'),
            # CONFIG_DRIVER_PE_KUNIT_TEST as a module is invalid before https://git.kernel.org/linus/98ad1dd06a02096fff6c65703a85b9f3c3de1a7d
            ('DRIVER_PE_KUNIT_TEST', 'drivers/base/test/Kconfig'),
            # CONFIG_DRM_GEM_{CMA,SHMEM}_HELPER as modules is invalid before https://git.kernel.org/linus/4b2b5e142ff499a2bef2b8db0272bbda1088a3fe
            *[(f"DRM_GEM_{val}_HELPER", 'drivers/gpu/drm/Kconfig') for val in ['CMA', 'SHMEM']],
            # CONFIG_FSCACHE as a module is invalid after https://git.kernel.org/next/linux-next/c/9896c4f367fcc44213d15fe7210e9305df8063f2
            # While the new configuration location is fs/netfs/Kconfig, we
            # check for whether or not FSCACHE can be a module in
            # fs/fscache/Kconfig; if it does not exist, we know it cannot be
            # 'm' due to the change above.
            ('FSCACHE', 'fs/fscache/Kconfig'),
            # CONFIG_GPIO_DAVINCI as a module is invalid before https://git.kernel.org/linus/8dab99c9eab3162bfb4326c35579a3388dbf68f2
            # CONFIG_GPIO_MXC as a module is invalid before https://git.kernel.org/linus/12d16b397ce0a999d13762c4c0cae2fb82eb60ee
            # CONFIG_GPIO_PL061 as a module is invalid before https://git.kernel.org/linus/616844408de7f21546c3c2a71ea7f8d364f45e0d
            # CONFIG_GPIO_TPS68470 as a module is invalid before https://git.kernel.org/linus/a1ce76e89907a69713f729ff21db1efa00f3bb47
            *[(f"GPIO_{val}", 'drivers/gpio/Kconfig')
              for val in ['DAVINCI', 'MXC', 'PL061', 'TPS68470']],
            # CONFIG_IMX_DSP as a module is invalid before https://git.kernel.org/linus/f52cdcce9197fef9d4a68792dd3b840ad2b77117
            ('IMX_DSP', 'drivers/firmware/imx/Kconfig'),
            # CONFIG_KPROBES_SANITY_TEST as a module is invalid before https://git.kernel.org/linus/e44e81c5b90f698025eadceb7eef8661eda117d5
            ('KPROBES_SANITY_TEST', 'lib/Kconfig.debug'),
            # CONFIG_MFD_PALMAS as a module is invalid before https://git.kernel.org/linus/d4b15e447c352ae74b18261bdaf0023fa9a7d1bd
            ('MFD_PALMAS', 'drivers/mfd/Kconfig'),
            # CONFIG_MTK_IOMMU as a module is invalid before https://git.kernel.org/linus/18d8c74ec5987a78bd1e9c1c629dfdd04a151a89
            ('MTK_IOMMU', 'drivers/iommu/Kconfig'),
            # CONFIG_MTK_MMSYS as a module is invalid before https://git.kernel.org/linus/a7596e62dac7318456c1aa9af5bfccf0f8e6ad7e
            ('MTK_MMSYS', 'drivers/soc/mediatek/Kconfig'),
            # CONFIG_MTK_SMI as a module is invalid before https://git.kernel.org/linus/50fc8d9232cdc64b9e9d1b9488452f153de52b69
            ('MTK_SMI', 'drivers/memory/Kconfig'),
            # CONFIG_NET_DSA_REALTEK_{MDIO,SMI} as modules is invalid after https://git.kernel.org/netdev/net-next/c/98b75c1c149c653ad11a440636213eb070325158
            *[(f"NET_DSA_REALTEK_{val}", 'drivers/net/dsa/realtek/Kconfig')
              for val in ('MDIO', 'SMI')],
            # CONFIG_NVME_AUTH as a module is invalid before https://git.kernel.org/linus/6affe08aea5f3b630565676e227b41d55a6f009c
            ('NVME_AUTH', 'drivers/nvme/common/Kconfig'),
            # CONFIG_NVMEM_ZYNQMP as a module is invalid before https://git.kernel.org/linus/bcd1fe07def0f070eb5f31594620aaee6f81d31a
            ('NVMEM_ZYNQMP', 'drivers/nvmem/Kconfig'),
            # CONFIG_PCI_DRA7XX{,_HOST,_EP} as modules is invalid before https://git.kernel.org/linus/3b868d150efd3c586762cee4410cfc75f46d2a07
            # CONFIG_PCI_EXYNOS as a module is invalid before https://git.kernel.org/linus/778f7c194b1dac351d345ce723f8747026092949
            # CONFIG_PCI_MESON as a module is invalid before https://git.kernel.org/linus/a98d2187efd9e6d554efb50e3ed3a2983d340fe5
            *[(f"PCI_{val}", 'drivers/pci/controller/dwc/Kconfig')
              for val in ['DRA7XX', 'DRA7XX_EP', 'DRA7XX_HOST', 'EXYNOS', 'MESON']],
            # CONFIG_PCI_MVEBU as a module is invalid before https://git.kernel.org/linus/0746ae1be12177ebda0666eefa82583cbaeeefd6
            ('PCI_MVEBU', 'drivers/pci/controller/Kconfig'),
            # CONFIG_PINCTRL_ROCKCHIP as a module is invalid before https://git.kernel.org/linus/be786ac5a6c4bf4ef3e4c569a045d302c1e60fe6
            ('PINCTRL_ROCKCHIP', 'drivers/pinctrl/Kconfig'),
            # CONFIG_POWER_RESET_SC27XX as a module is invalid before https://git.kernel.org/linus/f78c55e3b4806974f7d590b2aab8683232b7bd25
            ('POWER_RESET_SC27XX', 'drivers/power/reset/Kconfig'),
            # CONFIG_PROC_THERMAL_MMIO_RAPL as a module is invalid before https://git.kernel.org/linus/a5923b6c3137b9d4fc2ea1c997f6e4d51ac5d774
            ('PROC_THERMAL_MMIO_RAPL', 'drivers/thermal/intel/int340x_thermal/Kconfig'),
            # CONFIG_PWM_CRC as a module is invalid before https://git.kernel.org/linus/91a69d38cf97b195fef1a10ea53cf429aa134497
            ('PWM_CRC', 'drivers/pwm/Kconfig'),
            # CONFIG_QCOM_IPCC as a module is invalid before https://git.kernel.org/linus/8d7e5908c0bcf8a0abc437385e58e49abab11a93
            ('QCOM_IPCC', 'drivers/mailbox/Kconfig'),
            # CONFIG_QCOM_RPMPD as a module is invalid before https://git.kernel.org/linus/f29808b2fb85a7ff2d4830aa1cb736c8c9b986f4
            # CONFIG_QCOM_RPMHPD as a module is invalid before https://git.kernel.org/linus/d4889ec1fc6ac6321cc1e8b35bb656f970926a09
            *[(f"QCOM_RPM{val}PD", 'drivers/soc/qcom/Kconfig') for val in ['', 'H']],
            # CONFIG_RADIO_ADAPTERS as a module is invalid before https://git.kernel.org/linus/215d49a41709610b9e82a49b27269cfaff1ef0b6
            ('RADIO_ADAPTERS', 'drivers/media/radio/Kconfig'),
            # CONFIG_RATIONAL as a module is invalid before https://git.kernel.org/linus/bcda5fd34417c89f653cc0912cc0608b36ea032c
            ('RATIONAL', 'lib/math/Kconfig'),
            # CONFIG_RESET_IMX7 as a module is invalid before https://git.kernel.org/linus/a442abbbe186e14128d18bc3e42fb0fbf1a62210
            # CONFIG_RESET_MESON as a module is invalid before https://git.kernel.org/linus/3bfe8933f9d187f93f0d0910b741a59070f58c4c
            *[(f"RESET_{val}", 'drivers/reset/Kconfig') for val in ['IMX7', 'MESON']],
            # CONFIG_RTW88_8822BE as a module is invalid before https://git.kernel.org/linus/416e87fcc780cae8d72cb9370fa0f46007faa69a
            # CONFIG_RTW88_8822CE as a module is invalid before https://git.kernel.org/linus/ba0fbe236fb8a7b992e82d6eafb03a600f5eba43
            *[(f"RTW88_8822{val}E", 'drivers/net/wireless/realtek/rtw88/Kconfig')
              for val in ['B', 'C']],
            # CONFIG_SERIAL_LANTIQ as a module is invalid before https://git.kernel.org/linus/ad406341bdd7d22ba9497931c2df5dde6bb9440e
            ('SERIAL_LANTIQ', 'drivers/tty/serial/Kconfig'),
            # CONFIG_SND_SOC_SOF_DEBUG_PROBES as a module is invalid before https://git.kernel.org/linus/3dc0d709177828a22dfc9d0072e3ac937ef90d06
            ('SND_SOC_SOF_DEBUG_PROBES', 'sound/soc/sof/Kconfig'),
            # CONFIG_SND_SOC_SOF_HDA_PROBES as a module is invalid before https://git.kernel.org/linus/e18610eaa66a1849aaa00ca43d605fb1a6fed800
            ('SND_SOC_SOF_HDA_PROBES', 'sound/soc/sof/intel/Kconfig'),
            # CONFIG_SND_SOC_SPRD_MCDT as a module is invalid before https://git.kernel.org/linus/fd357ec595d36676c239d8d16706a270a961ac32
            ('SND_SOC_SPRD_MCDT', 'sound/soc/sprd/Kconfig'),
            # CONFIG_SUNXI_CCU as a module is invalid before https://git.kernel.org/linus/91389c390521a02ecfb91270f5b9d7fae4312ae5
            ('SUNXI_CCU', 'drivers/clk/sunxi-ng/Kconfig'),
            # CONFIG_SUN8I_DE2_CCU as a module is invalid before https://git.kernel.org/linus/c8c525b06f532923d21d99811a7b80bf18ffd2be
            ('SUN8I_DE2_CCU', 'drivers/clk/sunxi-ng/Kconfig'),
            # CONFIG_SYSCTL_KUNIT_TEST as a module is invalid before https://git.kernel.org/linus/c475c77d5b56398303e726969e81208196b3aab3
            ('SYSCTL_KUNIT_TEST', 'lib/Kconfig.debug'),
            # CONFIG_TEGRA124_EMC as a module is invalid before https://git.kernel.org/linus/281462e593483350d8072a118c6e072c550a80fa
            # CONFIG_TEGRA20_EMC as a module is invalid before https://git.kernel.org/linus/0260979b018faaf90ff5a7bb04ac3f38e9dee6e3
            # CONFIG_TEGRA30_EMC as a module is invalid before https://git.kernel.org/linus/0c56eda86f8cad705d7d14e81e0e4efaeeaf4613
            *[(f"TEGRA{ver}_EMC", 'drivers/memory/tegra/Kconfig') for ver in ['124', '20', '30']],
            # CONFIG_TI_CPTS as a module is invalid before https://git.kernel.org/linus/92db978f0d686468e527d49268e7c7e8d97d334b
            ('TI_CPTS', 'drivers/net/ethernet/ti/Kconfig'),
            # CONFIG_TI_K3_UDMA and CONFIG_TI_K3_UDMA_GLUE_LAYER as modules is invalid before https://git.kernel.org/linus/56b0a668cb35c5f04ef98ffc22b297f116fe7108
            *[(f"TI_K3_UDMA{suffix}", 'drivers/dma/ti/Kconfig') for suffix in ['', '_GLUE_LAYER']],
            # CONFIG_UNICODE as a module is invalid before https://git.kernel.org/linus/5298d4bfe80f6ae6ae2777bcd1357b0022d98573
            ('UNICODE', 'fs/unicode/Kconfig'),
            # CONFIG_VFIO_VIRQFD as a module is invalid after https://git.kernel.org/next/linux-next/c/e2d55709398e62cf53e5c7df3758ae52cc62d63a
            ('VFIO_VIRQFD', 'drivers/vfio/Kconfig'),
            # CONFIG_VIRTIO_IOMMU as a module is invalid before https://git.kernel.org/linus/fa4afd78ea12cf31113f8b146b696c500d6a9dc3
            ('VIRTIO_IOMMU', 'drivers/iommu/Kconfig'),
            # CONFIG_XEN_PVCALLS_BACKEND as a module is invalid before https://git.kernel.org/linus/45da234467f381239d87536c86597149f189d375
            ('XEN_PVCALLS_BACKEND', 'drivers/xen/Kconfig'),
        ]
        for config_sym, file in compat_changes:
            sym_is_m = lkt.utils.is_modular(self.folders.source, self.folders.build, config_sym)
            can_be_m = False
            if (kconfig_file := Path(self.folders.source, file)).exists():
                kconfig_text = ''.join(kconfig_file.read_text(encoding='utf-8').split())
                if f"config{config_sym}tristate" in kconfig_text:
                    can_be_m = True
            if sym_is_m and not can_be_m:
                configs.append(f"CONFIG_{config_sym}=y")
                if config_sym == 'CS89x0_PLATFORM':
                    configs.append('CONFIG_CS89x0=y')

        # CONFIG_MFD_ARIZONA as a module is invalid before https://git.kernel.org/linus/33d550701b915938bd35ca323ee479e52029adf2
        # Done manually because 'tristate'/'bool' is not right after 'config MFD_ARIZONA'...
        mfd_arizona_is_m = lkt.utils.is_modular(self.folders.source, self.folders.build,
                                                'MFD_ARIZONA')
        file_text = Path(self.folders.source, 'drivers/mfd/Makefile').read_text(encoding='utf-8')
        if mfd_arizona_is_m and 'arizona-objs' not in file_text:
            configs.append('CONFIG_MFD_ARIZONA=y')

        # Handle type of CONFIG_BASE_SMALL changing: https://lore.kernel.org/20240505080343.1471198-1-yoann.congal@smile.fr/
        file_text = ''.join(
            Path(self.folders.source, 'init/Kconfig').read_text(encoding='utf-8').split())
        base_small_val = lkt.utils.get_config_val(self.folders.source, self.folders.build,
                                                  'BASE_SMALL')
        if 'configBASE_SMALLint' in file_text and base_small_val == 'n':
            configs.append('CONFIG_BASE_SMALL=0')
        if 'configBASE_SMALLbool' in file_text and base_small_val == '0':
            configs.append('CONFIG_BASE_SMALL=n')

        return configs

    def _initial_distro_prep(self):
        config = self.configs[0]
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

        if 'e96f2d64c812d' not in self.lsm.commits and 'CONFIG_BPF_PRELOAD' in self.lsm.configs and lkt.utils.is_set(
                self.folders.source, config, 'BPF_PRELOAD'):
            self.configs.append('CONFIG_BPF_PRELOAD=n')

        if distro == 'archlinux' and lkt.utils.is_set(self.folders.source, config,
                                                      'EXTRA_FIRMWARE'):
            self.configs.append('CONFIG_EXTRA_FIRMWARE=""')

        if distro == 'debian' and lkt.utils.is_set(self.folders.source, config,
                                                   'SYSTEM_TRUSTED_KEYS'):
            self.configs.append('CONFIG_SYSTEM_TRUSTED_KEYS=n')

        # Nothing is explicitly wrong with this configuration option but
        # CONFIG_EFI_ZBOOT changes the default image target, which boot-utils
        # does not expect, so undo it to get the expected image for boot
        # testing.
        if config.stem in ('aarch64', 'arm64') and lkt.utils.is_set(self.folders.source, config,
                                                                    'EFI_ZBOOT'):
            self.configs.append('CONFIG_EFI_ZBOOT=n')

    def run(self):
        if not self.folders.source:
            raise RuntimeError('No source location set?')
        if not self.folders.build:
            raise RuntimeError('No build folder set?')
        if not self.configs:
            raise RuntimeError('No configuration to build?')
        if not self.lsm:
            raise RuntimeError('No source manager set?')

        self._config = Path(self.folders.build, '.config')

        # Handle distribution configurations that need to disable
        # configurations to build properly, as those configuration
        # changes should be visible in the log.
        if isinstance(self.configs[0], Path):
            configs = [f"{self.configs[0].parts[-2]} config"]
            self._initial_distro_prep()
            if len(self.configs) > 1:
                configs += self.configs[1:]
        else:
            configs = self.configs
        self.result['name'] = f"{self.make_vars['ARCH']} {' + '.join(configs)}"
        print(f"\nBuilding {self.result['name']}...")

        self.folders.log.mkdir(exist_ok=True, parents=True)
        log_name = self.result['name'].replace(' ', '-').replace('-+-', '-').replace('""', '')
        self.result['log'] = Path(self.folders.log, f"{log_name[0:251]}.log")

        self._build_kernel()
        self._boot_kernel()

        return self.result


class LKTRunner:

    def __init__(self, arch, clang_target):
        self.folders = Folders()
        self.lsm = None
        self.make_vars = {'ARCH': arch}
        self.only_test_boot = False
        self.targets = []
        self.save_objects = False

        self._llvm_version = ClangVersion()

        self._clang_target = clang_target
        self._results = []
        self._runners = []

    def _skip_all(self, log_reason, print_reason):
        result = {
            'name': f"{self.make_vars['ARCH']} kernels",
            'build': 'skipped',
            'reason': log_reason,
        }
        self._results = [result]

        lkt.utils.header(f"Skipping {result['name']}")
        print(f"Reason: {print_reason}")

        return self._results

    def _skip_one(self, name, reason):
        result = {
            'name': name,
            'build': 'skipped',
            'reason': reason,
        }
        self._results.append(result)
        print(f"Skipping {name} due to {reason}")

    def run(self):
        if not lkt.utils.clang_supports_target(self._clang_target):
            return self._skip_all('missing clang target',
                                  f"Missing {self._clang_target} target in clang")

        if 'CROSS_COMPILE' in self.make_vars and \
           self.make_vars.get('LLVM_IAS', 1) == 0 and \
            not shutil.which(f"{self.make_vars['CROSS_COMPILE']}as"):
            return self._skip_all('missing binutils', 'Cannot find binutils')

        lkt.utils.header(f"Building {self.make_vars['ARCH']} kernels", end='')

        self.folders.build = Path(self.folders.build, self.make_vars['ARCH'])

        for runner in self._runners:
            runner.folders = self.folders
            if not runner.lsm and self.lsm:
                runner.lsm = self.lsm
            runner.make_vars.update(self.make_vars)
            self._results.append(runner.run())

        if not self.save_objects:
            shutil.rmtree(self.folders.build)

        return self._results
