#!/usr/bin/env bash

# Make sure that we instantly exit on Ctrl-C
trap 'exit' INT

# Get the absolute location of this repo
BASE=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
[[ -z ${BASE} ]] && exit 1

# Folder setup
SRC=${BASE}/src
TC_BLD=${SRC}/tc-build

# Logging for the script

# Start tracking script runtime
START_TIME=$(date +%s)

# Prints an error message in bold red then exits
function die() {
    printf "\n\033[01;31m%s\033[0m\n" "${1}"
    exit "${2:-33}"
}

# Prints a header describing a section of the script
function header() {
    BORDER="====$(for _ in $(seq ${#1}); do printf '='; done)===="
    printf '\033[1m\n%s\n%s\n%s\n\n\033[0m' "${BORDER}" "==  ${1}  ==" "${BORDER}"
}

# Logs message to current log
function log() {
    printf "%b\n\n" "${1}" >>"${BLD_LOG}"
}

# Print formatted time with Python 3
function print_time() {
    python3 -c "import datetime; print(str(datetime.timedelta(seconds=int(${2} - ${1}))))"
}

# Parse inputs to the script
function parse_parameters() {
    ARCHES=()
    BLD_LLVM_ARGS=()
    while ((${#})); do
        case ${1} in
            -a | --arches) shift && IFS=, read -r -a ARCHES <<<"${1}" ;;
            -b | --llvm-branch) shift && LLVM_BRANCH=${1} ;;
            --binutils-prefix) shift && BINUTILS_PREFIX=$(readlink -f "${1}") ;;
            --boot-utils) shift && BOOT_UTILS=$(readlink -f "${1}") ;;
            -d | --debug) set -x ;;
            --defconfigs) DEFCONFIGS_ONLY=true ;;
            -j | --jobs) shift && JOBS=${1} ;;
            -j*) JOBS=${1/-j/} ;;
            -l | --linux-src) shift && LINUX_SRC=$(readlink -f "${1}") ;;
            --llvm-prefix) shift && LLVM_PREFIX=$(readlink -f "${1}") ;;
            --log-dir) shift && BLD_LOG_DIR=${1} ;;
            --lto=* | -n | --no-update | --pgo) BLD_LLVM_ARGS=("${BLD_LLVM_ARGS[@]}" "${1}") ;;
            --lto) shift && BLD_LLVM_ARGS=("${BLD_LLVM_ARGS[@]}" --lto "${1}") ;;
            -o | --out-dir) shift && O=${1} ;;
            -s | --skip-tc-build) SKIP_TC_BUILD=true ;;
            -t | --tc-prefix) shift && TC_PREFIX=$(readlink -f "${1}") ;;
            --test-cfi-kernel) TEST_CFI_KERNEL=true ;;
            *=*) export "${1:?}" ;;
            "") ;;
            *) die "Invalid parameter '${1}'" ;;
        esac
        shift
    done

    [[ -z ${ARCHES[*]} ]] && ARCHES=(arm32 arm64 hexagon mips powerpc riscv s390x x86 x86_64)
    [[ -z ${DEFCONFIGS_ONLY} ]] && DEFCONFIGS_ONLY=false
    [[ -z ${BLD_LOG_DIR} ]] && BLD_LOG_DIR=${BASE}/logs/$(date +%Y%m%d-%H%M)
    [[ -z ${TC_PREFIX} ]] && TC_PREFIX=${BASE}/toolchain
    [[ -z ${LLVM_PREFIX} ]] && LLVM_PREFIX=${TC_PREFIX}
    [[ -z ${BINUTILS_PREFIX} ]] && BINUTILS_PREFIX=${TC_PREFIX}

    # We purposefully do not use [[ -z ... ]] here so that a user can
    # override this with LOCALVERSION=
    : "${LOCALVERSION=-cbl}"
    export LOCALVERSION

    BLD_LOG=${BLD_LOG_DIR}/results.log
    mkdir -p "${BLD_LOG%/*}" "${SRC}"
}

# Builds the tools that we are testing
function build_llvm_binutils() {
    ${SKIP_TC_BUILD:=false} && return 0

    header "Building LLVM and binutils"

    [[ -d ${TC_BLD} ]] || git clone git://github.com/ClangBuiltLinux/tc-build "${TC_BLD}"
    git -C "${TC_BLD}" pull --rebase || die "Error updating tc-build" "${?}"

    BINUTILS_TARGETS=()
    for ARCH in "${ARCHES[@]}"; do
        case ${ARCH} in
            arm32) BINUTILS_TARGETS=("${BINUTILS_TARGETS[@]}" arm) ;;
            arm64) BINUTILS_TARGETS=("${BINUTILS_TARGETS[@]}" aarch64) ;;
            # Hexagon does not build binutils
            hexagon) ;;
            mips) BINUTILS_TARGETS=("${BINUTILS_TARGETS[@]}" mips mipsel) ;;
            powerpc) BINUTILS_TARGETS=("${BINUTILS_TARGETS[@]}" powerpc powerpc64 powerpc64le) ;;
            riscv) BINUTILS_TARGETS=("${BINUTILS_TARGETS[@]}" riscv64) ;;
            # We only support x86_64 in build-binutils.py but it works for 32-bit x86 as well
            x86) BINUTILS_TARGETS=("${BINUTILS_TARGETS[@]}" x86_64) ;;
            s390x | x86_64) BINUTILS_TARGETS=("${BINUTILS_TARGETS[@]}" "${ARCH}") ;;
            *) die "Unsupported architecture '${ARCH}'" ;;
        esac
    done

    "${TC_BLD}"/build-llvm.py \
        --assertions \
        --branch "${LLVM_BRANCH:=llvmorg-12.0.0}" \
        --check-targets clang lld llvm \
        --install-folder "${LLVM_PREFIX}" \
        "${BLD_LLVM_ARGS[@]}" || die "build-llvm.py failed" "${?}"

    "${TC_BLD}"/build-binutils.py \
        --install-folder "${BINUTILS_PREFIX}" \
        --targets "${BINUTILS_TARGETS[@]}" || die "build-binutils.py failed" "${?}"
}

# Download the kernel source that we are testing if LINUX_SOURCE wasn't specified
function dwnld_kernel_src() {
    [[ -n ${LINUX_SRC} ]] && return 0

    LINUX=linux-5.11.15
    LINUX_SRC=${SRC}/${LINUX}
    LINUX_TARBALL=${LINUX_SRC}.tar.xz

    # If we don't have the source tarball, download and verify it
    if [[ ! -f ${LINUX_TARBALL} ]]; then
        curl -LSso "${LINUX_TARBALL}" https://cdn.kernel.org/pub/linux/kernel/v5.x/"${LINUX_TARBALL##*/}"
        (
            cd "${LINUX_TARBALL%/*}" || exit ${?}
            sha256sum -c "${BASE}/${LINUX_TARBALL##*/}".sha256 --quiet
        ) ||
            die "Linux tarball verification failed! Please remove '${LINUX_TARBALL}' and try again."
    fi

    [[ -d ${LINUX_SRC} ]] || { tar -C "${LINUX_SRC%/*}" -xf "${LINUX_TARBALL}" || die "Error extracting ${LINUX_TARBALL}." "${?}"; }
}

# Download/update boot-utils repo
function dwnld_update_boot_utils() {
    if [[ -z ${BOOT_UTILS} ]]; then
        header "Updating boot-utils"

        BOOT_UTILS=${SRC}/boot-utils
        [[ -d ${BOOT_UTILS} ]] || git -C "${BOOT_UTILS%/*}" clone git://github.com/ClangBuiltLinux/boot-utils
        git -C "${BOOT_UTILS}" pull --no-edit || die "Error updating boot-utils"
    fi
}

# Get what CONFIG_LOCALVERSION_AUTO spits out without actually enabling it in every config
# Designed to avoid running make due to overhead
function get_config_localversion_auto() { (
    [[ -d ${LINUX_SRC}/.git ]] || return 0
    cd "${LINUX_SRC}" || exit ${?}

    mkdir -p include/config
    touch include/config/auto.conf
    CONFIG_LOCALVERSION_AUTO=y ./scripts/setlocalversion
    rm -rf include/config
); }

# Print binutils version for specific architectures
function print_binutils_info() {
    AS=${CROSS_COMPILE}as
    echo "binutils version: $("${AS}" --version | head -n1)"
    echo "binutils location $(dirname "$(command -v "${AS}")")"
}

# Print clang, binutils, and kernel versions being tested into the build log
function print_tc_lnx_info() {
    clang --version | head -n1
    clang --version | tail -n1

    print_binutils_info

    echo "Linux $(make -C "${LINUX_SRC}" -s kernelversion)$(get_config_localversion_auto)"
}

