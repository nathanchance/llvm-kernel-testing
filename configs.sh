#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function configs_sh_shellcheck() {
    die "This function should never be called."
    linux_src=
    lnx_ver_code=
    root=
    echo "$nft_log_comment"
}

# Use config script in kernel source to enable/disable options
function scripts_config() {
    case "$*" in
        *"-s "*) ;;
        *) set -x ;;
    esac
    "$linux_src"/scripts/config --file "${out:?}"/.config "$@"
    set +x
}

function merge_config() {
    case "$*" in
        *"-s "*) ;;
        *) set -x ;;
    esac
    "$linux_src"/scripts/kconfig/merge_config.sh -m -O "${out:?}" "$out"/.config "$@"
    set +x
}

function handle_bpf_configs() {
    # CONFIG_DEBUG_INFO_BTF has two conditions:
    #
    #   * pahole needs to be available
    #
    #   * The kernel needs https://git.kernel.org/linus/90ceddcb495008ac8ba7a3dce297841efcd7d584,
    #     which is first available in 5.7: https://github.com/ClangBuiltLinux/linux/issues/871
    #
    # If either of those conditions are false, we need to disable this config so
    # that the build does not error.
    if [[ "$(scripts_config -s DEBUG_INFO_BTF)" = "y" ]] &&
        ! (command -v pahole &>/dev/null && [[ $lnx_ver_code -ge 507000 ]]); then
        disabled_configs+=(DEBUG_INFO_BTF)
        scripts_config -d DEBUG_INFO_BTF
    fi

    # https://lore.kernel.org/bpf/20201119085022.3606135-1-davidgow@google.com/
    if [[ "$(scripts_config -s BPF_PRELOAD)" = "y" ]]; then
        disabled_configs+=(BPF_PRELOAD)
        scripts_config -d BPF_PRELOAD
    fi
}

