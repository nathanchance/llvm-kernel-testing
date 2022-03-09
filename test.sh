#!/usr/bin/env bash

# Make sure that we instantly exit on Ctrl-C
trap 'exit' INT

# Get the absolute location of this repo
root=$(dirname "$(readlink -f "$0")")
[[ -z $root || ! -d $root ]] && exit 1

# Folder setup
src=$root/src

# Logging for the script

# Start tracking script runtime
start_time=$(date +%s)

# Prints an error message in bold red then exits
function die() {
    printf "\n\033[01;31mERROR: %s\033[0m\n" "$*"
    exit "${2:-33}"
}

# Prints a header describing a section of the script
function header() {
    border="====$(for _ in $(seq ${#1}); do printf '='; done)===="
    printf '\033[1m\n%s\n%s\n%s\n\n\033[0m' "$border" "==  $*  ==" "$border"
}

# Logs message to current log
function log() {
    printf "%b\n\n" "$1" >>"$bld_log"
}

# Print formatted time with Python 3
function print_time() {
    python3 -c "import datetime; print(str(datetime.timedelta(seconds=int($2 - $1))))"
}

# Parse inputs to the script
function parse_parameters() {
    arches=()
    while (($#)); do
        case $1 in
            -a | --arches) shift && IFS=, read -r -a arches <<<"$1" ;;
            --binutils-prefix) shift && binutils_prefix=$(readlink -f "$1") ;;
            --boot-utils) shift && boot_utils=$(readlink -f "$1") ;;
            --ccache) use_ccache=true ;;
            -d | --debug) set -x ;;
            --defconfigs) defconfigs_only=true ;;
            -j | --jobs) shift && jobs=$1 ;;
            -j*) jobs=${1/-j/} ;;
            -l | --linux-src) shift && linux_src=$(readlink -f "$1") ;;
            --llvm-prefix) shift && llvm_prefix=$(readlink -f "$1") ;;
            --log-dir) shift && bld_log_dir=$1 ;;
            --no-ccache) use_ccache=false ;;
            -o | --out-dir) shift && O=$1 ;;
            -q | --qemu-prefix) shift && qemu_prefix=$(readlink -f "$1") ;;
            -t | --tc-prefix) shift && tc_prefix=$(readlink -f "$1") ;;
            --test-cfi-kernel) test_cfi_kernel=true ;;
            *=*) export "${1:?}" ;;
            "") ;;
            *) die "Invalid parameter '$1'" ;;
        esac
        shift
    done

    [[ -z ${arches[*]} ]] && arches=(arm32 arm64 hexagon mips powerpc riscv s390x x86 x86_64)
    [[ -z $defconfigs_only ]] && defconfigs_only=false
    [[ -z $bld_log_dir ]] && bld_log_dir=$root/logs/$(date +%Y%m%d-%H%M)
    [[ -z $linux_src ]] && die "\$linux_src is empty"
    [[ -z $use_ccache ]] && use_ccache=false

    # We purposefully do not use [[ -z ... ]] here so that a user can
    # override this with LOCALVERSION=
    : "${LOCALVERSION=-cbl}"
    export LOCALVERSION

    bld_log=$bld_log_dir/results.log
    mkdir -p "${bld_log%/*}" "$src"
}

# Download/update boot-utils repo
function dwnld_update_boot_utils() {
    if [[ -z $boot_utils ]]; then
        header "Updating boot-utils"

        boot_utils=$src/boot-utils
        [[ -d $boot_utils ]] || git -C "${boot_utils%/*}" clone git://github.com/ClangBuiltLinux/boot-utils
        git -C "$boot_utils" pull --no-edit || die "Updating boot-utils failed"
    fi
}

# Get what CONFIG_LOCALVERSION_AUTO spits out without actually enabling it in every config
# Designed to avoid running make due to overhead
function get_config_localversion_auto() { (
    cd "$linux_src" || exit $?
    git rev-parse --is-inside-work-tree &>/dev/null || return 0

    mkdir -p include/config
    echo "CONFIG_LOCALVERSION_AUTO=y" >include/config/auto.conf
    scripts/setlocalversion
    rm -rf include/config
); }

function check_binutils() {
    as=${CROSS_COMPILE}as
    if command -v "$as" &>/dev/null; then
        return 0
    else
        msg="$1 kernels skipped due to missing binutils"
        log "$msg"
        echo "$msg"
        echo
        return 1
    fi
}

# Print binutils version for specific architectures
function print_binutils_info() {
    as=${CROSS_COMPILE}as
    echo "binutils version: $("$as" --version | head -n1)"
    echo "binutils location: $(dirname "$(command -v "$as")")"
}

# Print clang, binutils, and kernel versions being tested into the build log
function print_tc_lnx_env_info() {
    clang --version | head -n1
    clang --version | tail -n1

    print_binutils_info

    echo "Linux $(make -C "$linux_src" -s kernelversion)$(get_config_localversion_auto)"
    echo "PATH: $PATH"
}

# Set tool variables based on availability
function set_tool_vars() {
    if $use_ccache; then
        ccache=$(command -v ccache)
    fi
    kbzip2=$(command -v pbzip2)
    kgzip=$(command -v pigz)
}