# Set tool variables based on availability
function set_tool_vars() {
    CCACHE=$(command -v ccache)
    KBZIP2=$(command -v pbzip2)
    KGZIP=$(command -v pigz)
}

# make wrapper for the kernel so we can set all variables that we need
function kmake() {
    KMAKE_START=$(date +%s)
    (
        MAKE_ARGS=()
        while ((${#})); do
            case ${1} in
                # Consume these to avoid duplicates in the 'set -x' print out
                LD=* | LLVM_IAS=* | OBJCOPY=* | OBJDUMP=*) export "${1:?}" ;;
                *) MAKE_ARGS=("${MAKE_ARGS[@]}" "${1}") ;;
            esac
            shift
        done

        set -x
        time stdbuf -eL -oL make \
            -C "${LINUX_SRC}" \
            -skj"${JOBS:=$(nproc)}" \
            ${AR:+AR="${AR}"} \
            ${CCACHE:+CC="ccache clang"} \
            ${HOSTAR:+HOSTAR="${HOSTAR}"} \
            ${CCACHE:+HOSTCC="ccache clang"} \
            ${HOSTLD:+HOSTLD="${HOSTLD}"} \
            HOSTLDFLAGS="${HOSTLDFLAGS--fuse-ld=lld}" \
            ${KBZIP2:+KBZIP2=pbzip2} \
            ${KCFLAGS:+KCFLAGS="${KCFLAGS}"} \
            ${KGZIP:+KGZIP=pigz} \
            ${LD:+LD="${LD}"} \
            LLVM=1 \
            LLVM_IAS="${LLVM_IAS:-0}" \
            ${LOCALVERSION:+LOCALVERSION="${LOCALVERSION}"} \
            ${NM:+NM="${NM}"} \
            O="${OUT#${LINUX_SRC}/*}" \
            ${OBJCOPY:+OBJCOPY="${OBJCOPY}"} \
            ${OBJDUMP:+OBJDUMP="${OBJDUMP}"} \
            ${OBJSIZE:+OBJSIZE="${OBJSIZE}"} \
            ${READELF:+READELF="${READELF}"} \
            ${STRIP:+STRIP="${STRIP}"} \
            "${MAKE_ARGS[@]}" |& tee "${BLD_LOG_DIR}/${KLOG}.log"
        INNER_RET=${PIPESTATUS[0]}
        set +x
        exit "${INNER_RET}"
    )
    OUTER_RET=${?}
    KMAKE_END=$(date +%s)
    return "${OUTER_RET}"
}

# Use config script in kernel source to enable/disable options
function scripts_config() {
    case "${*}" in
        *"-s "*) ;;
        *) set -x ;;
    esac
    "${LINUX_SRC}"/scripts/config --file "${OUT:?}"/.config "${@}"
    set +x
}

function merge_config() {
    case "${*}" in
        *"-s "*) ;;
        *) set -x ;;
    esac
    "${LINUX_SRC}"/scripts/kconfig/merge_config.sh -m -O "${OUT:?}" "${OUT}"/.config "${@}"
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
        ! (command -v pahole &>/dev/null && [[ ${LNX_VER_CODE} -ge 507000 ]]); then
        DISABLED_CONFIGS+=(DEBUG_INFO_BTF)
        scripts_config -d DEBUG_INFO_BTF
    fi

    # https://lore.kernel.org/bpf/20201119085022.3606135-1-davidgow@google.com/
    if [[ "$(scripts_config -s BPF_PRELOAD)" = "y" ]]; then
        DISABLED_CONFIGS+=(BPF_PRELOAD)
        scripts_config -d BPF_PRELOAD
    fi
}