# Set up an out of tree config
function setup_config() {
    # Cleanup the previous artifacts
    rm -rf "${out:?}"
    mkdir -p "$out"

    # Grab the config we are testing
    cp -v "$root"/configs/"${1:?}" "$out"/.config

    disabled_configs=()

    handle_bpf_configs

    # Some distro configs have options that are specific to their distro,
    # which will break in a generic environment
    case $1 in
        debian/*)
            # We are building upstream kernels, which do not have Debian's
            # signing keys in their source
            disabled_configs+=(SYSTEM_TRUSTED_KEYS)
            scripts_config -d SYSTEM_TRUSTED_KEYS

            # The Android drivers are not modular in upstream
            [[ "$(scripts_config -s ANDROID_BINDER_IPC)" = "m" ]] && scripts_config -e ANDROID_BINDER_IPC
            [[ "$(scripts_config -s ASHMEM)" = "m" ]] && scripts_config -e ASHMEM
            ;;

        archlinux/*)
            if [[ -n "$(scripts_config -s CONFIG_EXTRA_FIRMWARE)" ]]; then
                disabled_configs+=(EXTRA_FIRMWARE)
                scripts_config -u EXTRA_FIRMWARE
            fi
            ;;
    esac

    # Make sure that certain configuration options do not get disabled across kernel versions
    # This would not be necessary if we had an individual config for each kernel version
    # that we support but that is a lot more effort.
    scripts_config_args=()

    # CONFIG_BCM7120_L2_IRQ as a module is invalid before https://git.kernel.org/linus/3ac268d5ed2233d4a2db541d8fd744ccc13f46b0
    if [[ "$(scripts_config -s BCM7120_L2_IRQ)" = "m" ]] &&
        ! grep -q 'tristate "Broadcom STB 7120-style L2 interrupt controller driver"' "$linux_src"/drivers/irqchip/Kconfig; then
        scripts_config_args+=(-e BCM7120_L2_IRQ)
    fi

    # CONFIG_CHELSIO_IPSEC_INLINE as a module is invalid before https://git.kernel.org/linus/1b77be463929e6d3cefbc929f710305714a89723
    if [[ "$(scripts_config -s CHELSIO_IPSEC_INLINE)" = "m" ]] &&
        grep -q 'bool "Chelsio IPSec XFRM Tx crypto offload"' "$linux_src"/drivers/crypto/chelsio/Kconfig; then
        scripts_config_args+=(-e CHELSIO_IPSEC_INLINE)
    fi

    # CONFIG_CLK_RK3399 and CONFIG_CLK_RK3568 as modules is invalid after 9af0cbeb477cf36327eec4246a60c5e981b2bd1a
    for num in 3399 3568; do
        kconfig=CLK_RK$num
        kconfig_text="bool \"Rockchip RK$num clock controller support\""
        if [[ "$(scripts_config -s $kconfig)" = "m" ]] &&
            grep -q "$kconfig_text" "$linux_src"/drivers/clk/rockchip/Kconfig; then
            scripts_config_args+=(-e "$kconfig")
        fi
    done

    # CONFIG_CORESIGHT (and all of its drivers) as a module is invalid before https://git.kernel.org/linus/8e264c52e1dab8a7c1e036222ef376c8920c3423
    if [[ "$(scripts_config -s CORESIGHT)" = "m" ]] &&
        grep -q 'bool "CoreSight Tracing Support"' "$linux_src"/drivers/hwtracing/coresight/Kconfig; then
        scripts_config_args+=(-e CORESIGHT)
        for CORESIGHT_CONFIG in LINKS_AND_SINKS LINK_AND_SINK_TMC CATU SINK_TPIU SINK_ETBV10 SOURCE_ETM4X STM; do
            [[ "$(scripts_config -s CORESIGHT_${CORESIGHT_CONFIG})" = "m" ]] && scripts_config_args+=(-e CORESIGHT_"${CORESIGHT_CONFIG}")
        done
    fi

    # CONFIG_CRYPTO_ARCH_HAVE_LIB_BLAKE2S and CONFIG_CRYPTO_LIB_BLAKE2S_GENERIC as modules is invalid after https://git.kernel.org/linus/6048fdcc5f269c7f31d774c295ce59081b36e6f9
    if grep -oPqz '(?s)config CRYPTO_ARCH_HAVE_LIB_BLAKE2S.*?bool' "$linux_src"/lib/crypto/Kconfig 2>/dev/null; then
        for config in CRYPTO_ARCH_HAVE_LIB_BLAKE2S CRYPTO_LIB_BLAKE2S_GENERIC; do
            # These are not user selectable symbols; unset them and let Kconfig set them as necessary
            [[ "$(scripts_config -s $config)" = "m" ]] && scripts_config_args+=(-u "$config")
        done
    fi

    # CONFIG_CS89x0_PLATFORM as a module is invalid before https://git.kernel.org/linus/47fd22f2b84765a2f7e3f150282497b902624547
    if [[ "$(scripts_config -k -s CS89x0_PLATFORM)" = "m" ]] &&
        grep -q 'bool "CS89x0 platform driver support"' "$linux_src"/drivers/net/ethernet/cirrus/Kconfig; then
        scripts_config_args+=(-e CS89x0 -e CS89x0_PLATFORM)
    fi

    # CONFIG_DRM_GEM_{CMA,SHMEM}_HELPER as modules is invalid before https://git.kernel.org/linus/4b2b5e142ff499a2bef2b8db0272bbda1088a3fe
    if grep -oPqz '(?s)config DRM_GEM_CMA_HELPER.*?bool' "$linux_src"/drivers/gpu/drm/Kconfig; then
        for config in CONFIG_DRM_GEM_{CMA,SHMEM}_HELPER; do
            # These are not user selectable symbols; unset them and let Kconfig set them as necessary
            [[ "$(scripts_config -s $config)" = "m" ]] && scripts_config_args+=(-u "$config")
        done
    fi

    # CONFIG_FB_SIMPLE as a module is invalid before https://git.kernel.org/linus/ec7cc3f74b4236860ce612656aa5be7936d1c594
    if [[ "$(scripts_config -s FB_SIMPLE)" = "m" ]] &&
        grep -q 'bool "Simple framebuffer support"' "$linux_src"/drivers/video/fbdev/Kconfig; then
        scripts_config_args+=(-e FB_SIMPLE)
    fi

    # CONFIG_GPIO_MXC as a module is invalid before https://git.kernel.org/linus/12d16b397ce0a999d13762c4c0cae2fb82eb60ee
    if [[ "$(scripts_config -s GPIO_MXC)" = "m" ]] &&
        ! grep -q 'tristate "i.MX GPIO support"' "$linux_src"/drivers/gpio/Kconfig; then
        scripts_config_args+=(-e GPIO_MXC)
    fi

    # CONFIG_GPIO_TPS68470 as a module is invalid before https://git.kernel.org/linus/a1ce76e89907a69713f729ff21db1efa00f3bb47
    if [[ "$(scripts_config -s GPIO_TPS68470)" = "m" ]] &&
        grep -q 'bool "TPS68470 GPIO"' "$linux_src"/drivers/gpio/Kconfig; then
        scripts_config_args+=(-e GPIO_TPS68470)
    fi

    # CONFIG_GPIO_PL061 as a module is invalid before https://git.kernel.org/linus/616844408de7f21546c3c2a71ea7f8d364f45e0d
    if [[ "$(scripts_config -s GPIO_PL061)" = "m" ]] &&
        grep -q 'bool "PrimeCell PL061 GPIO support"' "$linux_src"/drivers/gpio/Kconfig; then
        scripts_config_args+=(-e GPIO_PL061)
    fi

    # CONFIG_I8K as a module is invalid after https://git.kernel.org/linus/9a78ed9a6ed2c3666ac6a4157635f635be62eed2
    if [[ "$(scripts_config -s I8K)" = "m" ]] &&
        grep -q "config I8K" "$linux_src"/drivers/hwmon/Kconfig; then
        scripts_config_args+=(-e I8K)
    fi

    # CONFIG_IMX_DSP as a module is invalid before https://git.kernel.org/linus/f52cdcce9197fef9d4a68792dd3b840ad2b77117
    if [[ "$(scripts_config -s IMX_DSP)" = "m" ]] &&
        grep -q 'bool "IMX DSP Protocol driver"' "$linux_src"/drivers/firmware/imx/Kconfig; then
        scripts_config_args+=(-e IMX_DSP)
    fi

    # CONFIG_INTERCONNECT as a module is invalid after https://git.kernel.org/linus/fcb57bfcb87f3bdb1b29fea1a1cd72940fa559fd
    if [[ "$(scripts_config -s INTERCONNECT)" = "m" ]] &&
        grep -q 'bool "On-Chip Interconnect management support"' "$linux_src"/drivers/interconnect/Kconfig; then
        scripts_config_args+=(-e INTERCONNECT)
    fi

    # CONFIG_KASAN_STACK=1 is invalid after https://git.kernel.org/next/linux-next/c/031734e881750d622a4bbc0011b45361c779dd8c
    if [[ "$(scripts_config -s KASAN_STACK)" = "1" ]] &&
        ! grep -q "config KASAN_STACK_ENABLE" "$linux_src"/lib/Kconfig.kasan; then
        scripts_config_args+=(--set-val KASAN_STACK y)
    fi

    # CONFIG_MFD_ARIZONA as a module is invalid before https://git.kernel.org/linus/33d550701b915938bd35ca323ee479e52029adf2
    if [[ "$(scripts_config -s MFD_ARIZONA)" = "m" ]] &&
        ! grep -q 'arizona-objs' "$linux_src"/drivers/mfd/Makefile; then
        scripts_config_args+=(-e MFD_ARIZONA)
    fi

    # CONFIG_MTD_NAND_ECC_SW_HAMMING as a module is invalid after https://git.kernel.org/next/linux-next/c/5c859c18150b57d47dc684cab6e12b99f5d14ad3
    if [[ "$(scripts_config -s MTD_NAND_ECC_SW_HAMMING)" = "m" ]] &&
        grep -q 'bool "Software Hamming ECC engine"' "$linux_src"/drivers/mtd/nand/Kconfig; then
        scripts_config_args+=(-e MTD_NAND_ECC_SW_HAMMING)
    fi

    # CONFIG_PCI_DRA7XX{,_HOST,_EP} as modules is invalid before https://git.kernel.org/linus/3b868d150efd3c586762cee4410cfc75f46d2a07
    if grep -q 'bool "TI DRA7xx PCIe controller Host Mode"' "$linux_src"/drivers/pci/controller/dwc/Kconfig; then
        for config in PCI_DRA7XX{,_HOST,_EP}; do
            [[ "$(scripts_config -s "$config")" = "m" ]] && scripts_config_args+=(-e "$config")
        done
    fi

    # CONFIG_PCI_EXYNOS as a module is invalid before https://git.kernel.org/linus/778f7c194b1dac351d345ce723f8747026092949
    if [[ "$(scripts_config -s PCI_EXYNOS)" = "m" ]] &&
        grep -q 'bool "Samsung Exynos PCIe controller"' "$linux_src"/drivers/pci/controller/dwc/Kconfig; then
        scripts_config_args+=(-e PCI_EXYNOS)
    fi

    # CONFIG_PCI_MESON as a module is invalid before https://git.kernel.org/linus/a98d2187efd9e6d554efb50e3ed3a2983d340fe5
    if [[ "$(scripts_config -s PCI_MESON)" = "m" ]] &&
        grep -q 'bool "MESON PCIe controller"' "$linux_src"/drivers/pci/controller/dwc/Kconfig; then
        scripts_config_args+=(-e PCI_MESON)
    fi

    # CONFIG_PINCTRL_MSM as a module is invalid before https://git.kernel.org/linus/38e86f5c2645f3c16f698fa7e66b4eb23da5369c
    if [[ "$(scripts_config -s PINCTRL_MSM)" = "m" ]] &&
        grep -oPqz '(?s)config PINCTRL_MSM.*?bool' "$linux_src"/drivers/pinctrl/qcom/Kconfig; then
        scripts_config_args+=(-e PINCTRL_MSM)
    fi

    # CONFIG_POWER_RESET_SC27XX as a module is invalid before https://git.kernel.org/linus/f78c55e3b4806974f7d590b2aab8683232b7bd25
    if [[ "$(scripts_config -s POWER_RESET_SC27XX)" = "m" ]] &&
        grep -q 'bool "Spreadtrum SC27xx PMIC power-off driver"' "$linux_src"/drivers/power/reset/Kconfig; then
        scripts_config_args+=(-e POWER_RESET_SC27XX)
    fi

    # CONFIG_PROC_THERMAL_MMIO_RAPL as a module is invalid before https://git.kernel.org/linus/a5923b6c3137b9d4fc2ea1c997f6e4d51ac5d774
    if [[ "$(scripts_config -s PROC_THERMAL_MMIO_RAPL)" = "m" ]] &&
        grep -oPqz '(?s)config PROC_THERMAL_MMIO_RAPL.*?bool' "$linux_src"/drivers/thermal/intel/int340x_thermal/Kconfig; then
        scripts_config_args+=(-e PROC_THERMAL_MMIO_RAPL)
    fi

    # CONFIG_PVPANIC as a module is invalid after https://git.kernel.org/gregkh/char-misc/c/6861d27cf590d20a95b5d0724ac3768583b62947
    if [[ "$(scripts_config -s PVPANIC)" = "m" && -f $linux_src/drivers/misc/pvpanic/Kconfig ]]; then
        scripts_config_args+=(-e PVPANIC -m PVPANIC_MMIO)
    fi

    # CONFIG_MCTP as a module is invalid after https://git.kernel.org/linus/78476d315e190533757ab894255c4f2c2f254bce
    if [[ "$(scripts_config -s MCTP)" = "m" ]] &&
        grep -q 'bool "MCTP core protocol support"' "$linux_src"/net/mctp/Kconfig; then
        scripts_config_args+=(-e MCTP)
    fi

    # CONFIG_QCOM_RPMPD as a module is invalid before https://git.kernel.org/linus/f29808b2fb85a7ff2d4830aa1cb736c8c9b986f4
    if [[ "$(scripts_config -s QCOM_RPMPD)" = "m" ]] &&
        grep -q 'bool "Qualcomm RPM Power domain driver"' "$linux_src"/drivers/soc/qcom/Kconfig; then
        scripts_config_args+=(-e QCOM_RPMPD)
    fi

    # CONFIG_QCOM_RPMHPD as a module is invalid before https://git.kernel.org/linus/d4889ec1fc6ac6321cc1e8b35bb656f970926a09
    if [[ "$(scripts_config -s QCOM_RPMHPD)" = "m" ]] &&
        grep -q 'bool "Qualcomm RPMh Power domain driver"' "$linux_src"/drivers/soc/qcom/Kconfig; then
        scripts_config_args+=(-e QCOM_RPMHPD)
    fi

    # CONFIG_RADIO_ADAPTERS as a module is invalid before https://git.kernel.org/linus/215d49a41709610b9e82a49b27269cfaff1ef0b6
    if [[ "$(scripts_config -s RADIO_ADAPTERS)" = "m" ]] &&
        grep -q 'bool "Radio Adapters"' "$linux_src"/drivers/media/radio/Kconfig; then
        scripts_config_args+=(-e RADIO_ADAPTERS)
    fi

    # CONFIG_RATIONAL as a module is invalid before https://git.kernel.org/linus/bcda5fd34417c89f653cc0912cc0608b36ea032c
    if [[ "$(scripts_config -s RATIONAL)" = "m" ]] &&
        grep -oPqz '(?s)config RATIONAL.*?bool' "$linux_src"/lib/math/Kconfig; then
        scripts_config_args+=(-e RATIONAL)
    fi

    # CONFIG_RESET_IMX7 as a module is invalid before https://git.kernel.org/linus/a442abbbe186e14128d18bc3e42fb0fbf1a62210
    if [[ "$(scripts_config -s RESET_IMX7)" = "m" ]] &&
        grep -q 'bool "i.MX7/8 Reset Driver"' "$linux_src"/drivers/reset/Kconfig; then
        scripts_config_args+=(-e RESET_IMX7)
    fi

    # CONFIG_RESET_MESON as a module is invalid before https://git.kernel.org/linus/3bfe8933f9d187f93f0d0910b741a59070f58c4c
    if [[ "$(scripts_config -s RESET_MESON)" = "m" ]] &&
        grep -q 'bool "Meson Reset Driver" if COMPILE_TEST' "$linux_src"/drivers/reset/Kconfig; then
        scripts_config_args+=(-e RESET_MESON)
    fi

    # CONFIG_RTW88_8822BE as a module is invalid before https://git.kernel.org/linus/416e87fcc780cae8d72cb9370fa0f46007faa69a
    if [[ "$(scripts_config -s RTW88_8822BE)" = "m" ]] &&
        grep -q 'bool "Realtek 8822BE PCI wireless network adapter"' "$linux_src"/drivers/net/wireless/realtek/rtw88/Kconfig; then
        scripts_config_args+=(-e RTW88_8822BE)
    fi

    # CONFIG_RTW88_8822CE as a module is invalid before https://git.kernel.org/linus/ba0fbe236fb8a7b992e82d6eafb03a600f5eba43
    if [[ "$(scripts_config -s RTW88_8822CE)" = "m" ]] &&
        grep -q 'bool "Realtek 8822CE PCI wireless network adapter"' "$linux_src"/drivers/net/wireless/realtek/rtw88/Kconfig; then
        scripts_config_args+=(-e RTW88_8822CE)
    fi

    # CONFIG_SERIAL_LANTIQ as a module is invalid before https://git.kernel.org/linus/ad406341bdd7d22ba9497931c2df5dde6bb9440e
    if [[ "$(scripts_config -s SERIAL_LANTIQ)" = "m" ]] &&
        grep -q 'bool "Lantiq serial driver"' "$linux_src"/drivers/tty/serial/Kconfig; then
        scripts_config_args+=(-e SERIAL_LANTIQ)
    fi

    # CONFIG_SND_SOC_SOF_DEBUG_PROBES as a module is invalid before https://git.kernel.org/linus/3dc0d709177828a22dfc9d0072e3ac937ef90d06
    if [[ "$(scripts_config -s SND_SOC_SOF_DEBUG_PROBES)" = "m" ]] &&
        grep -q 'bool "SOF enable data probing"' "$linux_src"/sound/soc/sof/Kconfig; then
        scripts_config_args+=(-e SND_SOC_SOF_DEBUG_PROBES)
    fi

    # CONFIG_SND_SOC_SPRD_MCDT as a module is invalid before https://git.kernel.org/linus/fd357ec595d36676c239d8d16706a270a961ac32
    if [[ "$(scripts_config -s SND_SOC_SPRD_MCDT)" = "m" ]] &&
        grep -q 'bool "Spreadtrum multi-channel data transfer support"' "$linux_src"/sound/soc/sprd/Kconfig; then
        scripts_config_args+=(-e SND_SOC_SPRD_MCDT)
    fi

    # CONFIG_SYSCTL_KUNIT_TEST as a module is invalid before https://git.kernel.org/linus/c475c77d5b56398303e726969e81208196b3aab3
    if [[ "$(scripts_config -s SYSCTL_KUNIT_TEST)" = "m" ]] &&
        grep -q 'bool "KUnit test for sysctl"' "$linux_src"/lib/Kconfig.debug; then
        scripts_config_args+=(-e SYSCTL_KUNIT_TEST)
    fi

    # CONFIG_TEGRA124_EMC as a module is invalid before https://git.kernel.org/linus/281462e593483350d8072a118c6e072c550a80fa
    if [[ "$(scripts_config -s TEGRA124_EMC)" = "m" ]] &&
        grep -q 'bool "NVIDIA Tegra124 External Memory Controller driver"' "$linux_src"/drivers/memory/tegra/Kconfig; then
        scripts_config_args+=(-e TEGRA124_EMC)
    fi

    # CONFIG_TEGRA20_APB_DMA as a module is invalid before https://git.kernel.org/linus/703b70f4dc3d22b4ab587e0ca424b974a4489db4
    if [[ "$(scripts_config -s TEGRA20_APB_DMA)" = "m" ]] &&
        grep -q 'bool "NVIDIA Tegra20 APB DMA support"' "$linux_src"/drivers/dma/Kconfig; then
        scripts_config_args+=(-e TEGRA20_APB_DMA)
    fi

    # CONFIG_TEGRA20_EMC as a module is invalid before https://git.kernel.org/linus/0260979b018faaf90ff5a7bb04ac3f38e9dee6e3
    if [[ "$(scripts_config -s TEGRA20_EMC)" = "m" ]] &&
        grep -q 'bool "NVIDIA Tegra20 External Memory Controller driver"' "$linux_src"/drivers/memory/tegra/Kconfig; then
        scripts_config_args+=(-e TEGRA20_EMC)
    fi

    # CONFIG_TEGRA30_EMC as a module is invalid before https://git.kernel.org/linus/0c56eda86f8cad705d7d14e81e0e4efaeeaf4613
    if [[ "$(scripts_config -s TEGRA30_EMC)" = "m" ]] &&
        grep -q 'bool "NVIDIA Tegra30 External Memory Controller driver"' "$linux_src"/drivers/memory/tegra/Kconfig; then
        scripts_config_args+=(-e TEGRA30_EMC)
    fi

    # CONFIG_TI_CPTS as a module is invalid before https://git.kernel.org/linus/92db978f0d686468e527d49268e7c7e8d97d334b
    if [[ "$(scripts_config -s TI_CPTS)" = "m" ]] &&
        grep -q 'bool "TI Common Platform Time Sync' "$linux_src"/drivers/net/ethernet/ti/Kconfig; then
        scripts_config_args+=(-e TI_CPTS)
    fi

    # CONFIG_UNICODE as a module is invalid before https://git.kernel.org/linus/5298d4bfe80f6ae6ae2777bcd1357b0022d98573
    if [[ "$(scripts_config -s UNICODE)" = "m" ]] &&
        grep -q 'bool "UTF-8 normalization and casefolding support"' "$linux_src"/fs/unicode/Kconfig; then
        scripts_config_args+=(-e UNICODE)
    fi

    # CONFIG_VIRTIO_IOMMU as a module is invalid before https://git.kernel.org/linus/fa4afd78ea12cf31113f8b146b696c500d6a9dc3
    if [[ "$(scripts_config -s VIRTIO_IOMMU)" = "m" ]] &&
        grep -q 'bool "Virtio IOMMU driver"' "$linux_src"/drivers/iommu/Kconfig; then
        scripts_config_args+=(-e VIRTIO_IOMMU)
    fi

    # Several ZORAN configurations are invalid as modules after https://git.kernel.org/next/linux-next/c/fe047de480ca23e59ab797465902f2bc4fd937cd
    for zoran_config in DC30 ZR36060 BUZ DC10 LML33 LML33R10 AVS6EYES; do
        zoran_config=VIDEO_ZORAN_"$zoran_config"
        if [[ "$(scripts_config -s $zoran_config)" = "m" ]] &&
            grep -oPqz "(?s)config $zoran_config.*?bool" "$linux_src"/drivers/staging/media/zoran/Kconfig 2>/dev/null; then
            scripts_config_args+=(-e "$zoran_config")
        fi
    done

    # CONFIG_ZPOOL as a module is invalid after https://git.kernel.org/akpm/mm/c/ba34176c517039ac4dce053341a854f92e67f1e0
    if [[ "$(scripts_config -s ZPOOL)" = "m" ]] &&
        ! grep -q "Compressed memory storage API.  This allows using either zbud or" "$linux_src"/mm/Kconfig; then
        scripts_config_args+=(-e ZPOOL)
    fi

    [[ -n "${scripts_config_args[*]}" ]] && scripts_config -k "${scripts_config_args[@]}"
    log_comment=""
    for disabled_config in "${disabled_configs[@]}"; do
        log_comment+=" + CONFIG_$disabled_config=n"
        case $disabled_config in
            BPF_PRELOAD)
                log_comment+=" (https://github.com/ClangBuiltLinux/linux/issues/1433)"
                ;;
            DEBUG_INFO_BTF)
                command -v pahole &>/dev/null || log_comment+=" (pahole is not installed)"
                ;;
        esac
    done

}

function swap_endianness() {
    case "${1:?}" in
        b2l) b_opt=-d && l_opt=-e ;;
        l2b) b_opt=-e && l_opt=-d ;;
        *) return 1 ;;
    esac

    scripts_config \
        "$b_opt" CPU_BIG_ENDIAN \
        "$l_opt" CPU_LITTLE_ENDIAN
}

function gen_allconfig() {
    if [[ -n ${configs_to_disable[*]} ]]; then
        config_file=$(mktemp --suffix=.config)
        log_comment=""
        for config_to_disable in "${configs_to_disable[@]}"; do
            config_value=${config_to_disable}=n
            echo "$config_value" >>"$config_file"
            log_comment+=" + $config_value"
        done
    else
        unset config_file
        unset log_comment
    fi
}

function x86_fortify_configs() {
    if grep -q "https://bugs.llvm.org/show_bug.cgi?id=50322" "$linux_src"/security/Kconfig ||
        grep -q "https://github.com/llvm/llvm-project/issues/53645" "$linux_src"/security/Kconfig; then
        while (($#)); do
            case $1 in
                -a | --allconfig)
                    configs_to_disable+=(
                        CONFIG_IP_NF_TARGET_SYNPROXY
                        CONFIG_IP6_NF_TARGET_SYNPROXY
                        CONFIG_NFT_SYNPROXY
                    )
                    nft_log_comment=" (https://github.com/ClangBuiltLinux/linux/issues/1442)"
                    return 0
                    ;;
            esac
            shift
        done

        log_comment+=" + CONFIG_NETFILTER_SYNPROXY=n (https://github.com/ClangBuiltLinux/linux/issues/1442)"
        scripts_config \
            -d IP_NF_TARGET_SYNPROXY \
            -d IP6_NF_TARGET_SYNPROXY \
            -d NFT_SYNPROXY
    fi
}