# make wrapper for the kernel so we can set all variables that we need
function kmake() {
    kmake_start=$(date +%s)
    (
        make_args=()
        while (($#)); do
            case $1 in
                # Consume these to avoid duplicates in the 'set -x' print out
                LD=* | LLVM_IAS=* | OBJCOPY=* | OBJDUMP=*) export "${1:?}" ;;
                *) make_args+=("$1") ;;
            esac
            shift
        done

        set -x
        time stdbuf -eL -oL make \
            -C "$linux_src" \
            -skj"${jobs:=$(nproc)}" \
            ${AR:+AR="${AR}"} \
            ${ccache:+CC="ccache clang"} \
            ${HOSTAR:+HOSTAR="${HOSTAR}"} \
            ${ccache:+HOSTCC="ccache clang"} \
            ${HOSTLD:+HOSTLD="${HOSTLD}"} \
            HOSTLDFLAGS="${HOSTLDFLAGS--fuse-ld=lld}" \
            ${kbzip2:+KBZIP2=pbzip2} \
            ${KCFLAGS:+KCFLAGS="${KCFLAGS}"} \
            ${kgzip:+KGZIP=pigz} \
            ${LD:+LD="${LD}"} \
            LLVM=1 \
            LLVM_IAS="${LLVM_IAS:-0}" \
            ${LOCALVERSION:+LOCALVERSION="${LOCALVERSION}"} \
            ${NM:+NM="${NM}"} \
            O="${out#"$linux_src"/*}" \
            ${OBJCOPY:+OBJCOPY="${OBJCOPY}"} \
            ${OBJDUMP:+OBJDUMP="${OBJDUMP}"} \
            ${OBJSIZE:+OBJSIZE="${OBJSIZE}"} \
            ${READELF:+READELF="${READELF}"} \
            ${STRIP:+STRIP="${STRIP}"} \
            "${make_args[@]}" |& tee "$bld_log_dir/$klog.log"
        inner_ret=${PIPESTATUS[0]}
        set +x
        exit "$inner_ret"
    )
    outer_ret=$?
    kmake_end=$(date +%s)
    return "$outer_ret"
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
    if grep -oPqz '(?s)config CRYPTO_ARCH_HAVE_LIB_BLAKE2S.*?bool' "$linux_src"/lib/crypto/Kconfig; then
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

    # CONFIG_GPIO_PL061 as a module is invalid before https://git.kernel.org/linus/616844408de7f21546c3c2a71ea7f8d364f45e0d
    if [[ "$(scripts_config -s GPIO_PL061)" = "m" ]] &&
        grep -q 'bool "PrimeCell PL061 GPIO support"' "$linux_src"/drivers/gpio/Kconfig; then
        scripts_config_args+=(-e GPIO_PL061)
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

    # CONFIG_VIRTIO_IOMMU as a module is invalid before https://git.kernel.org/linus/fa4afd78ea12cf31113f8b146b696c500d6a9dc3
    if [[ "$(scripts_config -s VIRTIO_IOMMU)" = "m" ]] &&
        grep -q 'bool "Virtio IOMMU driver"' "$linux_src"/drivers/iommu/Kconfig; then
        scripts_config_args+=(-e VIRTIO_IOMMU)
    fi

    # Several ZORAN configurations are invalid as modules after https://git.kernel.org/next/linux-next/c/fe047de480ca23e59ab797465902f2bc4fd937cd
    for zoran_config in DC30 ZR36060 BUZ DC10 LML33 LML33R10 AVS6EYES; do
        zoran_config=VIDEO_ZORAN_"$zoran_config"
        if [[ "$(scripts_config -s $zoran_config)" = "m" ]] &&
            grep -oPqz "(?s)config $zoran_config.*?bool" "$linux_src"/drivers/staging/media/zoran/Kconfig; then
            scripts_config_args+=(-e "$zoran_config")
        fi
    done

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

function results() {
    if [[ -n $qemu && $krnl_rc -ne 0 ]]; then
        result=skipped
    elif [[ -n $qemu && $1 -eq 32 ]]; then
        result="skipped due to a QEMU binary newer than 5.0.1 and older than 6.2.0 (found $raw_qemu_ver)"
    elif [[ -n $qemu && $1 -eq 33 ]]; then
        result="skipped due to a QEMU binary older than 6.0.0 (found $raw_qemu_ver)"
    elif [[ -n $qemu && $1 -eq 127 ]]; then
        result="skipped due to missing QEMU binary in PATH"
    elif [[ $1 -eq 0 ]]; then
        result=successful
    else
        result=failed
    fi
    printf "%s" "$result"
    if [[ -n $qemu ]]; then
        printf '\n'
    else
        printf " in %s" "$(print_time "$kmake_start" "$kmake_end")"
        printf '\n'
        [[ $result = "failed" ]] && grep "error:\|warning:\|undefined" "$bld_log_dir/$klog.log"
    fi
    printf '\n'
}

# Build arm32 kernels
function build_arm32_kernels() {
    local CROSS_COMPILE kmake_args log_comment
    for cross_compile in arm-linux-gnu{,eabi{hf,}}-; do
        command -v "$cross_compile"as &>/dev/null && break
    done
    CROSS_COMPILE=$cross_compile
    kmake_args=(ARCH=arm)
    header "Building arm32 kernels"

    if [[ $llvm_ver_code -ge 130000 && $lnx_ver_code -ge 513000 ]]; then
        kmake_args+=(LLVM_IAS=1)
        if [[ ! -f $linux_src/scripts/Makefile.clang ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
    else
        kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        check_binutils arm32 || return
        print_binutils_info
        echo
    fi

    # Upstream
    klog=arm32-multi_v5_defconfig
    kmake "${kmake_args[@]}" distclean multi_v5_defconfig all
    krnl_rc=$?
    log "arm32 multi_v5_defconfig$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm32_v5
    log "arm32 multi_v5_defconfig$log_comment qemu boot $(qemu=1 results "$?")"

    klog=arm32-aspeed_g5_defconfig
    kmake "${kmake_args[@]}" distclean aspeed_g5_defconfig all
    krnl_rc=$?
    log "arm32 aspeed_g5_defconfig $(results "$krnl_rc")"
    qemu_boot_kernel arm32_v6
    log "arm32 aspeed_g5_defconfig qemu boot $(qemu=1 results "$?")"

    klog=arm32-multi_v7_defconfig
    kmake "${kmake_args[@]}" distclean multi_v7_defconfig all
    krnl_rc=$?
    log "arm32 multi_v7_defconfig $(results "$krnl_rc")"
    qemu_boot_kernel arm32_v7
    log "arm32 multi_v7_defconfig qemu boot $(qemu=1 results "$?")"

    # https://github.com/ClangBuiltLinux/linux/issues/325
    if grep -q "select HAVE_FUTEX_CMPXCHG if FUTEX" "$linux_src"/arch/arm/Kconfig ||
        ! grep -q "select HAVE_FUTEX_CMPXCHG" "$linux_src"/arch/arm/Kconfig; then
        klog=arm32-multi_v7_defconfig-thumb2
        kmake "${kmake_args[@]}" distclean multi_v7_defconfig
        scripts_config -e THUMB2_KERNEL
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "arm32 multi_v7_defconfig + CONFIG_THUMB2_KERNEL=y $(results "$krnl_rc")"
        qemu_boot_kernel arm32_v7
        log "arm32 multi_v7_defconfig + CONFIG_THUMB2_KERNEL=y qemu boot $(qemu=1 results "$?")"
    fi

    $defconfigs_only && return 0

    configs_to_disable=()
    grep -oPqz '(?s)depends on ARCH_SUPPORTS_BIG_ENDIAN.*?depends on \!LD_IS_LLD' "$linux_src"/arch/arm/mm/Kconfig || configs_to_disable+=(CONFIG_CPU_BIG_ENDIAN)
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    gen_allconfig
    klog=arm32-allmodconfig
    kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "arm32 allmodconfig$log_comment $(results "$?")"
    rm -f "$config_file"

    klog=arm32-allnoconfig
    kmake "${kmake_args[@]}" distclean allnoconfig all
    log "arm32 allnoconfig $(results "$?")"

    klog=arm32-tinyconfig
    kmake "${kmake_args[@]}" distclean tinyconfig all
    log "arm32 tinyconfig $(results "$?")"

    # Alpine Linux
    klog=arm32-alpine
    setup_config alpine/armv7.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "armv7 alpine config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm32_v7
    log "armv7 alpine config qemu boot $(qemu=1 results "$?")"

    # Arch Linux ARM
    klog=arm32-v5-archlinux
    setup_config archlinux/armv5.config
    kmake "${kmake_args[@]}" olddefconfig all
    log "armv5 archlinux config$log_comment $(results "$?")"

    klog=arm32-v7-archlinux
    setup_config archlinux/armv7.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "armv7 archlinux config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm32_v7
    log "armv7 archlinux config qemu boot $(qemu=1 results "$?")"

    # Debian
    klog=arm32-debian
    setup_config debian/armmp.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm32 debian config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm32_v7
    log "arm32 debian config qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=arm32-fedora
    setup_config fedora/armv7hl.config
    kmake "${kmake_args[@]}" olddefconfig all
    log "armv7hl fedora config$log_comment $(results "$?")"

    # OpenSUSE
    klog=arm32-opensuse
    setup_config opensuse/armv7hl.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "armv7hl opensuse config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm32_v7
    log "armv7hl opensuse config qemu boot $(qemu=1 results "$?")"
}

# Build arm64 kernels
function build_arm64_kernels() {
    local kmake_args
    kmake_args=(ARCH=arm64)

    header "Building arm64 kernels"

    if [[ $(uname -m) = "aarch64" ]]; then
        unset CROSS_COMPILE
    else
        CROSS_COMPILE=aarch64-linux-gnu-
    fi

    if [[ $lnx_ver_code -ge 510000 ]]; then
        kmake_args+=(LLVM_IAS=1)
        if [[ ! -f $linux_src/scripts/Makefile.clang && -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
    else
        if [[ -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
        check_binutils arm64 || return
        print_binutils_info
        echo
    fi

    # Upstream
    klog=arm64-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "arm64 defconfig $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 defconfig qemu boot $(qemu=1 results "$?")"

    if [[ $llvm_ver_code -ge 130000 ]]; then
        klog=arm64be-defconfig
        kmake "${kmake_args[@]}" distclean defconfig
        swap_endianness l2b
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y $(results "$krnl_rc")"
        qemu_boot_kernel arm64be
        log "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y qemu boot $(qemu=1 results "$?")"
    fi

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig; then
        klog=arm64-defconfig-lto
        kmake "${kmake_args[@]}" distclean defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "$krnl_rc")"
        qemu_boot_kernel arm64
        log "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y qemu boot $(qemu=1 results "$?")"
    fi

    if grep -q "config CFI_CLANG" "$linux_src"/arch/Kconfig && [[ $llvm_ver_code -ge 120000 ]]; then
        klog=arm64-defconfig-lto-scs-cfi
        kmake "${kmake_args[@]}" distclean defconfig
        tmp_config=$(mktemp --suffix=.config)
        cat <<EOF >"$tmp_config"
CONFIG_CFI_CLANG=y
CONFIG_LTO_CLANG_THIN=y
CONFIG_LTO_NONE=n
CONFIG_SHADOW_CALL_STACK=y
EOF
        merge_config "$tmp_config"
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y $(results "$krnl_rc")"
        qemu_boot_kernel arm64
        log "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y qemu boot $(qemu=1 results "$?")"
        rm "$tmp_config"
    fi

    $defconfigs_only && return 0

    configs_to_disable=()
    grep -q 'prompt "Endianness"' "$linux_src"/arch/arm64/Kconfig || configs_to_disable+=(CONFIG_CPU_BIG_ENDIAN)
    # https://github.com/ClangBuiltLinux/continuous-integration2/issues/246
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    gen_allconfig
    klog=arm64-allmodconfig
    kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "arm64 allmodconfig$log_comment $(results "$?")"
    rm -f "$config_file"

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig; then
        configs_to_disable=(CONFIG_GCOV_KERNEL CONFIG_KASAN)
        grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
        gen_allconfig
        echo "CONFIG_LTO_CLANG_THIN=y" >>"$config_file"
        klog=arm64-allmodconfig-thinlto
        kmake "${kmake_args[@]}" KCONFIG_ALLCONFIG="$config_file" distclean allmodconfig all
        log "arm64 allmodconfig$log_comment + CONFIG_LTO_CLANG_THIN=y $(results "$?")"
        rm -f "$config_file"
    fi

    klog=arm64-allnoconfig
    kmake "${kmake_args[@]}" distclean allnoconfig all
    log "arm64 allnoconfig $(results "$?")"

    klog=arm64-tinyconfig
    kmake "${kmake_args[@]}" distclean tinyconfig all
    log "arm64 tinyconfig $(results "$?")"

    # Alpine Linux
    klog=arm64-alpine
    setup_config alpine/aarch64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 alpine config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 alpine config qemu boot $(qemu=1 results "$?")"

    # Arch Linux ARM
    klog=arm64-archlinux
    setup_config archlinux/aarch64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 archlinux config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 archlinux config qemu boot $(qemu=1 results "$?")"

    # Debian
    klog=arm64-debian
    setup_config debian/arm64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 debian config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 debian config qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=arm64-fedora
    log_comment=""
    setup_config fedora/aarch64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 fedora config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 fedora config$log_comment qemu boot $(qemu=1 results "$?")"

    # OpenSUSE
    klog=arm64-opensuse
    setup_config opensuse/arm64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 opensuse config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 opensuse config qemu boot $(qemu=1 results "$?")"
}

# Build hexagon kernels
function build_hexagon_kernels() {
    kmake_args=(
        ARCH=hexagon
        LLVM_IAS=1
    )
    if [[ ! -f $linux_src/scripts/Makefile.clang ]]; then
        kmake_args+=(CROSS_COMPILE=hexagon-linux-gnu-)
    fi

    # Hexagon was broken without some fixes
    if ! grep -q "KBUILD_CFLAGS += -mlong-calls" "$linux_src"/arch/hexagon/Makefile || ! [[ -f $linux_src/arch/hexagon/lib/divsi3.S ]]; then
        echo
        echo "Hexagon needs the following fixes from Linux 5.13 to build properly:"
        echo
        echo '  * https://git.kernel.org/linus/788dcee0306e1bdbae1a76d1b3478bb899c5838e'
        echo '  * https://git.kernel.org/linus/6fff7410f6befe5744d54f0418d65a6322998c09'
        echo '  * https://git.kernel.org/linus/f1f99adf05f2138ff2646d756d4674e302e8d02d'
        echo
        echo "Provide a kernel tree with Linux 5.13+ or one with these fixes to build Hexagon kernels"
        return 0
    fi

    header "Building hexagon kernels"

    # Upstream
    klog=hexagon-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "hexagon defconfig $(results "$krnl_rc")"

    $defconfigs_only && return 0

    if grep -Fq "EXPORT_SYMBOL(__raw_readsw)" "$linux_src"/arch/hexagon/lib/io.c; then
        klog=hexagon-allmodconfig
        configs_to_disable=()
        grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
        gen_allconfig
        kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
        krnl_rc=$?
        log "hexagon allmodconfig $(results "$krnl_rc")"
        rm -f "$config_file"
    fi
}

# Build mips kernels
function build_mips_kernels() {
    local CROSS_COMPILE kmake_args
    for cross_compile in mips{64,el}-linux-gnu-; do
        command -v "$cross_compile"as &>/dev/null && break
    done
    CROSS_COMPILE=$cross_compile
    kmake_args=(
        ARCH=mips
        CROSS_COMPILE="$CROSS_COMPILE"
    )

    header "Building mips kernels"

    check_binutils mips || return
    print_binutils_info
    echo

    # Upstream
    klog=mipsel-malta
    kmake "${kmake_args[@]}" distclean malta_defconfig
    scripts_config -e BLK_DEV_INITRD
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y $(results "$krnl_rc")"
    qemu_boot_kernel mipsel
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y qemu boot $(qemu=1 results "$?")"

    klog=mipsel-malta-kaslr
    kmake "${kmake_args[@]}" distclean malta_defconfig
    scripts_config \
        -e BLK_DEV_INITRD \
        -e RELOCATABLE \
        --set-val RELOCATION_TABLE_SIZE 0x00200000 \
        -e RANDOMIZE_BASE
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_RANDOMIZE_BASE=y $(results "$krnl_rc")"
    qemu_boot_kernel mipsel
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_RANDOMIZE_BASE=y qemu boot $(qemu=1 results "$?")"

    # https://github.com/ClangBuiltLinux/linux/issues/1025
    klog=mips-malta
    [[ -f $linux_src/arch/mips/vdso/Kconfig && $llvm_ver_code -lt 130000 ]] && mips_be_ld=${CROSS_COMPILE}ld
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean malta_defconfig
    scripts_config -e BLK_DEV_INITRD
    swap_endianness l2b
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} olddefconfig all
    krnl_rc=$?
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_CPU_BIG_ENDIAN=y $(results "$krnl_rc")"
    qemu_boot_kernel mips
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_CPU_BIG_ENDIAN=y qemu boot $(qemu=1 results "$?")"

    klog=mips-32r1
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r1_defconfig all
    log "mips 32r1_defconfig $(results "$?")"

    klog=mips-32r1el
    kmake "${kmake_args[@]}" distclean 32r1el_defconfig all
    log "mips 32r1el_defconfig $(results "$?")"

    klog=mips-32r2
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r2_defconfig all
    log "mips 32r2_defconfig $(results "$?")"

    klog=mips-32r2el
    kmake "${kmake_args[@]}" distclean 32r2el_defconfig all
    log "mips 32r2el_defconfig $(results "$?")"

    # https://github.com/ClangBuiltLinux/linux/issues/1241
    klog=mips-32r2
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r2_defconfig all
    log "mips 32r2_defconfig $(results "$?")"

    klog=mips-32r2el
    kmake "${kmake_args[@]}" distclean 32r2el_defconfig all
    log "mips 32r2el_defconfig $(results "$?")"

    # https://github.com/llvm/llvm-project/issues/48039
    if [[ $llvm_ver_code -ge 120000 ]]; then
        klog=mips-32r6
        kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r6_defconfig all
        log "mips 32r6_defconfig $(results "$?")"

        klog=mips-32r6el
        kmake "${kmake_args[@]}" distclean 32r6el_defconfig all
        log "mips 32r6el_defconfig $(results "$?")"
    fi

    klog=mips-allnoconfig
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean allnoconfig all
    log "mips allnoconfig $(results "$?")"

    klog=mips-tinyconfig
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean tinyconfig all
    log "mips tinyconfig $(results "$?")"
}

# Build powerpc kernels
function build_powerpc_kernels() {
    local CROSS_COMPILE ctod kmake_args log_comment
    for cross_compile in powerpc{64,}-linux-gnu-; do
        command -v "$cross_compile"as &>/dev/null && break
    done
    CROSS_COMPILE=$cross_compile
    kmake_args=(
        ARCH=powerpc
        CROSS_COMPILE="$CROSS_COMPILE"
    )

    header "Building powerpc kernels"

    check_binutils powerpc || return
    print_binutils_info
    echo

    # Upstream
    klog=powerpc-ppc44x_defconfig
    kmake "${kmake_args[@]}" distclean ppc44x_defconfig all uImage
    krnl_rc=$?
    log "powerpc ppc44x_defconfig $(results "$krnl_rc")"
    qemu_boot_kernel ppc32
    log "powerpc ppc44x_defconfig qemu boot $(qemu=1 results "$?")"

    # https://github.com/ClangBuiltLinux/linux/issues/563
    if grep -q " __restrict " "$linux_src"/arch/powerpc/lib/xor_vmx.c; then
        klog=powerpc-pmac32_defconfig
        kmake "${kmake_args[@]}" distclean pmac32_defconfig
        scripts_config -e SERIAL_PMACZILOG -e SERIAL_PMACZILOG_CONSOLE
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "powerpc pmac32_defconfig $(results "$krnl_rc")"
        qemu_boot_kernel ppc32_mac
        log "powerpc pmac32_defconfig qemu boot $(qemu=1 results "$?")"
    fi

    klog=powerpc-allnoconfig
    kmake "${kmake_args[@]}" distclean allnoconfig all
    log "powerpc allnoconfig $(results "$?")"

    klog=powerpc-tinyconfig
    kmake "${kmake_args[@]}" distclean tinyconfig all
    log "powerpc tinyconfig $(results "$?")"

    klog=powerpc64-pseries_defconfig
    pseries_targets=(pseries_defconfig)
    # https://github.com/ClangBuiltLinux/linux/issues/1292
    if ! grep -q "noinline_for_stack void byteswap_pt_regs" "$linux_src"/arch/powerpc/kvm/book3s_hv_nested.c && [[ $llvm_ver_code -ge 120000 ]]; then
        ctoe=CONFIG_PPC_DISABLE_WERROR
        if [[ -f $linux_src/arch/powerpc/configs/disable-werror.config ]]; then
            pseries_targets+=(disable-werror.config all)
        else
            sc_dwerror=true
        fi
        log_comment=" + ${ctoe}=y"
    else
        pseries_targets+=(all)
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/602
    kmake "${kmake_args[@]}" LD=${CROSS_COMPILE}ld distclean "${pseries_targets[@]}"
    krnl_rc=$?
    if ${sc_dwerror:=false}; then
        scripts_config -e $ctoe
        kmake "${kmake_args[@]}" LD=${CROSS_COMPILE}ld olddefconfig all
        krnl_rc=$?
    fi
    log "powerpc pseries_defconfig$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel ppc64
    log "powerpc pseries_defconfig qemu boot$log_comment $(qemu=1 results "$?")"

    CROSS_COMPILE=powerpc64-linux-gnu-
    kmake_args=(
        ARCH=powerpc
        CROSS_COMPILE="$CROSS_COMPILE"
    )

    klog=powerpc64le-powernv_defconfig
    kmake "${kmake_args[@]}" distclean powernv_defconfig all
    krnl_rc=$?
    log "powerpc powernv_defconfig $(results "$krnl_rc")"
    qemu_boot_kernel ppc64le
    log "powerpc powernv_defconfig qemu boot $(qemu=1 results "$?")"

    ppc64le_args=()
    # https://github.com/ClangBuiltLinux/linux/issues/811
    # shellcheck disable=SC2016
    grep -Fq 'LDFLAGS_vmlinux-$(CONFIG_RELOCATABLE) += -z notext' "$linux_src"/arch/powerpc/Makefile || ppc64le_args+=(LD="${CROSS_COMPILE}"ld)

    klog=powerpc64le-defconfig
    kmake "${kmake_args[@]}" "${ppc64le_args[@]}" distclean ppc64le_defconfig all
    log "powerpc ppc64le_defconfig $(results "$?")"

    $defconfigs_only && return 0

    # Debian
    klog=powerpc64le-debian
    setup_config debian/powerpc64le.config
    kmake "${kmake_args[@]}" "${ppc64le_args[@]}" olddefconfig all
    krnl_rc=$?
    log "ppc64le debian config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel ppc64le
    log "ppc64le debian config$log_comment qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=powerpc64le-fedora
    setup_config fedora/ppc64le.config
    kmake "${kmake_args[@]}" "${ppc64le_args[@]}" olddefconfig all
    krnl_rc=$?
    log "ppc64le fedora config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel ppc64le
    log "ppc64le fedora config$log_comment qemu boot $(qemu=1 results "$?")"

    # OpenSUSE
    # https://github.com/ClangBuiltLinux/linux/issues/1160
    if ! grep -q "depends on PPC32 || COMPAT" "$linux_src"/arch/powerpc/platforms/Kconfig.cputype || [[ $llvm_ver_code -ge 120000 ]]; then
        klog=powerpc64le-opensuse
        setup_config opensuse/ppc64le.config
        kmake "${kmake_args[@]}" "${ppc64le_args[@]}" olddefconfig all
        krnl_rc=$?
        log "ppc64le opensuse config$log_comment $(results "$krnl_rc")"
        qemu_boot_kernel ppc64le
        log "ppc64le opensuse config qemu boot $(qemu=1 results "$?")"
    else
        log "ppc64le opensuse config skipped (https://github.com/ClangBuiltLinux/linux/issues/1160)"
    fi
}

# Build riscv kernels
function build_riscv_kernels() {
    local kmake_args
    CROSS_COMPILE=riscv64-linux-gnu-
    kmake_args=(
        ARCH=riscv
        CROSS_COMPILE="$CROSS_COMPILE"
    )

    # riscv did not build properly for Linux prior to 5.7 and there is an
    # inordinate amount of spam about '-save-restore' before LLVM 11: https://llvm.org/pr44853
    if [[ $lnx_ver_code -lt 507000 || $llvm_ver_code -lt 110000 ]]; then
        header "Skipping riscv kernels"
        echo "Reasons:"
        if [[ $lnx_ver_code -lt 507000 ]]; then
            echo
            echo "RISC-V needs the following fixes from Linux 5.7 to build properly:"
            echo
            echo '  * https://git.kernel.org/linus/52e7c52d2ded5908e6a4f8a7248e5fa6e0d6809a'
            echo '  * https://git.kernel.org/linus/fdff9911f266951b14b20e25557278b5b3f0d90d'
            echo '  * https://git.kernel.org/linus/abc71bf0a70311ab294f97a7f16e8de03718c05a'
            echo
            echo "Provide a kernel tree with Linux 5.7 or newer to build RISC-V kernels"
        fi
        if [[ $llvm_ver_code -lt 110000 ]]; then
            echo
            echo "RISC-V needs a patch from LLVM 11 to build without a massive amount of warnings."
            echo
            echo "https://github.com/llvm/llvm-project/commit/07f7c00208b393296f8f27d6cd3cec2b11d86fd8"
        fi
        return 0
    fi

    header "Building riscv kernels"

    if [[ $llvm_ver_code -ge 130000 ]]; then
        kmake_args+=(LLVM_IAS=1)
    else
        check_binutils riscv || return
        print_binutils_info
        echo
    fi

    klog=riscv-defconfig
    log_comment=""
    # https://github.com/ClangBuiltLinux/linux/issues/1020
    if [[ $llvm_ver_code -lt 130000 ]] || ! grep -q 'mno-relax' "$linux_src"/arch/riscv/Makefile; then
        kmake_args+=(LD=riscv64-linux-gnu-ld)
    else
        # linux-5.10.y has a build problem with ld.lld
        if [[ $lnx_ver_code -le 510999 ]]; then
            kmake_args+=(LD=riscv64-linux-gnu-ld)
        fi
    fi
    kmake "${kmake_args[@]}" distclean defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/1143
    if [[ $llvm_ver_code -lt 130000 ]] && grep -q "config EFI" "$linux_src"/arch/riscv/Kconfig; then
        log_comment+=" + CONFIG_EFI=n (https://github.com/ClangBuiltLinux/linux/issues/1143)"
        scripts_config -d CONFIG_EFI
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "riscv defconfig$log_comment $(results "$krnl_rc")"
    # https://github.com/ClangBuiltLinux/linux/issues/867
    if grep -q "(long)__old" "$linux_src"/arch/riscv/include/asm/cmpxchg.h; then
        qemu_boot_kernel riscv
        log "riscv defconfig qemu boot $(qemu=1 results "$?")"
    fi

    $defconfigs_only && return 0

    # https://github.com/ClangBuiltLinux/linux/issues/999
    if [[ $lnx_ver_code -gt 508000 ]] && grep -q 'mno-relax' "$linux_src"/arch/riscv/Makefile; then
        klog=riscv-allmodconfig
        configs_to_disable=()
        grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
        gen_allconfig
        kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
        krnl_rc=$?
        log "riscv allmodconfig$log_comment $(results "$krnl_rc")"
        rm -f "$config_file"

        klog=riscv-opensuse
        setup_config opensuse/riscv64.config
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "riscv opensuse config$log_comment $(results "$krnl_rc")"
        qemu_boot_kernel riscv
        log "riscv opensuse config qemu boot $(qemu=1 results "$?")"
    fi
}

# Build s390x kernels
# Non-working LLVM tools outline:
#   * ld.lld
#   * llvm-objcopy
#   * llvm-objdump
function build_s390x_kernels() {
    local CROSS_COMPILE ctod kmake_args log_comment
    CROSS_COMPILE=s390x-linux-gnu-
    kmake_args=(
        ARCH=s390
        CROSS_COMPILE="$CROSS_COMPILE"
        LD="${CROSS_COMPILE}"ld
        OBJCOPY="${CROSS_COMPILE}"objcopy
        OBJDUMP="${CROSS_COMPILE}"objdump
    )

    # s390 did not build properly until Linux 5.6
    if [[ $lnx_ver_code -lt 506000 ]]; then
        header "Skipping s390x kernels"
        echo "Reason: s390 kernels did not build properly until Linux 5.6"
        echo "        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/"
        return 0
    fi

    header "Building s390x kernels"

    check_binutils s390x || return
    print_binutils_info
    echo

    # Upstream
    klog=s390x-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "s390x defconfig $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x defconfig qemu boot $(qemu=1 results "$?")"

    $defconfigs_only && return 0

    klog=s390x-allnoconfig
    kmake "${kmake_args[@]}" distclean allnoconfig all
    log "s390x allnoconfig $(results "$?")"

    klog=s390x-tinyconfig
    kmake "${kmake_args[@]}" distclean tinyconfig all
    log "s390x tinyconfig $(results "$?")"

    klog=s390x-allmodconfig
    configs_to_disable=()
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    gen_allconfig
    kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "s390x allmodconfig$log_comment $(results "$?")"
    rm -f "$config_file"

    # Debian
    klog=s390x-debian
    setup_config debian/s390x.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "s390x debian config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x debian config qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=s390x-fedora
    log_comment=""
    setup_config fedora/s390x.config
    if grep -Eq '"(o|n|x)i.*%0,%b1.*n"' "$linux_src"/arch/s390/include/asm/bitops.h; then
        log_comment+=" + CONFIG_MARCH_Z196=y (https://github.com/ClangBuiltLinux/linux/issues/1264)"
        scripts_config -d MARCH_ZEC12 -e MARCH_Z196
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "s390x fedora config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x fedora config$log_comment qemu boot $(qemu=1 results "$?")"

    # OpenSUSE
    klog=s390x-opensuse
    setup_config opensuse/s390x.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "s390x opensuse config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x opensuse config qemu boot $(qemu=1 results "$?")"
}

# Build x86 kernels
function build_x86_kernels() {
    # x86 did not build properly until Linux 5.9
    if [[ $lnx_ver_code -lt 509000 ]]; then
        header "Skipping x86 kernels"
        echo "Reason: x86 kernels did not build properly until Linux 5.9"
        echo "        https://github.com/ClangBuiltLinux/linux/issues/194"
        return 0
    elif [[ $llvm_ver_code -gt 120000 ]] &&
        ! grep -q "R_386_PLT32:" "$linux_src"/arch/x86/tools/relocs.c; then
        header "Skipping x86 kernels"
        echo "Reason: x86 kernels do not build properly with LLVM 12.0.0+ without R_386_PLT32 handling"
        echo "        https://github.com/ClangBuiltLinux/linux/issues/1210"
        return 0
    fi

    header "Building x86 kernels"

    kmake_args=(ARCH=i386)

    export LLVM_IAS=1
    if [[ $(uname -m) = "x86_64" || $(uname -m) = "i386" ]]; then
        unset CROSS_COMPILE
    else
        [[ -f $linux_src/scripts/Makefile.clang ]] || kmake_args+=(CROSS_COMPILE=x86_64-linux-gnu-)
    fi

    # Upstream
    klog=i386-defconfig
    kmake "${kmake_args[@]}" distclean i386_defconfig all
    krnl_rc=$?
    log "i386 defconfig $(results "$krnl_rc")"
    qemu_boot_kernel x86
    log "i386 defconfig qemu boot $(qemu=1 results "$?")"

    if grep -q "select ARCH_SUPPORTS_LTO_CLANG_THIN" "$linux_src"/arch/x86/Kconfig &&
        ! grep -Pq "select ARCH_SUPPORTS_LTO_CLANG_THIN\tif X86_64" "$linux_src"/arch/x86/Kconfig; then
        klog=i386-defconfig-lto
        kmake "${kmake_args[@]}" distclean i386_defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "i386 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "$krnl_rc")"
        qemu_boot_kernel x86
        log "i386 defconfig + CONFIG_LTO_CLANG_THIN=y qemu boot $(qemu=1 results "$?")"
    fi

    $defconfigs_only && return 0

    klog=x86-allmodconfig
    configs_to_disable=()
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    if grep -q "https://bugs.llvm.org/show_bug.cgi?id=50322" "$linux_src"/security/Kconfig ||
        grep -q "https://github.com/llvm/llvm-project/issues/53645" "$linux_src"/security/Kconfig; then
        configs_to_disable+=(
            CONFIG_IP_NF_TARGET_SYNPROXY
            CONFIG_IP6_NF_TARGET_SYNPROXY
            CONFIG_NFT_SYNPROXY
        )
        nft_log_comment=" (https://github.com/ClangBuiltLinux/linux/issues/1442)"
    fi
    gen_allconfig
    kmake "${kmake_args[@]}" ARCH=i386 ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "x86 allmodconfig$log_comment$nft_log_comment $(results "$?")"

    klog=x86-allnoconfig
    kmake "${kmake_args[@]}" distclean allnoconfig all
    log "x86 allnoconfig $(results "$?")"

    klog=x86-tinyconfig
    kmake "${kmake_args[@]}" distclean tinyconfig all
    log "x86 tinyconfig $(results "$?")"

    # Debian
    klog=i386-debian
    setup_config debian/i386.config
    if grep -q "https://bugs.llvm.org/show_bug.cgi?id=50322" "$linux_src"/security/Kconfig ||
        grep -q "https://github.com/llvm/llvm-project/issues/53645" "$linux_src"/security/Kconfig; then
        log_comment+=" + CONFIG_NETFILTER_SYNPROXY=n (https://github.com/ClangBuiltLinux/linux/issues/1442)"
        scripts_config \
            -d IP_NF_TARGET_SYNPROXY \
            -d IP6_NF_TARGET_SYNPROXY \
            -d NFT_SYNPROXY
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    log "i386 debian config$log_comment $(results "$?")"

    # Fedora
    klog=i686-fedora
    setup_config fedora/i686.config
    if grep -q "https://bugs.llvm.org/show_bug.cgi?id=50322" "$linux_src"/security/Kconfig ||
        grep -q "https://github.com/llvm/llvm-project/issues/53645" "$linux_src"/security/Kconfig; then
        log_comment+=" + CONFIG_NETFILTER_SYNPROXY=n (https://github.com/ClangBuiltLinux/linux/issues/1442)"
        scripts_config \
            -d IP_NF_TARGET_SYNPROXY \
            -d IP6_NF_TARGET_SYNPROXY \
            -d NFT_SYNPROXY
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    log "i686 fedora config$log_comment $(results "$?")"

    # OpenSUSE
    klog=i386-opensuse
    setup_config opensuse/i386.config
    kmake "${kmake_args[@]}" olddefconfig all
    log "i386 opensuse config$log_comment $(results "$?")"
}

# Build x86_64 kernels
function build_x86_64_kernels() {
    local log_comment kmake_args
    header "Building x86_64 kernels"

    kmake_args=(ARCH=x86_64)

    if [[ $(uname -m) = "x86_64" ]]; then
        unset CROSS_COMPILE
    else
        CROSS_COMPILE=x86_64-linux-gnu-
    fi

    if [[ $lnx_ver_code -ge 510000 ]]; then
        export LLVM_IAS=1
        if [[ ! -f $linux_src/scripts/Makefile.clang && -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
    else
        if [[ -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
        check_binutils x86_64 || return
        print_binutils_info
        echo
    fi

    # Upstream
    klog=x86_64-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "x86_64 defconfig $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 qemu boot $(qemu=1 results "$?")"

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig; then
        klog=x86_64-defconfig-lto
        kmake "${kmake_args[@]}" distclean defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "$krnl_rc")"
        qemu_boot_kernel x86_64
        log "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y qemu boot $(qemu=1 results "$?")"
    fi

    $defconfigs_only && return 0

    klog=x86_64-allmodconfig
    configs_to_disable=()
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    # https://github.com/ClangBuiltLinux/linux/issues/515
    [[ $lnx_ver_code -lt 507000 ]] && configs_to_disable+=(CONFIG_STM CONFIG_TEST_MEMCAT_P)
    gen_allconfig
    [[ $lnx_ver_code -lt 507000 ]] && log_comment+=" + (https://github.com/ClangBuiltLinux/linux/issues/515)"
    kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "x86_64 allmodconfig$log_comment $(results "$?")"
    rm -f "$config_file"

    klog=x86_64-allmodconfig-O3
    kmake "${kmake_args[@]}" distclean allmodconfig
    # https://github.com/ClangBuiltLinux/linux/issues/678
    if [[ $lnx_ver_code -lt 508000 ]]; then
        log_comment=" + CONFIG_SENSORS_APPLESMC=n (https://github.com/ClangBuiltLinux/linux/issues/678)"
        scripts_config -d CONFIG_SENSORS_APPLESMC
    # https://github.com/ClangBuiltLinux/linux/issues/1116
    elif [[ -f $linux_src/drivers/media/platform/ti-vpe/cal-camerarx.c && $llvm_ver_code -lt 110000 ]]; then
        ctod=CONFIG_VIDEO_TI_CAL
        log_comment=" + ${ctod}=n (https://github.com/ClangBuiltLinux/linux/issues/1116)"
        scripts_config -d $ctod
    elif grep -q "config WERROR" "$linux_src"/init/Kconfig; then
        ctod=CONFIG_WERROR
        log_comment=" + ${ctod}=n"
        scripts_config -d $ctod
    else
        unset log_comment
    fi
    kmake "${kmake_args[@]}" olddefconfig all KCFLAGS="${KCFLAGS:+${KCFLAGS} }-O3"
    log "x86_64 allmodconfig at -O3$log_comment $(results "$?")"

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig && [[ $llvm_ver_code -ge 110000 ]]; then
        configs_to_disable=(CONFIG_GCOV_KERNEL CONFIG_KASAN)
        grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
        gen_allconfig
        echo "CONFIG_LTO_CLANG_THIN=y" >>"$config_file"
        klog=x86_64-allmodconfig-thinlto
        kmake "${kmake_args[@]}" KCONFIG_ALLCONFIG="$config_file" distclean allmodconfig all
        log "x86_64 allmodconfig$log_comment + CONFIG_LTO_CLANG_THIN=y $(results "$?")"
        rm -f "$config_file"
    fi

    # Alpine Linux
    klog=x86_64-alpine
    log_comment=""
    setup_config alpine/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "x86_64 alpine config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 alpine config$log_comment qemu boot $(qemu=1 results "$?")"

    # Arch Linux
    klog=x86_64-archlinux
    log_comment=""
    setup_config archlinux/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "x86_64 archlinux config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 archlinux config$log_comment qemu boot $(qemu=1 results "$?")"

    # Debian
    klog=x86_64-debian
    setup_config debian/amd64.config
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake "${kmake_args[@]}" OBJCOPY=${CROSS_COMPILE}objcopy olddefconfig all
    krnl_rc=$?
    log "x86_64 debian config $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 debian config qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=x86_64-fedora
    log_comment=""
    setup_config fedora/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n + CONFIG_TEST_MEMCAT_P=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM -d CONFIG_TEST_MEMCAT_P
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "x86_64 fedora config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 fedora config$log_comment qemu boot $(qemu=1 results "$?")"

    # OpenSUSE
    klog=x86_64-opensuse
    log_comment=""
    setup_config opensuse/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake "${kmake_args[@]}" OBJCOPY=${CROSS_COMPILE}objcopy olddefconfig all
    krnl_rc=$?
    log "x86_64 opensuse config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 opensuse config$log_comment qemu boot $(qemu=1 results "$?")"

    unset LLVM_IAS
}

function build_x86_64_cfi_kernels() {
    header "Building x86_64 CFI kernels"

    if [[ $llvm_ver_code -ge 140000 ]]; then
        klog=x86_64-defconfig-lto-cfi
        kmake ARCH=x86_64 LLVM=1 LLVM_IAS=1 distclean defconfig
        scripts_config -d LTO_NONE -e CFI_CLANG -e LTO_CLANG_THIN
        kmake ARCH=x86_64 LLVM=1 LLVM_IAS=1 olddefconfig all
        krnl_rc=$?
        log "x86_64 defconfig + CONFIG_CFI_CLANG=y $(results "$krnl_rc")"
        qemu_boot_kernel x86_64
        log "x86_64 defconfig + CONFIG_CFI_CLANG=y qemu boot $(qemu=1 results "$?")"
    fi
}

# Build Sami Tolvanen's CFI tree
function build_cfi_kernels() {
    header "Updating CFI kernel source"

    # Grab the latest kernel source
    linux_src=$src/linux-clang-cfi
    [[ -d $linux_src ]] || git clone -b clang-cfi https://github.com/samitolvanen/linux "$linux_src"
    git -C "$linux_src" remote update || return $?
    git -C "$linux_src" reset --hard origin/clang-cfi

    tmp_config=$(mktemp --suffix=.config)
    for arch in "${arches[@]}"; do
        case $arch in
            x86_64)
                out=$(cd "$linux_src" && readlink -f -m "${O:-.build}")/$arch
                if ! check_clang_target "$arch"; then
                    header "Skipping $arch LTO/CFI kernels"
                    echo "Reason: clang was not configured with this target"
                    continue
                fi
                build_"$arch"_cfi_kernels || exit $?
                ;;
            *) ;;
        esac
    done
    rm "$tmp_config"
}

# Print LLVM/clang version as a 5-6 digit number (e.g. clang 11.0.0 will be 110000)
function create_llvm_ver_code() {
    local major minor patchlevel
    major=$(echo __clang_major__ | clang -E -x c - | tail -n 1)
    minor=$(echo __clang_minor__ | clang -E -x c - | tail -n 1)
    patchlevel=$(echo __clang_patchlevel__ | clang -E -x c - | tail -n 1)
    llvm_ver_code=$(printf "%d%02d%02d" "$major" "$minor" "$patchlevel")
}

# Print Linux version as a 6 digit number (e.g. Linux 5.6.2 will be 506002)
function create_lnx_ver_code() {
    lnx_ver=$(make -C "$linux_src" -s kernelversion | sed 's/-rc.*//')
    IFS=. read -ra lnx_ver <<<"$lnx_ver"
    lnx_ver_code=$(printf "%d%02d%03d" "${lnx_ver[@]}")
}

# Print QEMU version as a 5-6 digit number (e.g. QEMU 6.1.0 will be 60100)
function create_qemu_ver_code() {
    raw_qemu_ver=$(qemu-system-"$qemu_suffix" --version | head -1 | cut -d ' ' -f 4)
    IFS=. read -ra qemu_ver <<<"$raw_qemu_ver"
    qemu_ver_code=$(printf "%d%02d%02d" "${qemu_ver[@]}")
}

# Check if the clang binary supports the target before attempting to build
function check_clang_target() {
    local target
    case "${1:?}" in
        arm32) target=arm-linux-gnueabi ;;
        arm64) target=aarch64-linux-gnu ;;
        hexagon) target=hexagon-linux-gnu ;;
        mips) target=mips-linux-gnu ;;
        powerpc) target=powerpc-linux-gnu ;;
        riscv) target=riscv64-linux-gnu ;;
        s390x) target=s390x-linux-gnu ;;
        x86) target=i386-linux-gnu ;;
        x86_64) target=x86_64-linux-gnu ;;
    esac
    echo | clang --target=$target -c -x c - -o /dev/null &>/dev/null
}