# Set up an out of tree config
function setup_config() {
    # Cleanup the previous artifacts
    rm -rf "${OUT:?}"
    mkdir -p "${OUT}"

    # Grab the config we are testing
    cp -v "${BASE}"/configs/"${1:?}" "${OUT}"/.config

    DISABLED_CONFIGS=()

    handle_bpf_configs

    # Some distro configs have options that are specific to their distro,
    # which will break in a generic environment
    case ${1} in
        debian/*)
            # We are building upstream kernels, which do not have Debian's
            # signing keys in their source
            DISABLED_CONFIGS+=(SYSTEM_TRUSTED_KEYS)
            scripts_config -d SYSTEM_TRUSTED_KEYS

            # The Android drivers are not modular in upstream
            [[ "$(scripts_config -s ANDROID_BINDER_IPC)" = "m" ]] && scripts_config -e ANDROID_BINDER_IPC
            [[ "$(scripts_config -s ASHMEM)" = "m" ]] && scripts_config -e ASHMEM
            ;;

        archlinux/*)
            if [[ -n "$(scripts_config -s CONFIG_EXTRA_FIRMWARE)" ]]; then
                DISABLED_CONFIGS+=(EXTRA_FIRMWARE)
                scripts_config -u EXTRA_FIRMWARE
            fi
            ;;
    esac

    # Make sure that certain configuration options do not get disabled across kernel versions
    # This would not be necessary if we had an individual config for each kernel version
    # that we support but that is a lot more effort.
    SCRIPTS_CONFIG_ARGS=()

    # CONFIG_CHELSIO_IPSEC_INLINE as a module is invalid before https://git.kernel.org/linus/1b77be463929e6d3cefbc929f710305714a89723
    if [[ "$(scripts_config -s CHELSIO_IPSEC_INLINE)" = "m" ]] &&
        grep -q 'bool "Chelsio IPSec XFRM Tx crypto offload"' "${LINUX_SRC}"/drivers/crypto/chelsio/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e CHELSIO_IPSEC_INLINE)
    fi

    # CONFIG_CORESIGHT (and all of its drivers) as a module is invalid before https://git.kernel.org/linus/8e264c52e1dab8a7c1e036222ef376c8920c3423
    if [[ "$(scripts_config -s CORESIGHT)" = "m" ]] &&
        grep -q 'bool "CoreSight Tracing Support"' "${LINUX_SRC}"/drivers/hwtracing/coresight/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e CORESIGHT)
        for CORESIGHT_CONFIG in LINKS_AND_SINKS LINK_AND_SINK_TMC CATU SINK_TPIU SINK_ETBV10 SOURCE_ETM4X STM; do
            [[ "$(scripts_config -s CORESIGHT_${CORESIGHT_CONFIG})" = "m" ]] && SCRIPTS_CONFIG_ARGS+=(-e CORESIGHT_"${CORESIGHT_CONFIG}")
        done
    fi

    # CONFIG_CLK_RK3399 and CONFIG_CLK_RK3568 as modules is invalid after 9af0cbeb477cf36327eec4246a60c5e981b2bd1a
    for NUM in 3399 3568; do
        KCONFIG=CLK_RK${NUM}
        KCONFIG_TEXT="bool \"Rockchip RK${NUM} clock controller support\""
        if [[ "$(scripts_config -s ${KCONFIG})" = "m" ]] &&
            grep -q "${KCONFIG_TEXT}" "${LINUX_SRC}"/drivers/clk/rockchip/Kconfig; then
            SCRIPTS_CONFIG_ARGS+=(-e "${KCONFIG}")
        fi
    done

    # CONFIG_GPIO_MXC as a module is invalid before https://git.kernel.org/linus/12d16b397ce0a999d13762c4c0cae2fb82eb60ee
    if [[ "$(scripts_config -s GPIO_MXC)" = "m" ]] &&
        ! grep -q 'tristate "i.MX GPIO support"' "${LINUX_SRC}"/drivers/gpio/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e GPIO_MXC)
    fi

    # CONFIG_IMX_DSP as a module is invalid before https://git.kernel.org/linus/f52cdcce9197fef9d4a68792dd3b840ad2b77117
    if [[ "$(scripts_config -s IMX_DSP)" = "m" ]] &&
        grep -q 'bool "IMX DSP Protocol driver"' "${LINUX_SRC}"/drivers/firmware/imx/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e IMX_DSP)
    fi

    # CONFIG_INTERCONNECT as a module is invalid after https://git.kernel.org/linus/fcb57bfcb87f3bdb1b29fea1a1cd72940fa559fd
    if [[ "$(scripts_config -s INTERCONNECT)" = "m" ]] &&
        grep -q 'bool "On-Chip Interconnect management support"' "${LINUX_SRC}"/drivers/interconnect/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e INTERCONNECT)
    fi

    # CONFIG_KASAN_STACK=1 is invalid after https://git.kernel.org/next/linux-next/c/031734e881750d622a4bbc0011b45361c779dd8c
    if [[ "$(scripts_config -s KASAN_STACK)" = "1" ]] &&
        ! grep -q "config KASAN_STACK_ENABLE" "${LINUX_SRC}"/lib/Kconfig.kasan; then
        SCRIPTS_CONFIG_ARGS+=(--set-val KASAN_STACK y)
    fi

    # CONFIG_MTD_NAND_ECC_SW_HAMMING as a module is invalid after https://git.kernel.org/next/linux-next/c/5c859c18150b57d47dc684cab6e12b99f5d14ad3
    if [[ "$(scripts_config -s MTD_NAND_ECC_SW_HAMMING)" = "m" ]] &&
        grep -q 'bool "Software Hamming ECC engine"' "${LINUX_SRC}"/drivers/mtd/nand/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e MTD_NAND_ECC_SW_HAMMING)
    fi

    # CONFIG_PCI_EXYNOS as a module is invalid before https://git.kernel.org/linus/778f7c194b1dac351d345ce723f8747026092949
    if [[ "$(scripts_config -s PCI_EXYNOS)" = "m" ]] &&
        grep -q 'bool "Samsung Exynos PCIe controller"' "${LINUX_SRC}"/drivers/pci/controller/dwc/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e PCI_EXYNOS)
    fi

    # CONFIG_PCI_MESON as a module is invalid before https://git.kernel.org/linus/a98d2187efd9e6d554efb50e3ed3a2983d340fe5
    if [[ "$(scripts_config -s PCI_MESON)" = "m" ]] &&
        grep -q 'bool "MESON PCIe controller"' "${LINUX_SRC}"/drivers/pci/controller/dwc/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e PCI_MESON)
    fi

    # CONFIG_POWER_RESET_SC27XX as a module is invalid before https://git.kernel.org/linus/f78c55e3b4806974f7d590b2aab8683232b7bd25
    if [[ "$(scripts_config -s POWER_RESET_SC27XX)" = "m" ]] &&
        grep -q 'bool "Spreadtrum SC27xx PMIC power-off driver"' "${LINUX_SRC}"/drivers/power/reset/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e POWER_RESET_SC27XX)
    fi

    # CONFIG_PROC_THERMAL_MMIO_RAPL as a module is invalid before https://git.kernel.org/linus/a5923b6c3137b9d4fc2ea1c997f6e4d51ac5d774
    if [[ "$(scripts_config -s PROC_THERMAL_MMIO_RAPL)" = "m" ]] &&
        grep -oPqz '(?s)config PROC_THERMAL_MMIO_RAPL.*?bool' "${LINUX_SRC}"/drivers/thermal/intel/int340x_thermal/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e PROC_THERMAL_MMIO_RAPL)
    fi

    # CONFIG_PVPANIC as a module is invalid after https://git.kernel.org/gregkh/char-misc/c/6861d27cf590d20a95b5d0724ac3768583b62947
    if [[ "$(scripts_config -s PVPANIC)" = "m" && -f ${LINUX_SRC}/drivers/misc/pvpanic/Kconfig ]]; then
        SCRIPTS_CONFIG_ARGS+=(-e PVPANIC -m PVPANIC_MMIO)
    fi

    # CONFIG_MCTP as a module is invalid after https://git.kernel.org/linus/78476d315e190533757ab894255c4f2c2f254bce
    if [[ "$(scripts_config -s MCTP)" = "m" ]] &&
        grep -q 'bool "MCTP core protocol support"' "${LINUX_SRC}"/net/mctp/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e MCTP)
    fi

    # CONFIG_QCOM_RPMPD as a module is invalid before https://git.kernel.org/linus/f29808b2fb85a7ff2d4830aa1cb736c8c9b986f4
    if [[ "$(scripts_config -s QCOM_RPMPD)" = "m" ]] &&
        grep -q 'bool "Qualcomm RPM Power domain driver"' "${LINUX_SRC}"/drivers/soc/qcom/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e QCOM_RPMPD)
    fi

    # CONFIG_QCOM_RPMHPD as a module is invalid before https://git.kernel.org/linus/d4889ec1fc6ac6321cc1e8b35bb656f970926a09
    if [[ "$(scripts_config -s QCOM_RPMHPD)" = "m" ]] &&
        grep -q 'bool "Qualcomm RPMh Power domain driver"' "${LINUX_SRC}"/drivers/soc/qcom/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e QCOM_RPMHPD)
    fi

    # CONFIG_RESET_MESON as a module is invalid before https://git.kernel.org/linus/3bfe8933f9d187f93f0d0910b741a59070f58c4c
    if [[ "$(scripts_config -s RESET_MESON)" = "m" ]] &&
        grep -q 'bool "Meson Reset Driver" if COMPILE_TEST' "${LINUX_SRC}"/drivers/reset/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e RESET_MESON)
    fi

    # CONFIG_RTW88_8822BE as a module is invalid before https://git.kernel.org/linus/416e87fcc780cae8d72cb9370fa0f46007faa69a
    if [[ "$(scripts_config -s RTW88_8822BE)" = "m" ]] &&
        grep -q 'bool "Realtek 8822BE PCI wireless network adapter"' "${LINUX_SRC}"/drivers/net/wireless/realtek/rtw88/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e RTW88_8822BE)
    fi

    # CONFIG_RTW88_8822CE as a module is invalid before https://git.kernel.org/linus/ba0fbe236fb8a7b992e82d6eafb03a600f5eba43
    if [[ "$(scripts_config -s RTW88_8822CE)" = "m" ]] &&
        grep -q 'bool "Realtek 8822CE PCI wireless network adapter"' "${LINUX_SRC}"/drivers/net/wireless/realtek/rtw88/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e RTW88_8822CE)
    fi

    # CONFIG_SERIAL_LANTIQ as a module is invalid before https://git.kernel.org/linus/ad406341bdd7d22ba9497931c2df5dde6bb9440e
    if [[ "$(scripts_config -s SERIAL_LANTIQ)" = "m" ]] &&
        grep -q 'bool "Lantiq serial driver"' "${LINUX_SRC}"/drivers/tty/serial/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e SERIAL_LANTIQ)
    fi

    # CONFIG_SND_SOC_SPRD_MCDT as a module is invalid before https://git.kernel.org/linus/fd357ec595d36676c239d8d16706a270a961ac32
    if [[ "$(scripts_config -s SND_SOC_SPRD_MCDT)" = "m" ]] &&
        grep -q 'bool "Spreadtrum multi-channel data transfer support"' "${LINUX_SRC}"/sound/soc/sprd/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e SND_SOC_SPRD_MCDT)
    fi

    # CONFIG_TEGRA124_EMC as a module is invalid before https://git.kernel.org/linus/281462e593483350d8072a118c6e072c550a80fa
    if [[ "$(scripts_config -s TEGRA124_EMC)" = "m" ]] &&
        grep -q 'bool "NVIDIA Tegra124 External Memory Controller driver"' "${LINUX_SRC}"/drivers/memory/tegra/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e TEGRA124_EMC)
    fi

    # CONFIG_TEGRA20_EMC as a module is invalid before https://git.kernel.org/linus/0260979b018faaf90ff5a7bb04ac3f38e9dee6e3
    if [[ "$(scripts_config -s TEGRA20_EMC)" = "m" ]] &&
        grep -q 'bool "NVIDIA Tegra20 External Memory Controller driver"' "${LINUX_SRC}"/drivers/memory/tegra/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e TEGRA20_EMC)
    fi

    # CONFIG_TEGRA30_EMC as a module is invalid before https://git.kernel.org/linus/0c56eda86f8cad705d7d14e81e0e4efaeeaf4613
    if [[ "$(scripts_config -s TEGRA30_EMC)" = "m" ]] &&
        grep -q 'bool "NVIDIA Tegra30 External Memory Controller driver"' "${LINUX_SRC}"/drivers/memory/tegra/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e TEGRA30_EMC)
    fi

    # CONFIG_TI_CPTS as a module is invalid before https://git.kernel.org/linus/92db978f0d686468e527d49268e7c7e8d97d334b
    if [[ "$(scripts_config -s TI_CPTS)" = "m" ]] &&
        grep -q 'bool "TI Common Platform Time Sync' "${LINUX_SRC}"/drivers/net/ethernet/ti/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e TI_CPTS)
    fi

    [[ -n "${SCRIPTS_CONFIG_ARGS[*]}" ]] && scripts_config "${SCRIPTS_CONFIG_ARGS[@]}"
    LOG_COMMENT=""
    for DISABLED_CONFIG in "${DISABLED_CONFIGS[@]}"; do
        LOG_COMMENT+=" + CONFIG_${DISABLED_CONFIG}=n"
        case ${DISABLED_CONFIG} in
            BPF_PRELOAD)
                LOG_COMMENT+=" (https://github.com/ClangBuiltLinux/linux/issues/1433)"
                ;;
            DEBUG_INFO_BTF)
                command -v pahole &>/dev/null || LOG_COMMENT+=" (pahole is not installed)"
                ;;
        esac
    done

}

function swap_endianness() {
    case "${1:?}" in
        b2l) B_OPT=-d && L_OPT=-e ;;
        l2b) B_OPT=-e && L_OPT=-d ;;
        *) return 1 ;;
    esac

    scripts_config \
        "${B_OPT}" CPU_BIG_ENDIAN \
        "${L_OPT}" CPU_LITTLE_ENDIAN
}

function results() {
    if [[ -n ${QEMU} && ${KRNL_RC} -ne 0 ]]; then
        RESULT=skipped
    elif [[ ${1} -eq 0 ]]; then
        RESULT=successful
    else
        RESULT=failed
    fi
    printf "%s" "${RESULT}"
    if [[ -n ${QEMU} ]]; then
        printf '\n'
    else
        printf " in %s" "$(print_time "${KMAKE_START}" "${KMAKE_END}")"
        printf '\n'
        [[ ${RESULT} = "failed" ]] && grep "error:\|warning:\|undefined" "${BLD_LOG_DIR}/${KLOG}.log"
    fi
    printf '\n'
}

# Build arm32 kernels
function build_arm32_kernels() {
    local CROSS_COMPILE KMAKE_ARGS LOG_COMMENT
    CROSS_COMPILE=arm-linux-gnueabi-
    KMAKE_ARGS=(
        ARCH=arm
        CROSS_COMPILE="${CROSS_COMPILE}"
    )
    [[ ${LLVM_VER_CODE} -ge 130000 && ${LNX_VER_CODE} -ge 513000 ]] && KMAKE_ARGS+=(LLVM_IAS=1)

    header "Building arm32 kernels"

    print_binutils_info
    echo

    # Upstream
    KLOG=arm32-multi_v5_defconfig
    kmake "${KMAKE_ARGS[@]}" distclean multi_v5_defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/954
    if [[ ${LLVM_VER_CODE} -lt 100001 ]]; then
        LOG_COMMENT=" + CONFIG_TRACING=n + CONFIG_OPROFILE=n + CONFIG_RCU_TRACE=n (https://github.com/ClangBuiltLinux/linux/issues/954)"
        scripts_config -d CONFIG_TRACING -d CONFIG_OPROFILE -d CONFIG_RCU_TRACE
    else
        unset LOG_COMMENT
    fi
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "arm32 multi_v5_defconfig${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm32_v5
    log "arm32 multi_v5_defconfig${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    KLOG=arm32-aspeed_g5_defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/732
    [[ ${LLVM_VER_CODE} -lt 110000 ]] && ARM32_V6_LD=${CROSS_COMPILE}ld
    kmake "${KMAKE_ARGS[@]}" ${ARM32_V6_LD:+LD=${ARM32_V6_LD}} distclean aspeed_g5_defconfig all
    KRNL_RC=${?}
    log "arm32 aspeed_g5_defconfig $(results "${KRNL_RC}")"
    qemu_boot_kernel arm32_v6
    log "arm32 aspeed_g5_defconfig qemu boot $(QEMU=1 results "${?}")"

    KLOG=arm32-multi_v7_defconfig
    kmake "${KMAKE_ARGS[@]}" distclean multi_v7_defconfig all
    KRNL_RC=${?}
    log "arm32 multi_v7_defconfig $(results "${KRNL_RC}")"
    qemu_boot_kernel arm32_v7
    log "arm32 multi_v7_defconfig qemu boot $(QEMU=1 results "${?}")"

    if grep -q "select HAVE_FUTEX_CMPXCHG if FUTEX" "${LINUX_SRC}"/arch/arm/Kconfig; then
        KLOG=arm32-multi_v7_defconfig-thumb2
        kmake "${KMAKE_ARGS[@]}" LLVM_IAS=0 distclean multi_v7_defconfig
        scripts_config -e THUMB2_KERNEL
        kmake "${KMAKE_ARGS[@]}" LLVM_IAS=0 olddefconfig all
        KRNL_RC=${?}
        log "arm32 multi_v7_defconfig + CONFIG_THUMB2_KERNEL=y $(results "${KRNL_RC}")"
        qemu_boot_kernel arm32_v7
        log "arm32 multi_v7_defconfig + CONFIG_THUMB2_KERNEL=y qemu boot $(QEMU=1 results "${?}")"
    fi

    ${DEFCONFIGS_ONLY} && return 0

    CONFIGS_TO_DISABLE=()
    grep -oPqz '(?s)depends on ARCH_SUPPORTS_BIG_ENDIAN.*?depends on \!LD_IS_LLD' "${LINUX_SRC}"/arch/arm/mm/Kconfig || CONFIGS_TO_DISABLE+=(CONFIG_CPU_BIG_ENDIAN)
    if [[ -n ${CONFIGS_TO_DISABLE[*]} ]]; then
        CONFIG_FILE=$(mktemp --suffix=.config)
        LOG_COMMENT=""
        for CONFIG_TO_DISABLE in "${CONFIGS_TO_DISABLE[@]}"; do
            CONFIG_VALUE=${CONFIG_TO_DISABLE}=n
            echo "${CONFIG_VALUE}" >>"${CONFIG_FILE}"
            LOG_COMMENT+=" + ${CONFIG_VALUE}"
        done
    fi
    KLOG=arm32-allmodconfig
    kmake "${KMAKE_ARGS[@]}" ${CONFIG_FILE:+KCONFIG_ALLCONFIG=${CONFIG_FILE}} distclean allmodconfig all
    log "arm32 allmodconfig${LOG_COMMENT} $(results "${?}")"

    KLOG=arm32-allnoconfig
    kmake "${KMAKE_ARGS[@]}" distclean allnoconfig all
    log "arm32 allnoconfig $(results "${?}")"

    KLOG=arm32-tinyconfig
    kmake "${KMAKE_ARGS[@]}" distclean tinyconfig all
    log "arm32 tinyconfig $(results "${?}")"

    # Alpine Linux
    KLOG=arm32-alpine
    setup_config alpine/armv7.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "armv7 alpine config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm32_v7
    log "armv7 alpine config qemu boot $(QEMU=1 results "${?}")"

    # Arch Linux ARM
    KLOG=arm32-v5-archlinux
    setup_config archlinux/armv5.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "armv5 archlinux config${LOG_COMMENT} $(results "${?}")"

    KLOG=arm32-v7-archlinux
    setup_config archlinux/armv7.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "armv7 archlinux config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm32_v7
    log "armv7 archlinux config qemu boot $(QEMU=1 results "${?}")"

    # Debian
    KLOG=arm32-debian
    setup_config debian/armmp.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "arm32 debian config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm32_v7
    log "arm32 debian config qemu boot $(QEMU=1 results "${?}")"

    # Fedora
    KLOG=arm32-fedora
    setup_config fedora/armv7hl.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "armv7hl fedora config${LOG_COMMENT} $(results "${?}")"

    # OpenSUSE
    KLOG=arm32-opensuse
    setup_config opensuse/armv7hl.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "armv7hl opensuse config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm32_v7
    log "armv7hl opensuse config qemu boot $(QEMU=1 results "${?}")"
}

# Build arm64 kernels
function build_arm64_kernels() {
    local KMAKE_ARGS
    CROSS_COMPILE=aarch64-linux-gnu-
    KMAKE_ARGS=(
        ARCH=arm64
        CROSS_COMPILE="${CROSS_COMPILE}"
    )
    [[ ${LNX_VER_CODE} -ge 510000 && ${LLVM_VER_CODE} -ge 110000 ]] && KMAKE_ARGS+=(LLVM_IAS=1)

    header "Building arm64 kernels"

    print_binutils_info
    echo

    # Upstream
    KLOG=arm64-defconfig
    kmake "${KMAKE_ARGS[@]}" distclean defconfig all
    KRNL_RC=${?}
    log "arm64 defconfig $(results "${KRNL_RC}")"
    qemu_boot_kernel arm64
    log "arm64 defconfig qemu boot $(QEMU=1 results "${?}")"

    if [[ ${LLVM_VER_CODE} -ge 130000 ]]; then
        KLOG=arm64be-defconfig
        kmake "${KMAKE_ARGS[@]}" distclean defconfig
        swap_endianness l2b
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
        KRNL_RC=${?}
        log "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y $(results "${KRNL_RC}")"
        qemu_boot_kernel arm64be
        log "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y qemu boot $(QEMU=1 results "${?}")"
    fi

    if grep -q "config LTO_CLANG_THIN" "${LINUX_SRC}"/arch/Kconfig && [[ ${LLVM_VER_CODE} -ge 110000 ]]; then
        KLOG=arm64-defconfig-lto
        kmake "${KMAKE_ARGS[@]}" distclean defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
        KRNL_RC=${?}
        log "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "${KRNL_RC}")"
        qemu_boot_kernel arm64
        log "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y $(QEMU=1 results "${?}")"
    fi

    if grep -q "config CFI_CLANG" "${LINUX_SRC}"/arch/Kconfig && [[ ${LLVM_VER_CODE} -ge 120000 ]]; then
        KLOG=arm64-defconfig-lto-scs-cfi
        kmake "${KMAKE_ARGS[@]}" distclean defconfig
        TMP_CONFIG=$(mktemp --suffix=.config)
        cat <<EOF >"${TMP_CONFIG}"
CONFIG_CFI_CLANG=y
CONFIG_LTO_CLANG_THIN=y
CONFIG_LTO_NONE=n
CONFIG_SHADOW_CALL_STACK=y
EOF
        merge_config "${TMP_CONFIG}"
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
        KRNL_RC=${?}
        log "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y $(results "${KRNL_RC}")"
        qemu_boot_kernel arm64
        log "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y $(QEMU=1 results "${?}")"
        rm "${TMP_CONFIG}"
    fi

    ${DEFCONFIGS_ONLY} && return 0

    CONFIGS_TO_DISABLE=()
    grep -q 'prompt "Endianness"' "${LINUX_SRC}"/arch/arm64/Kconfig || CONFIGS_TO_DISABLE+=(CONFIG_CPU_BIG_ENDIAN)
    # https://github.com/ClangBuiltLinux/linux/issues/1116
    [[ -f ${LINUX_SRC}/drivers/media/platform/ti-vpe/cal-camerarx.c && ${LLVM_VER_CODE} -lt 110000 ]] && CONFIGS_TO_DISABLE+=(CONFIG_VIDEO_TI_CAL)
    # https://github.com/ClangBuiltLinux/linux/issues/1243
    GPI_C=${LINUX_SRC}/drivers/dma/qcom/gpi.c
    { [[ -f ${GPI_C} ]] && ! grep -oPqz '(?s)static __always_inline void.*?gpi_update_reg' "${GPI_C}"; } && CONFIGS_TO_DISABLE+=(CONFIG_QCOM_GPI_DMA)
    if [[ -n ${CONFIGS_TO_DISABLE[*]} ]]; then
        CONFIG_FILE=$(mktemp --suffix=.config)
        LOG_COMMENT=""
        for CONFIG_TO_DISABLE in "${CONFIGS_TO_DISABLE[@]}"; do
            CONFIG_VALUE=${CONFIG_TO_DISABLE}=n
            echo "${CONFIG_VALUE}" >>"${CONFIG_FILE}"
            LOG_COMMENT+=" + ${CONFIG_VALUE}"
        done
    fi
    KLOG=arm64-allmodconfig
    kmake "${KMAKE_ARGS[@]}" ${CONFIG_FILE:+KCONFIG_ALLCONFIG=${CONFIG_FILE}} distclean allmodconfig all
    log "arm64 allmodconfig${LOG_COMMENT} $(results "${?}")"

    KLOG=arm64-allnoconfig
    kmake "${KMAKE_ARGS[@]}" distclean allnoconfig all
    log "arm64 allnoconfig $(results "${?}")"

    KLOG=arm64-tinyconfig
    kmake "${KMAKE_ARGS[@]}" distclean tinyconfig all
    log "arm64 tinyconfig $(results "${?}")"

    # Alpine Linux
    KLOG=arm64-alpine
    setup_config alpine/aarch64.config
    # https://lore.kernel.org/r/20210413200057.ankb4e26ytgal7ev@archlinux-ax161/
    scripts_config -e PERF_EVENTS
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "arm64 alpine config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm64
    log "arm64 alpine config qemu boot $(QEMU=1 results "${?}")"

    # Arch Linux ARM
    KLOG=arm64-archlinux
    setup_config archlinux/aarch64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "arm64 archlinux config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm64
    log "arm64 archlinux config qemu boot $(QEMU=1 results "${?}")"

    # Debian
    KLOG=arm64-debian
    setup_config debian/arm64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "arm64 debian config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm64
    log "arm64 debian config qemu boot $(QEMU=1 results "${?}")"

    # Fedora
    KLOG=arm64-fedora
    LOG_COMMENT=""
    setup_config fedora/aarch64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "arm64 fedora config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm64
    log "arm64 fedora config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    # OpenSUSE
    KLOG=arm64-opensuse
    setup_config opensuse/arm64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "arm64 opensuse config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel arm64
    log "arm64 opensuse config qemu boot $(QEMU=1 results "${?}")"
}

# Build hexagon kernels
function build_hexagon_kernels() {
    KMAKE_ARGS=(
        ARCH=hexagon
        CROSS_COMPILE=hexagon-linux-gnu-
        LLVM_IAS=1
    )

    # Hexagon was broken without some fixes
    if ! grep -q "KBUILD_CFLAGS += -mlong-calls" "${LINUX_SRC}"/arch/hexagon/Makefile || ! [[ -f ${LINUX_SRC}/arch/hexagon/lib/divsi3.S ]]; then
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
    KLOG=hexagon-defconfig
    kmake "${KMAKE_ARGS[@]}" distclean defconfig all
    KRNL_RC=${?}
    log "hexagon defconfig $(results "${KRNL_RC}")"

    ${DEFCONFIGS_ONLY} && return 0

    if grep -Fq "EXPORT_SYMBOL(__raw_readsw)" "${LINUX_SRC}"/arch/hexagon/lib/io.c; then
        KLOG=hexagon-allmodconfig
        kmake "${KMAKE_ARGS[@]}" distclean allmodconfig all
        KRNL_RC=${?}
        log "hexagon allmodconfig $(results "${KRNL_RC}")"
    fi
}

# Build mips kernels
function build_mips_kernels() {
    local CROSS_COMPILE KMAKE_ARGS
    CROSS_COMPILE=mipsel-linux-gnu-
    KMAKE_ARGS=(
        ARCH=mips
        CROSS_COMPILE="${CROSS_COMPILE}"
    )

    header "Building mips kernels"

    print_binutils_info
    echo

    # Upstream
    KLOG=mipsel-malta
    kmake "${KMAKE_ARGS[@]}" distclean malta_defconfig
    scripts_config -e BLK_DEV_INITRD
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y $(results "${KRNL_RC}")"
    qemu_boot_kernel mipsel
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y qemu boot $(QEMU=1 results "${?}")"

    KLOG=mipsel-malta-kaslr
    kmake "${KMAKE_ARGS[@]}" distclean malta_defconfig
    scripts_config \
        -e BLK_DEV_INITRD \
        -e RELOCATABLE \
        --set-val RELOCATION_TABLE_SIZE 0x00200000 \
        -e RANDOMIZE_BASE
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_RANDOMIZE_BASE=y $(results "${KRNL_RC}")"
    qemu_boot_kernel mipsel
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_RANDOMIZE_BASE=y qemu boot $(QEMU=1 results "${?}")"

    # https://github.com/ClangBuiltLinux/linux/issues/1025
    KLOG=mips-malta
    [[ -f ${LINUX_SRC}/arch/mips/vdso/Kconfig && ${LLVM_VER_CODE} -lt 130000 ]] && MIPS_BE_LD=${CROSS_COMPILE}ld
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean malta_defconfig
    scripts_config -e BLK_DEV_INITRD
    swap_endianness l2b
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} olddefconfig all
    KRNL_RC=${?}
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_CPU_BIG_ENDIAN=y $(results "${KRNL_RC}")"
    qemu_boot_kernel mips
    log "mips malta_defconfig + CONFIG_BLK_DEV_INITRD=y + CONFIG_CPU_BIG_ENDIAN=y qemu boot $(QEMU=1 results "${?}")"

    KLOG=mips-32r1
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean 32r1_defconfig all
    log "mips 32r1_defconfig $(results "${?}")"

    KLOG=mips-32r1el
    kmake "${KMAKE_ARGS[@]}" distclean 32r1el_defconfig all
    log "mips 32r1el_defconfig $(results "${?}")"

    KLOG=mips-32r2
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean 32r2_defconfig all
    log "mips 32r2_defconfig $(results "${?}")"

    KLOG=mips-32r2el
    kmake "${KMAKE_ARGS[@]}" distclean 32r2el_defconfig all
    log "mips 32r2el_defconfig $(results "${?}")"

    # https://github.com/ClangBuiltLinux/linux/issues/1241
    KLOG=mips-32r2
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean 32r2_defconfig all
    log "mips 32r2_defconfig $(results "${?}")"

    KLOG=mips-32r2el
    kmake "${KMAKE_ARGS[@]}" distclean 32r2el_defconfig all
    log "mips 32r2el_defconfig $(results "${?}")"

    if [[ ${LLVM_VER_CODE} -ge 120000 ]]; then
        KLOG=mips-32r6
        kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean 32r6_defconfig all
        log "mips 32r6_defconfig $(results "${?}")"

        KLOG=mips-32r6el
        kmake "${KMAKE_ARGS[@]}" distclean 32r6el_defconfig all
        log "mips 32r6el_defconfig $(results "${?}")"
    fi

    KLOG=mips-allnoconfig
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean allnoconfig all
    log "mips allnoconfig $(results "${?}")"

    KLOG=mips-tinyconfig
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean tinyconfig all
    log "mips tinyconfig $(results "${?}")"
}

# Build powerpc kernels
function build_powerpc_kernels() {
    local CROSS_COMPILE CTOD KMAKE_ARGS LOG_COMMENT
    CROSS_COMPILE=powerpc-linux-gnu-
    KMAKE_ARGS=(
        ARCH=powerpc
        CROSS_COMPILE="${CROSS_COMPILE}"
    )

    header "Building powerpc kernels"

    print_binutils_info
    echo

    # Upstream
    # https://llvm.org/pr46186
    if ! grep -q 'case 4: __put_user_asm_goto(x, ptr, label, "stw"); break;' "${LINUX_SRC}"/arch/powerpc/include/asm/uaccess.h || [[ ${LLVM_VER_CODE} -ge 110000 ]]; then
        KLOG=powerpc-ppc44x_defconfig
        kmake "${KMAKE_ARGS[@]}" distclean ppc44x_defconfig all uImage
        KRNL_RC=${?}
        log "powerpc ppc44x_defconfig $(results "${KRNL_RC}")"
        qemu_boot_kernel ppc32
        log "powerpc ppc44x_defconfig qemu boot $(QEMU=1 results "${?}")"

        KLOG=powerpc-allnoconfig
        kmake "${KMAKE_ARGS[@]}" distclean allnoconfig all
        log "powerpc allnoconfig $(results "${?}")"

        KLOG=powerpc-tinyconfig
        kmake "${KMAKE_ARGS[@]}" distclean tinyconfig all
        log "powerpc tinyconfig $(results "${?}")"
    else
        log "powerpc 32-bit configs skipped (https://llvm.org/pr46186)"
    fi

    KLOG=powerpc64-pseries_defconfig
    PSERIES_TARGETS=(pseries_defconfig)
    # https://github.com/ClangBuiltLinux/linux/issues/1292
    if ! grep -q "noinline_for_stack void byteswap_pt_regs" "${LINUX_SRC}"/arch/powerpc/kvm/book3s_hv_nested.c && [[ ${LLVM_VER_CODE} -ge 120000 ]]; then
        CTOE=CONFIG_PPC_DISABLE_WERROR
        if [[ -f ${LINUX_SRC}/arch/powerpc/configs/disable-werror.config ]]; then
            PSERIES_TARGETS+=(disable-werror.config all)
        else
            SC_DWERROR=true
        fi
        LOG_COMMENT=" + ${CTOE}=y"
    else
        PSERIES_TARGETS+=(all)
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/602
    kmake "${KMAKE_ARGS[@]}" LD=${CROSS_COMPILE}ld distclean "${PSERIES_TARGETS[@]}"
    KRNL_RC=${?}
    if ${SC_DWERROR:=false}; then
        scripts_config -e ${CTOE}
        kmake "${KMAKE_ARGS[@]}" LD=${CROSS_COMPILE}ld olddefconfig all
        KRNL_RC=${?}
    fi
    log "powerpc pseries_defconfig${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel ppc64
    log "powerpc pseries_defconfig qemu boot${LOG_COMMENT} $(QEMU=1 results "${?}")"

    CROSS_COMPILE=powerpc64-linux-gnu-
    KMAKE_ARGS=(
        ARCH=powerpc
        CROSS_COMPILE="${CROSS_COMPILE}"
    )

    KLOG=powerpc64le-powernv_defconfig
    kmake "${KMAKE_ARGS[@]}" distclean powernv_defconfig all
    KRNL_RC=${?}
    log "powerpc powernv_defconfig $(results "${KRNL_RC}")"
    qemu_boot_kernel ppc64le
    log "powerpc powernv_defconfig qemu boot $(QEMU=1 results "${?}")"

    PPC64LE_ARGS=()
    # https://github.com/ClangBuiltLinux/linux/issues/666
    [[ ${LLVM_VER_CODE} -lt 110000 ]] && PPC64LE_ARGS+=(OBJDUMP="${CROSS_COMPILE}"objdump)
    # https://github.com/ClangBuiltLinux/linux/issues/811
    # shellcheck disable=SC2016
    grep -Fq 'LDFLAGS_vmlinux-$(CONFIG_RELOCATABLE) += -z notext' "${LINUX_SRC}"/arch/powerpc/Makefile || PPC64LE_ARGS+=(LD="${CROSS_COMPILE}"ld)

    KLOG=powerpc64le-defconfig
    kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" distclean ppc64le_defconfig all
    log "powerpc ppc64le_defconfig $(results "${?}")"

    ${DEFCONFIGS_ONLY} && return 0

    # Debian
    KLOG=powerpc64le-debian
    setup_config debian/powerpc64le.config
    kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "ppc64le debian config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel ppc64le
    log "ppc64le debian config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    # Fedora
    KLOG=powerpc64le-fedora
    setup_config fedora/ppc64le.config
    kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "ppc64le fedora config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel ppc64le
    log "ppc64le fedora config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    # OpenSUSE
    # https://github.com/ClangBuiltLinux/linux/issues/1160
    if ! grep -q "depends on PPC32 || COMPAT" "${LINUX_SRC}"/arch/powerpc/platforms/Kconfig.cputype || [[ ${LLVM_VER_CODE} -ge 120000 ]]; then
        KLOG=powerpc64le-opensuse
        setup_config opensuse/ppc64le.config
        kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" olddefconfig all
        KRNL_RC=${?}
        log "ppc64le opensuse config${LOG_COMMENT} $(results "${KRNL_RC}")"
        qemu_boot_kernel ppc64le
        log "ppc64le opensuse config qemu boot $(QEMU=1 results "${?}")"
    else
        log "ppc64le opensuse config skipped (https://github.com/ClangBuiltLinux/linux/issues/1160)"
    fi
}

# Build riscv kernels
function build_riscv_kernels() {
    local KMAKE_ARGS
    CROSS_COMPILE=riscv64-linux-gnu-
    KMAKE_ARGS=(
        ARCH=riscv
        CROSS_COMPILE="${CROSS_COMPILE}"
    )

    # riscv did not build properly for Linux prior to 5.7 and there is an
    # inordinate amount of spam about '-save-restore' before LLVM 11: https://llvm.org/pr44853
    if [[ ${LNX_VER_CODE} -lt 507000 || ${LLVM_VER_CODE} -lt 110000 ]]; then
        header "Skipping riscv kernels"
        echo "Reasons:"
        if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
            echo
            echo "RISC-V needs the following fixes from Linux 5.7 to build properly:"
            echo
            echo '  * https://git.kernel.org/linus/52e7c52d2ded5908e6a4f8a7248e5fa6e0d6809a'
            echo '  * https://git.kernel.org/linus/fdff9911f266951b14b20e25557278b5b3f0d90d'
            echo '  * https://git.kernel.org/linus/abc71bf0a70311ab294f97a7f16e8de03718c05a'
            echo
            echo "Provide a kernel tree with Linux 5.7 or newer to build RISC-V kernels"
        fi
        if [[ ${LLVM_VER_CODE} -lt 110000 ]]; then
            echo
            echo "RISC-V needs a patch from LLVM 11 to build without a massive amount of warnings."
            echo
            echo "https://github.com/llvm/llvm-project/commit/07f7c00208b393296f8f27d6cd3cec2b11d86fd8"
        fi
        return 0
    fi

    header "Building riscv kernels"

    print_binutils_info
    echo

    KLOG=riscv-defconfig
    LOG_COMMENT=""
    # https://github.com/ClangBuiltLinux/linux/issues/1020
    if [[ ${LLVM_VER_CODE} -lt 130000 ]] || ! grep -q 'mno-relax' "${LINUX_SRC}"/arch/riscv/Makefile; then
        RISCV_LD=riscv64-linux-gnu-ld
    fi
    kmake "${KMAKE_ARGS[@]}" ${RISCV_LD:+LD=${RISCV_LD}} LLVM_IAS=1 distclean defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/1143
    if [[ ${LLVM_VER_CODE} -lt 130000 ]] && grep -q "config EFI" "${LINUX_SRC}"/arch/riscv/Kconfig; then
        LOG_COMMENT+=" + CONFIG_EFI=n (https://github.com/ClangBuiltLinux/linux/issues/1143)"
        scripts_config -d CONFIG_EFI
    fi
    kmake "${KMAKE_ARGS[@]}" ${RISCV_LD:+LD=${RISCV_LD}} LLVM_IAS=1 olddefconfig all
    KRNL_RC=${?}
    log "riscv defconfig${LOG_COMMENT} $(results "${KRNL_RC}")"
    # https://github.com/ClangBuiltLinux/linux/issues/867
    if grep -q "(long)__old" "${LINUX_SRC}"/arch/riscv/include/asm/cmpxchg.h; then
        qemu_boot_kernel riscv
        log "riscv defconfig qemu boot $(QEMU=1 results "${?}")"
    fi

    # https://github.com/ClangBuiltLinux/linux/issues/999
    if [[ ${LNX_VER_CODE} -gt 508000 ]] && grep -q 'mno-relax' "${LINUX_SRC}"/arch/riscv/Makefile; then
        [[ ${LLVM_VER_CODE} -ge 130000 ]] && KMAKE_ARGS+=(LLVM_IAS=1)
        KLOG=riscv-allmodconfig
        kmake "${KMAKE_ARGS[@]}" LLVM_IAS=1 distclean allmodconfig all
        KRNL_RC=${?}

        KLOG=riscv-opensuse
        setup_config opensuse/riscv64.config
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
        KRNL_RC=${?}
        log "riscv opensuse config${LOG_COMMENT} $(results "${KRNL_RC}")"
        qemu_boot_kernel riscv
        log "riscv opensuse config qemu boot $(QEMU=1 results "${?}")"
    fi
}

# Build s390x kernels
# Non-working LLVM tools outline:
#   * ld.lld
#   * llvm-objcopy
#   * llvm-objdump
function build_s390x_kernels() {
    local CROSS_COMPILE CTOD KMAKE_ARGS LOG_COMMENT
    CROSS_COMPILE=s390x-linux-gnu-
    # For some reason, -Waddress-of-packed-member does not get disabled...
    # Disable it so that real issues/errors can be found
    # TODO: Investigate and file a bug or fix
    KMAKE_ARGS=(
        ARCH=s390
        CROSS_COMPILE="${CROSS_COMPILE}"
        KCFLAGS=-Wno-address-of-packed-member
        LD="${CROSS_COMPILE}"ld
        OBJCOPY="${CROSS_COMPILE}"objcopy
        OBJDUMP="${CROSS_COMPILE}"objdump
    )

    # s390 did not build properly until Linux 5.6
    if [[ ${LNX_VER_CODE} -lt 506000 ]]; then
        header "Skipping s390x kernels"
        echo "Reason: s390 kernels did not build properly until Linux 5.6"
        echo "        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/"
        return 0
    fi

    header "Building s390x kernels"

    print_binutils_info
    echo

    # Upstream
    KLOG=s390x-defconfig
    kmake "${KMAKE_ARGS[@]}" distclean defconfig all
    KRNL_RC=${?}
    log "s390x defconfig $(results "${KRNL_RC}")"
    qemu_boot_kernel s390
    log "s390x defconfig qemu boot $(QEMU=1 results "${?}")"

    ${DEFCONFIGS_ONLY} && return 0

    KLOG=s390x-allnoconfig
    kmake "${KMAKE_ARGS[@]}" distclean allnoconfig all
    log "s390x allnoconfig $(results "${?}")"

    KLOG=s390x-tinyconfig
    kmake "${KMAKE_ARGS[@]}" distclean tinyconfig all
    log "s390x tinyconfig $(results "${?}")"

    if [[ ${LLVM_VER_CODE} -ge 120000 ]]; then
        KLOG=s390x-allmodconfig
        LOG_COMMENT=""
        kmake "${KMAKE_ARGS[@]}" distclean allmodconfig
        # https://github.com/ClangBuiltLinux/linux/issues/1213
        if ! grep -q "config UBSAN_MISC" "${LINUX_SRC}"/lib/Kconfig.ubsan && ! grep -q "depends on HAS_IOMEM" "${LINUX_SRC}"/init/Kconfig; then
            CTOD=CONFIG_UBSAN_TRAP
            LOG_COMMENT+=" + ${CTOD}=n (https://github.com/ClangBuiltLinux/linux/issues/1213)"
            scripts_config -d ${CTOD}
        fi
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
        log "s390x allmodconfig${LOG_COMMENT} $(results "${?}")"
    else
        log "s390x allmodconfig skipped (https://reviews.llvm.org/D90065)"
    fi

    # Debian
    KLOG=s390x-debian
    setup_config debian/s390x.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "s390x debian config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel s390
    log "s390x debian config qemu boot $(QEMU=1 results "${?}")"

    # Fedora
    KLOG=s390x-fedora
    LOG_COMMENT=""
    setup_config fedora/s390x.config
    if grep -Eq '"(o|n|x)i.*%0,%b1.*n"' "${LINUX_SRC}"/arch/s390/include/asm/bitops.h; then
        LOG_COMMENT+=" + CONFIG_MARCH_Z196=y (https://github.com/ClangBuiltLinux/linux/issues/1264)"
        scripts_config -d MARCH_ZEC12 -e MARCH_Z196
    fi
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "s390x fedora config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel s390
    log "s390x fedora config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    # OpenSUSE
    KLOG=s390x-opensuse
    setup_config opensuse/s390x.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    KRNL_RC=${?}
    log "s390x opensuse config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel s390
    log "s390x opensuse config qemu boot $(QEMU=1 results "${?}")"
}

# Build x86 kernels
function build_x86_kernels() {
    # x86 did not build properly until Linux 5.9
    if [[ ${LNX_VER_CODE} -lt 509000 ]]; then
        header "Skipping x86 kernels"
        echo "Reason: x86 kernels did not build properly until Linux 5.9"
        echo "        https://github.com/ClangBuiltLinux/linux/issues/194"
        return 0
    elif [[ ${LLVM_VER_CODE} -gt 120000 ]] &&
        ! grep -q "R_386_PLT32:" "${LINUX_SRC}"/arch/x86/tools/relocs.c; then
        header "Skipping x86 kernels"
        echo "Reason: x86 kernels do not build properly with LLVM 12.0.0+ without R_386_PLT32 handling"
        echo "        https://github.com/ClangBuiltLinux/linux/issues/1210"
        return 0
    fi

    header "Building x86 kernels"

    unset CROSS_COMPILE
    print_binutils_info
    echo

    # Upstream
    KLOG=i386-defconfig
    kmake distclean i386_defconfig all
    KRNL_RC=${?}
    log "i386 defconfig $(results "${KRNL_RC}")"
    qemu_boot_kernel x86
    log "i386 defconfig qemu boot $(QEMU=1 results "${?}")"

    if grep -q "select ARCH_SUPPORTS_LTO_CLANG_THIN" "${LINUX_SRC}"/arch/x86/Kconfig &&
        ! grep -Pq "select ARCH_SUPPORTS_LTO_CLANG_THIN\tif X86_64" "${LINUX_SRC}"/arch/x86/Kconfig &&
        [[ ${LLVM_VER_CODE} -ge 110000 ]]; then
        KLOG=i386-defconfig-lto
        kmake distclean i386_defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake olddefconfig all
        KRNL_RC=${?}
        log "i386 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "${KRNL_RC}")"
        qemu_boot_kernel x86
        log "i386 defconfig + CONFIG_LTO_CLANG_THIN=y qemu boot $(QEMU=1 results "${?}")"
    fi

    ${DEFCONFIGS_ONLY} && return 0

    KLOG=x86-allnoconfig
    kmake distclean allnoconfig all
    log "x86 allnoconfig $(results "${?}")"

    KLOG=x86-tinyconfig
    kmake distclean tinyconfig all
    log "x86 tinyconfig $(results "${?}")"

    # Debian
    KLOG=i386-debian
    setup_config debian/i386.config
    kmake olddefconfig all
    log "i386 debian config${LOG_COMMENT} $(results "${?}")"

    # Fedora
    KLOG=i686-fedora
    setup_config fedora/i686.config
    kmake olddefconfig all
    log "i686 fedora config${LOG_COMMENT} $(results "${?}")"

    # OpenSUSE
    KLOG=i386-opensuse
    setup_config opensuse/i386.config
    kmake olddefconfig all
    log "i386 opensuse config${LOG_COMMENT} $(results "${?}")"
}

# Build x86_64 kernels
function build_x86_64_kernels() {
    local LOG_COMMENT
    header "Building x86_64 kernels"

    [[ ${LNX_VER_CODE} -ge 510000 && ${LLVM_VER_CODE} -ge 110000 ]] && export LLVM_IAS=1

    unset CROSS_COMPILE
    print_binutils_info
    echo

    # Upstream
    KLOG=x86_64-defconfig
    kmake distclean defconfig all
    KRNL_RC=${?}
    log "x86_64 defconfig $(results "${KRNL_RC}")"
    qemu_boot_kernel x86_64
    log "x86_64 qemu boot $(QEMU=1 results "${?}")"

    if grep -q "config LTO_CLANG_THIN" "${LINUX_SRC}"/arch/Kconfig && [[ ${LLVM_VER_CODE} -ge 110000 ]]; then
        KLOG=x86_64-defconfig-lto
        kmake distclean defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake olddefconfig all
        KRNL_RC=${?}
        log "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "${KRNL_RC}")"
        qemu_boot_kernel x86_64
        log "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y qemu boot $(QEMU=1 results "${?}")"
    fi

    ${DEFCONFIGS_ONLY} && return 0

    KLOG=x86_64-allmodconfig
    kmake distclean allmodconfig
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" + CONFIG_STM=n + CONFIG_TEST_MEMCAT_P=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM -d CONFIG_TEST_MEMCAT_P
    else
        unset LOG_COMMENT
    fi
    kmake olddefconfig all
    log "x86_64 allmodconfig${LOG_COMMENT} $(results "${?}")"

    KLOG=x86_64-allmodconfig-O3
    kmake distclean allmodconfig
    # https://github.com/ClangBuiltLinux/linux/issues/678
    if [[ ${LNX_VER_CODE} -lt 508000 ]]; then
        LOG_COMMENT=" + CONFIG_SENSORS_APPLESMC=n (https://github.com/ClangBuiltLinux/linux/issues/678)"
        scripts_config -d CONFIG_SENSORS_APPLESMC
    # https://github.com/ClangBuiltLinux/linux/issues/1116
    elif [[ -f ${LINUX_SRC}/drivers/media/platform/ti-vpe/cal-camerarx.c && ${LLVM_VER_CODE} -lt 110000 ]]; then
        CTOD=CONFIG_VIDEO_TI_CAL
        LOG_COMMENT=" + ${CTOD}=n (https://github.com/ClangBuiltLinux/linux/issues/1116)"
        scripts_config -d ${CTOD}
    else
        unset LOG_COMMENT
    fi
    kmake olddefconfig all KCFLAGS="${KCFLAGS:+${KCFLAGS} }-O3"
    log "x86_64 allmodconfig at -O3${LOG_COMMENT} $(results "${?}")"

    # Alpine Linux
    KLOG=x86_64-alpine
    LOG_COMMENT=""
    setup_config alpine/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake olddefconfig all
    KRNL_RC=${?}
    log "x86_64 alpine config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel x86_64
    log "x86_64 alpine config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    # Arch Linux
    KLOG=x86_64-archlinux
    LOG_COMMENT=""
    setup_config archlinux/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake olddefconfig all
    KRNL_RC=${?}
    log "x86_64 archlinux config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel x86_64
    log "x86_64 archlinux config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    # Debian
    KLOG=x86_64-debian
    setup_config debian/amd64.config
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake OBJCOPY=objcopy olddefconfig all
    KRNL_RC=${?}
    log "x86_64 debian config $(results "${KRNL_RC}")"
    qemu_boot_kernel x86_64
    log "x86_64 debian config qemu boot $(QEMU=1 results "${?}")"

    # Fedora
    KLOG=x86_64-fedora
    LOG_COMMENT=""
    setup_config fedora/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT+=" + CONFIG_STM=n + CONFIG_TEST_MEMCAT_P=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM -d CONFIG_TEST_MEMCAT_P
    fi
    kmake olddefconfig all
    KRNL_RC=${?}
    log "x86_64 fedora config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel x86_64
    log "x86_64 fedora config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    # OpenSUSE
    KLOG=x86_64-opensuse
    LOG_COMMENT=""
    setup_config opensuse/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake OBJCOPY=objcopy olddefconfig all
    KRNL_RC=${?}
    log "x86_64 opensuse config${LOG_COMMENT} $(results "${KRNL_RC}")"
    qemu_boot_kernel x86_64
    log "x86_64 opensuse config${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    unset LLVM_IAS
}

function build_x86_64_cfi_kernels() {
    header "Building x86_64 CFI kernels"

    if [[ ${LLVM_VER_CODE} -ge 140000 ]]; then
        KLOG=x86_64-defconfig-lto-cfi
        kmake LLVM=1 LLVM_IAS=1 distclean defconfig
        scripts_config -d LTO_NONE -e CFI_CLANG -e LTO_CLANG_THIN
        kmake LLVM=1 LLVM_IAS=1 olddefconfig all
        KRNL_RC=${?}
        log "x86_64 defconfig + CONFIG_CFI_CLANG=y $(results "${KRNL_RC}")"
        qemu_boot_kernel x86_64
        log "x86_64 defconfig + CONFIG_CFI_CLANG=y qemu boot $(QEMU=1 results "${?}")"
    fi
}

# Build Sami Tolvanen's CFI tree
function build_cfi_kernels() {
    header "Updating CFI kernel source"

    # Grab the latest kernel source
    LINUX_SRC=${SRC}/linux-clang-cfi
    [[ -d ${LINUX_SRC} ]] || git clone -b clang-cfi https://github.com/samitolvanen/linux "${LINUX_SRC}"
    git -C "${LINUX_SRC}" remote update || return ${?}
    git -C "${LINUX_SRC}" reset --hard origin/clang-cfi

    TMP_CONFIG=$(mktemp --suffix=.config)
    for ARCH in "${ARCHES[@]}"; do
        case ${ARCH} in
            x86_64)
                OUT=$(cd "${LINUX_SRC}" && readlink -f -m "${O:-.build}")/${ARCH}
                if ! check_clang_target "${ARCH}"; then
                    header "Skipping ${ARCH} LTO/CFI kernels"
                    echo "Reason: clang was not configured with this target"
                    continue
                fi
                build_"${ARCH}"_cfi_kernels || exit ${?}
                ;;
            *) ;;
        esac
    done
    rm "${TMP_CONFIG}"
}

# Print LLVM/clang version as a 5-6 digit number (e.g. clang 11.0.0 will be 110000)
function create_llvm_ver_code() {
    local MAJOR MINOR PATCHLEVEL
    MAJOR=$(echo __clang_major__ | clang -E -x c - | tail -n 1)
    MINOR=$(echo __clang_minor__ | clang -E -x c - | tail -n 1)
    PATCHLEVEL=$(echo __clang_patchlevel__ | clang -E -x c - | tail -n 1)
    LLVM_VER_CODE=$(printf "%d%02d%02d" "${MAJOR}" "${MINOR}" "${PATCHLEVEL}")
}

# Print Linux version as a 6 digit number (e.g. Linux 5.6.2 will be 506002)
function create_lnx_ver_code() {
    LNX_VER=$(make -C "${LINUX_SRC}" -s kernelversion | sed 's/-rc.*//')
    IFS=. read -ra LNX_VER <<<"${LNX_VER}"
    LNX_VER_CODE=$(printf "%d%02d%03d" "${LNX_VER[@]}")
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
    echo | clang --target=${target} -c -x c - -o /dev/null &>/dev/null
}

# Build kernels with said toolchains
function build_kernels() {
    export PATH=${LLVM_PREFIX}/bin:${BINUTILS_PREFIX}/bin:${PATH}

    set_tool_vars
    header "Build information"
    print_tc_lnx_info
    {
        print_tc_lnx_info
        echo
    } >"${BLD_LOG}"
    create_lnx_ver_code
    create_llvm_ver_code

    for ARCH in "${ARCHES[@]}"; do
        OUT=$(cd "${LINUX_SRC}" && readlink -f -m "${O:-.build}")/${ARCH}
        if ! check_clang_target "${ARCH}"; then
            header "Skipping ${ARCH} kernels"
            echo "Reason: clang was not configured with this target"
            continue
        fi
        build_"${ARCH}"_kernels || exit ${?}
    done
    ${TEST_CFI_KERNEL:=false} && build_cfi_kernels
}

# Boot the kernel in QEMU
function qemu_boot_kernel() {
    [[ ${KRNL_RC} -eq 0 ]] && "${BOOT_UTILS}"/boot-qemu.sh -a "${1:?}" -k "${OUT}"
}

# Show the results from the build log and show total script runtime
function report_results() {
    # Remove last blank line and full path from errors/warnings because I am OCD :^)
    sed -i -e '${/^$/d}' -e "s;${LINUX_SRC}/;;g" "${BLD_LOG}"
    header "Toolchain and kernel information"
    head -n4 "${BLD_LOG}"
    header "List of successes"
    grep "success" "${BLD_LOG}"
    FAILS=$(tail -n +5 "${BLD_LOG}" | grep "failed")
    if [[ -n ${FAILS} ]]; then
        header "List of failures"
        echo "${FAILS}"
    fi
    echo
    echo "Total script runtime: $(print_time "${START_TIME}" "$(date +%s)")"
}

parse_parameters "${@}"
build_llvm_binutils
dwnld_kernel_src
dwnld_update_boot_utils
build_kernels
report_results