function export_path_if_exists() {
    if [[ -d $1 ]]; then
        echo "$PATH" | grep -q "$1" || export PATH="$1:$PATH"
    fi
}

# Build kernels with said toolchains
function build_kernels() {
    export_path_if_exists "$binutils_prefix/bin"
    export_path_if_exists "$llvm_prefix/bin"
    export_path_if_exists "$tc_prefix/bin"
    export_path_if_exists "$qemu_prefix/bin"

    set_tool_vars
    header "Build information"
    print_tc_lnx_env_info
    {
        print_tc_lnx_env_info
        echo
    } >"$bld_log"
    create_lnx_ver_code
    create_llvm_ver_code

    for arch in "${arches[@]}"; do
        out=$(cd "$linux_src" && readlink -f -m "${O:-.build}")/$arch
        if ! check_clang_target "$arch"; then
            header "Skipping $arch kernels"
            echo "Reason: clang was not configured with this target"
            continue
        fi
        build_"$arch"_kernels
    done
    ${test_cfi_kernel:=false} && build_cfi_kernels
}

# Boot the kernel in qemu
function qemu_boot_kernel() {
    if [[ $krnl_rc -eq 0 ]]; then
        case ${1:?} in
            arm64*) qemu_suffix=aarch64 ;;
            arm*) qemu_suffix=arm ;;
            mips*) qemu_suffix=$1 ;;
            ppc32*) qemu_suffix=ppc ;;
            ppc64*) qemu_suffix=ppc64 ;;
            riscv) qemu_suffix=riscv64 ;;
            s390) qemu_suffix=s390x ;;
            x86) qemu_suffix=i386 ;;
            x86_64) qemu_suffix=x86_64 ;;
            *)
                unset qemu_suffix
                return 127
                ;;
        esac
        command -v qemu-system-"$qemu_suffix" &>/dev/null || return 127
        create_qemu_ver_code
        [[ $1 = "ppc32" && $qemu_ver_code -gt 50001 && $qemu_ver_code -lt 60200 ]] && return 32
        [[ $1 = "s390x" && $qemu_ver_code -lt 60000 ]] && return 33
        "$boot_utils"/boot-qemu.sh -a "$1" -k "$out"
    fi
}

# Show the results from the build log and show total script runtime
function report_results() {
    total_runtime="Total script runtime: $(print_time "$start_time" "$(date +%s)")"
    log "$total_runtime"

    # Remove last blank line and full path from errors/warnings because I am OCD :^)
    sed -i -e '${/^$/d}' -e "s;$linux_src/;;g" "$bld_log"
    header "Toolchain and kernel information"
    head -n5 "$bld_log"
    header "List of successes"
    grep "success" "$bld_log"
    fails=$(tail -n +5 "$bld_log" | grep "failed")
    if [[ -n $fails ]]; then
        header "List of failures"
        echo "$fails"
    fi
    echo
    echo "$total_runtime"
}

parse_parameters "$@"
dwnld_update_boot_utils
build_kernels
report_results
