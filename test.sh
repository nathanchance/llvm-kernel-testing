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
            --test-lto-cfi-kernel) TEST_LTO_CFI_KERNEL=true ;;
            *=*) export "${1:?}" ;;
            "") ;;
            *) die "Invalid parameter '${1}'" ;;
        esac
        shift
    done

    [[ -z ${ARCHES[*]} ]] && ARCHES=(arm32 arm64 mips powerpc riscv s390x x86 x86_64)
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
        --branch "${LLVM_BRANCH:=llvmorg-11.0.1}" \
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

    LINUX=linux-5.10.7
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

# Print clang, binutils, and kernel versions being tested into the build log
function log_tc_lnx_ver() {
    {
        clang --version | head -n1
        clang --version | tail -n1
        as --version | head -n1
        echo "Linux $(make -C "${LINUX_SRC}" -s kernelversion)$(get_config_localversion_auto)"
        echo
    } >"${BLD_LOG}"
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
                LD=* | OBJCOPY=* | OBJDUMP=*) export "${1:?}" ;;
                *) MAKE_ARGS=("${MAKE_ARGS[@]}" "${1}") ;;
            esac
            shift
        done

        set -x
        time make \
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
            ${LLVM_IAS:+LLVM_IAS="${LLVM_IAS}"} \
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

# Set up an out of tree config
function setup_config() {
    # Cleanup the previous artifacts
    rm -rf "${OUT:?}"
    mkdir -p "${OUT}"

    # Grab the config we are testing
    cp -v "${BASE}"/configs/"${1:?}" "${OUT}"/.config

    # Some distro configs have options that are specific to their distro,
    # which will break in a generic environment
    case ${1} in
        # We are building upstream kernels, which do not have Debian's
        # signing keys in their source
        # The Android drivers are not modular in upstream
        debian/*)
            scripts_config -d CONFIG_SYSTEM_TRUSTED_KEYS
            [[ "$(scripts_config -s ANDROID_BINDER_IPC)" = "m" ]] && scripts_config -e ANDROID_BINDER_IPC
            [[ "$(scripts_config -s ASHMEM)" = "m" ]] && scripts_config -e ASHMEM
            ;;

        # Arch Linux, Fedora, and OpenSUSE enable BTF, which has to be handled in a special manner:
        #
        #   * pahole needs to be available
        #
        #   * The kernel needs https://git.kernel.org/linus/90ceddcb495008ac8ba7a3dce297841efcd7d584,
        #     which is first available in 5.7: https://github.com/ClangBuiltLinux/linux/issues/871
        #
        # If either of those conditions are false, we need to disable this config so
        # that the build does not error.
        archlinux/* | fedora/* | opensuse/*)
            if ! (command -v pahole &>/dev/null && [[ ${LNX_VER_CODE} -ge 507000 ]]); then
                scripts_config -d CONFIG_DEBUG_INFO_BTF
            fi
            ;;
    esac

    # Make sure that certain configuration options do not get disabled across kernel versions
    # This would not be necessary if we had an individual config for each kernel version
    # that we support but that is a lot more effort.
    SCRIPTS_CONFIG_ARGS=()

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

    # CONFIG_POWER_RESET_SC27XX as a module is invalid before https://git.kernel.org/linus/f78c55e3b4806974f7d590b2aab8683232b7bd25
    if [[ "$(scripts_config -s POWER_RESET_SC27XX)" = "m" ]] &&
        grep -q 'bool "Spreadtrum SC27xx PMIC power-off driver"' "${LINUX_SRC}"/drivers/power/reset/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e POWER_RESET_SC27XX)
    fi

    # CONFIG_QCOM_RPMPD as a module is invalid before https://git.kernel.org/linus/f29808b2fb85a7ff2d4830aa1cb736c8c9b986f4
    if [[ "$(scripts_config -s QCOM_RPMPD)" = "m" ]] &&
        grep -q 'bool "Qualcomm RPM Power domain driver"' "${LINUX_SRC}"/drivers/soc/qcom/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e QCOM_RPMPD)
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

    # CONFIG_TI_CPTS as a module is invalid before https://git.kernel.org/linus/92db978f0d686468e527d49268e7c7e8d97d334b
    if [[ "$(scripts_config -s TI_CPTS)" = "m" ]] &&
        grep -q 'bool "TI Common Platform Time Sync' "${LINUX_SRC}"/drivers/net/ethernet/ti/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e TI_CPTS)
    fi

    # CONFIG_MTD_NAND_ECC_SW_HAMMING as a module is invalid after https://git.kernel.org/next/linux-next/c/5c859c18150b57d47dc684cab6e12b99f5d14ad3
    if [[ "$(scripts_config -s MTD_NAND_ECC_SW_HAMMING)" = "m" ]] &&
        grep -q 'bool "Software Hamming ECC engine"' "${LINUX_SRC}"/drivers/mtd/nand/Kconfig; then
        SCRIPTS_CONFIG_ARGS+=(-e MTD_NAND_ECC_SW_HAMMING)
    fi

    [[ -n "${SCRIPTS_CONFIG_ARGS[*]}" ]] && scripts_config "${SCRIPTS_CONFIG_ARGS[@]}"
}

function results() {
    if [[ ${1} -eq 0 ]]; then
        RESULT=successful
    else
        RESULT=failed
    fi
    printf "%s" "${RESULT}"
    if [[ -z ${QEMU} ]]; then
        printf " in %s" "$(print_time "${KMAKE_START}" "${KMAKE_END}")"
        printf '\n'
        [[ ${RESULT} = "failed" ]] && grep "error:\|warning:\|undefined" "${BLD_LOG_DIR}/${KLOG}.log"
    else
        printf '\n'
    fi
    printf '\n'
}

# Build arm32 kernels
function build_arm32_kernels() {
    local CROSS_COMPILE KMAKE_ARGS LOG_COMMENT
    CROSS_COMPILE=arm-linux-gnueabi-
    KMAKE_ARGS=("ARCH=arm" "CROSS_COMPILE=${CROSS_COMPILE}")

    header "Building arm32 kernels"

    # Upstream
    KLOG=arm32-multi_v5_defconfig
    kmake "${KMAKE_ARGS[@]}" distclean multi_v5_defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/954
    if [[ ${LLVM_VER_CODE} -lt 100001 ]]; then
        LOG_COMMENT=" (minus CONFIG_TRACING, CONFIG_OPROFILE, and CONFIG_RCU_TRACE due to https://github.com/ClangBuiltLinux/linux/issues/954)"
        scripts_config -d CONFIG_TRACING -d CONFIG_OPROFILE -d CONFIG_RCU_TRACE
    else
        unset LOG_COMMENT
    fi
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm32 multi_v5_defconfig${LOG_COMMENT} $(results "${?}")"
    qemu_boot_kernel arm32_v5
    log "arm32 multi_v5_defconfig${LOG_COMMENT} qemu boot $(QEMU=1 results "${?}")"

    KLOG=arm32-aspeed_g5_defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/732
    [[ ${LLVM_VER_CODE} -lt 110000 ]] && ARM32_V6_LD=${CROSS_COMPILE}ld
    kmake "${KMAKE_ARGS[@]}" ${ARM32_V6_LD:+LD=${ARM32_V6_LD}} distclean aspeed_g5_defconfig all
    log "arm32 aspeed_g5_defconfig $(results "${?}")"
    qemu_boot_kernel arm32_v6
    log "arm32 aspeed_g5_defconfig qemu boot $(QEMU=1 results "${?}")"

    KLOG=arm32-multi_v7_defconfig
    kmake "${KMAKE_ARGS[@]}" distclean multi_v7_defconfig all
    log "arm32 multi_v7_defconfig $(results "${?}")"
    qemu_boot_kernel arm32_v7
    log "arm32 multi_v7_defconfig qemu boot $(QEMU=1 results "${?}")"

    ${DEFCONFIGS_ONLY} && return 0

    KLOG=arm32-allmodconfig
    kmake "${KMAKE_ARGS[@]}" KCONFIG_ALLCONFIG=<(echo CONFIG_CPU_BIG_ENDIAN=n) distclean allmodconfig all
    log "arm32 allmodconfig (plus CONFIG_CPU_BIG_ENDIAN=n) $(results "${?}")"

    KLOG=arm32-allnoconfig
    kmake "${KMAKE_ARGS[@]}" distclean allnoconfig all
    log "arm32 allnoconfig $(results "${?}")"

    KLOG=arm32-allyesconfig
    kmake "${KMAKE_ARGS[@]}" KCONFIG_ALLCONFIG=<(echo CONFIG_CPU_BIG_ENDIAN=n) distclean allyesconfig all
    log "arm32 allyesconfig (plus CONFIG_CPU_BIG_ENDIAN=n) $(results "${?}")"

    # Debian
    KLOG=arm32-debian
    setup_config debian/armmp.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm32 debian config $(results "${?}")"

    # Fedora
    KLOG=arm32-fedora
    setup_config fedora/armv7hl.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "armv7hl fedora config $(results "${?}")"

    # OpenSUSE
    KLOG=arm32-opensuse
    setup_config opensuse/armv7hl.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "armv7hl opensuse config $(results "${?}")"
}

# Build arm64 kernels
function build_arm64_kernels() {
    local KMAKE_ARGS
    KMAKE_ARGS=("ARCH=arm64" "CROSS_COMPILE=aarch64-linux-gnu-")

    header "Building arm64 kernels"

    # Upstream
    KLOG=arm64-defconfig
    kmake "${KMAKE_ARGS[@]}" distclean defconfig all
    log "arm64 defconfig $(results "${?}")"
    qemu_boot_kernel arm64
    log "arm64 defconfig qemu boot $(QEMU=1 results "${?}")"

    ${DEFCONFIGS_ONLY} && return 0

    KLOG=arm64-allmodconfig
    kmake "${KMAKE_ARGS[@]}" KCONFIG_ALLCONFIG=<(echo CONFIG_CPU_BIG_ENDIAN=n) distclean allmodconfig all
    log "arm64 allmodconfig (plus CONFIG_CPU_BIG_ENDIAN=n) $(results "${?}")"

    KLOG=arm64-allnoconfig
    kmake "${KMAKE_ARGS[@]}" distclean allnoconfig all
    log "arm64 allnoconfig $(results "${?}")"

    KLOG=arm64-allyesconfig
    kmake "${KMAKE_ARGS[@]}" KCONFIG_ALLCONFIG=<(echo CONFIG_CPU_BIG_ENDIAN=n) distclean allyesconfig all
    log "arm64 allyesconfig (plus CONFIG_CPU_BIG_ENDIAN=n) $(results "${?}")"

    # Debian
    KLOG=arm64-debian
    setup_config debian/arm64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 debian config $(results "${?}")"

    # Fedora
    KLOG=arm64-fedora
    setup_config fedora/aarch64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 fedora config $(results "${?}")"

    # OpenSUSE
    KLOG=arm64-opensuse
    setup_config opensuse/arm64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 opensuse config $(results "${?}")"
}

# Build mips kernels
function build_mips_kernels() {
    local CROSS_COMPILE KMAKE_ARGS
    CROSS_COMPILE=mipsel-linux-gnu-
    KMAKE_ARGS=("ARCH=mips" "CROSS_COMPILE=${CROSS_COMPILE}")

    header "Building mips kernels"

    # Upstream
    KLOG=mipsel-malta
    kmake "${KMAKE_ARGS[@]}" distclean malta_kvm_guest_defconfig all
    log "mips malta_kvm_guest_defconfig $(results "${?}")"
    qemu_boot_kernel mipsel
    log "mips malta_kvm_guest_defconfig qemu boot $(QEMU=1 results "${?}")"

    KLOG=mipsel-malta-kaslr
    kmake "${KMAKE_ARGS[@]}" distclean malta_kvm_guest_defconfig
    scripts_config \
        -e RELOCATABLE \
        --set-val RELOCATION_TABLE_SIZE 0x00200000 \
        -e RANDOMIZE_BASE
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "mips malta_kvm_guest_defconfig (plus CONFIG_RANDOMIZE_BASE=y) $(results "${?}")"
    qemu_boot_kernel mipsel
    log "mips malta_kvm_guest_defconfig (plus CONFIG_RANDOMIZE_BASE=y) qemu boot $(QEMU=1 results "${?}")"

    # https://github.com/ClangBuiltLinux/linux/issues/1025
    KLOG=mips-malta
    [[ -f ${LINUX_SRC}/arch/mips/vdso/Kconfig ]] && MIPS_BE_LD=${CROSS_COMPILE}ld
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} distclean malta_kvm_guest_defconfig
    scripts_config \
        -d CONFIG_CPU_LITTLE_ENDIAN \
        -e CONFIG_CPU_BIG_ENDIAN
    kmake "${KMAKE_ARGS[@]}" ${MIPS_BE_LD:+LD=${MIPS_BE_LD}} olddefconfig all
    log "mips malta_kvm_guest_defconfig plus CONFIG_CPU_BIG_ENDIAN=y $(results "${?}")"
    qemu_boot_kernel mips
    log "mips malta_kvm_guest_defconfig plus CONFIG_CPU_BIG_ENDIAN=y qemu boot $(QEMU=1 results "${?}")"

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
}

# Build powerpc kernels
function build_powerpc_kernels() {
    local CROSS_COMPILE CTOD KMAKE_ARGS LOG_COMMENT
    CROSS_COMPILE=powerpc-linux-gnu-
    KMAKE_ARGS=("ARCH=powerpc" "CROSS_COMPILE=${CROSS_COMPILE}")

    header "Building powerpc kernels"

    # Upstream
    # https://llvm.org/pr46186
    if ! grep -q 'case 4: __put_user_asm_goto(x, ptr, label, "stw"); break;' "${LINUX_SRC}"/arch/powerpc/include/asm/uaccess.h || [[ ${LLVM_VER_CODE} -ge 110000 ]]; then
        KLOG=powerpc-ppc44x_defconfig
        kmake "${KMAKE_ARGS[@]}" distclean ppc44x_defconfig all uImage
        log "powerpc ppc44x_defconfig $(results "${?}")"
        qemu_boot_kernel ppc32
        log "powerpc ppc44x_defconfig qemu boot $(QEMU=1 results "${?}")"

        KLOG=powerpc-allnoconfig
        kmake "${KMAKE_ARGS[@]}" distclean allnoconfig all
        log "powerpc allnoconfig $(results "${?}")"
    else
        log "powerpc 32-bit configs skipped due to https://llvm.org/pr46186"
    fi

    KLOG=powerpc64-pseries_defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/602
    kmake "${KMAKE_ARGS[@]}" LD=${CROSS_COMPILE}ld distclean pseries_defconfig all
    log "powerpc pseries_defconfig $(results "${?}")"
    qemu_boot_kernel ppc64
    log "powerpc pseries_defconfig qemu boot $(QEMU=1 results "${?}")"

    CROSS_COMPILE=powerpc64-linux-gnu-
    KMAKE_ARGS=("ARCH=powerpc" "CROSS_COMPILE=${CROSS_COMPILE}")

    KLOG=powerpc64le-powernv_defconfig
    kmake "${KMAKE_ARGS[@]}" distclean powernv_defconfig all
    log "powerpc powernv_defconfig $(results "${?}")"
    qemu_boot_kernel ppc64le
    log "powerpc powernv_defconfig qemu boot $(QEMU=1 results "${?}")"

    # https://github.com/ClangBuiltLinux/linux/issues/666
    # https://github.com/ClangBuiltLinux/linux/issues/811
    PPC64LE_ARGS=("LD=${CROSS_COMPILE}ld" "OBJDUMP=${CROSS_COMPILE}objdump")

    KLOG=powerpc64le-defconfig
    kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" distclean ppc64le_defconfig all
    log "powerpc ppc64le_defconfig $(results "${?}")"

    ${DEFCONFIGS_ONLY} && return 0

    # Debian
    KLOG=powerpc64le-debian
    setup_config debian/powerpc64le.config
    # https://github.com/ClangBuiltLinux/linux/issues/944
    if [[ ${LLVM_VER_CODE} -lt 100001 ]]; then
        CTOD=CONFIG_DRM_AMD_DC
        LOG_COMMENT=" (minus ${CTOD} due to https://github.com/ClangBuiltLinux/linux/issues/944)"
        scripts_config -d ${CTOD}
    else
        unset LOG_COMMENT
    fi
    kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" olddefconfig all
    log "ppc64le debian config${LOG_COMMENT} $(results "${?}")"

    # Fedora
    KLOG=powerpc64le-fedora
    setup_config fedora/ppc64le.config
    # https://github.com/ClangBuiltLinux/linux/issues/944
    [[ ${LLVM_VER_CODE} -lt 100001 ]] && scripts_config -d ${CTOD}
    kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" olddefconfig all
    log "ppc64le fedora config${LOG_COMMENT} $(results "${?}")"

    # OpenSUSE
    # https://github.com/ClangBuiltLinux/linux/issues/1160
    if ! grep -q "depends on PPC32 || COMPAT" "${LINUX_SRC}"/arch/powerpc/platforms/Kconfig.cputype || [[ ${LLVM_VER_CODE} -ge 120000 ]]; then
        KLOG=powerpc64le-opensuse
        setup_config opensuse/ppc64le.config
        # https://github.com/ClangBuiltLinux/linux/issues/944
        [[ ${LLVM_VER_CODE} -lt 100001 ]] && scripts_config -d ${CTOD}
        kmake "${KMAKE_ARGS[@]}" "${PPC64LE_ARGS[@]}" olddefconfig all
        log "ppc64le opensuse config $(results "${?}")"
    else
        log "ppc64le opensuse config skipped due to https://github.com/ClangBuiltLinux/linux/issues/1160"
    fi
}

# Build riscv kernels
function build_riscv_kernels() {
    local KMAKE_ARGS
    KMAKE_ARGS=("ARCH=riscv" "CROSS_COMPILE=riscv64-linux-gnu-")

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

    KLOG=riscv-defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/1020
    kmake "${KMAKE_ARGS[@]}" LD=riscv64-linux-gnu-ld LLVM_IAS=1 distclean defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/1143
    if grep -q "config EFI" "${LINUX_SRC}"/arch/riscv/Kconfig; then
        LOG_COMMENT=" (minus CONFIG_EFI due to https://github.com/ClangBuiltLinux/linux/issues/1143)"
        scripts_config -d CONFIG_EFI
    fi
    kmake "${KMAKE_ARGS[@]}" LD=riscv64-linux-gnu-ld LLVM_IAS=1 olddefconfig all
    log "riscv defconfig${LOG_COMMENT} $(results "${?}")"
    # https://github.com/ClangBuiltLinux/linux/issues/867
    if grep -q "(long)__old" "${LINUX_SRC}"/arch/riscv/include/asm/cmpxchg.h; then
        qemu_boot_kernel riscv
        log "riscv defconfig qemu boot $(QEMU=1 results "${?}")"
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
        "ARCH=s390"
        "CROSS_COMPILE=${CROSS_COMPILE}"
        "KCFLAGS=-Wno-address-of-packed-member"
        "LD=${CROSS_COMPILE}ld"
        "OBJCOPY=${CROSS_COMPILE}objcopy"
        "OBJDUMP=${CROSS_COMPILE}objdump"
    )

    # s390 did not build properly until Linux 5.6
    if [[ ${LNX_VER_CODE} -lt 506000 ]]; then
        header "Skipping s390x kernels"
        echo "Reason: s390 kernels did not build properly until Linux 5.6"
        echo "        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/"
        return 0
    fi

    header "Building s390x kernels"

    # Upstream
    KLOG=s390x-defconfig
    kmake "${KMAKE_ARGS[@]}" distclean defconfig all
    log "s390x defconfig $(results "${?}")"
    qemu_boot_kernel s390
    log "s390x defconfig qemu boot $(QEMU=1 results "${?}")"

    ${DEFCONFIGS_ONLY} && return 0

    KLOG=s390x-allmodconfig
    kmake "${KMAKE_ARGS[@]}" distclean allmodconfig
    # https://github.com/ClangBuiltLinux/linux/issues/1213
    if ! grep -q "config UBSAN_MISC" "${LINUX_SRC}"/lib/Kconfig.ubsan; then
        CTOD=CONFIG_UBSAN
        LOG_COMMENT=" (minus ${CTOD} due to https://github.com/ClangBuiltLinux/linux/issues/1213)"
        scripts_config -d ${CTOD}
    else
        unset LOG_COMMENT
    fi
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x allmodconfig${LOG_COMMENT} $(results "${?}")"

    KLOG=s390x-allyesconfig
    kmake "${KMAKE_ARGS[@]}" distclean allyesconfig
    # https://github.com/ClangBuiltLinux/linux/issues/1213
    if ! grep -q "config UBSAN_MISC" "${LINUX_SRC}"/lib/Kconfig.ubsan; then
        CTOD=CONFIG_UBSAN
        LOG_COMMENT=" (minus ${CTOD} due to https://github.com/ClangBuiltLinux/linux/issues/1213)"
        scripts_config -d ${CTOD}
    else
        unset LOG_COMMENT
    fi
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x allyesconfig${LOG_COMMENT} $(results "${?}")"

    # Debian
    KLOG=s390x-debian
    setup_config debian/s390x.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x debian config $(results "${?}")"

    # Fedora
    KLOG=s390x-fedora
    setup_config fedora/s390x.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x fedora config $(results "${?}")"

    # OpenSUSE
    KLOG=s390x-opensuse
    setup_config opensuse/s390x.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x opensuse config $(results "${?}")"
}

# Build x86 kernels
function build_x86_kernels() {
    # s390 did not build properly until Linux 5.9
    if [[ ${LNX_VER_CODE} -lt 509000 ]]; then
        header "Skipping x86 kernels"
        echo "Reason: x86 kernels did not build properly until Linux 5.9"
        echo "        https://github.com/ClangBuiltLinux/linux/issues/194"
        return 0
    fi

    header "Building x86 kernels"

    KLOG=i386-defconfig
    kmake distclean i386_defconfig all
    log "i386 defconfig $(results "${?}")"
    qemu_boot_kernel x86
    log "i386 defconfig qemu boot $(QEMU=1 results "${?}")"

    KLOG=x86-allnoconfig
    kmake distclean allnoconfig all
    log "x86 allnoconfig $(results "${?}")"
}

# Build x86_64 kernels
function build_x86_64_kernels() {
    local LOG_COMMENT
    header "Building x86_64 kernels"

    # Upstream
    KLOG=x86_64-defconfig
    kmake distclean defconfig all
    log "x86_64 defconfig $(results "${?}")"
    qemu_boot_kernel x86_64
    log "x86_64 qemu boot $(QEMU=1 results "${?}")"

    ${DEFCONFIGS_ONLY} && return 0

    KLOG=x86_64-allmodconfig
    kmake distclean allmodconfig
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" (minus CONFIG_STM and CONFIG_TEST_MEMCAT_P due to https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM -d CONFIG_TEST_MEMCAT_P
    else
        unset LOG_COMMENT
    fi
    kmake olddefconfig all
    log "x86_64 allmodconfig${LOG_COMMENT} $(results "${?}")"

    KLOG=x86_64-allyesconfig
    kmake distclean allyesconfig all
    log "x86_64 allyesconfig $(results "${?}")"

    KLOG=x86_64-allyesconfig-O3
    kmake distclean allyesconfig
    # https://github.com/ClangBuiltLinux/linux/issues/678
    if [[ ${LNX_VER_CODE} -lt 508000 ]]; then
        LOG_COMMENT=" (minus CONFIG_SENSORS_APPLESMC)"
        scripts_config -d CONFIG_SENSORS_APPLESMC
    # https://github.com/ClangBuiltLinux/linux/issues/1116
    elif [[ -f ${LINUX_SRC}/drivers/media/platform/ti-vpe/cal-camerarx.c ]]; then
        LOG_COMMENT=" (minus CONFIG_VIDEO_TI_CAL due to https://github.com/ClangBuiltLinux/linux/issues/1116)"
        scripts_config -d CONFIG_VIDEO_TI_CAL
    else
        unset LOG_COMMENT
    fi
    kmake olddefconfig all KCFLAGS="${KCFLAGS:+${KCFLAGS} }-O3"
    log "x86_64 allyesconfig at -O3${LOG_COMMENT} $(results "${?}")"

    # Arch Linux
    KLOG=x86_64-archlinux
    setup_config archlinux/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" (minus CONFIG_STM due to https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    else
        unset LOG_COMMENT
    fi
    kmake olddefconfig all
    log "x86_64 archlinux config${LOG_COMMENT} $(results "${?}")"

    # Debian
    KLOG=x86_64-debian
    setup_config debian/amd64.config
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake OBJCOPY=objcopy olddefconfig all
    log "x86_64 debian config $(results "${?}")"

    # Fedora
    KLOG=x86_64-fedora
    setup_config fedora/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" (minus CONFIG_STM and CONFIG_TEST_MEMCAT_P due to https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM -d CONFIG_TEST_MEMCAT_P
    else
        unset LOG_COMMENT
    fi
    kmake olddefconfig all
    log "x86_64 fedora config${LOG_COMMENT} $(results "${?}")"

    # OpenSUSE
    KLOG=x86_64-opensuse
    setup_config opensuse/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" (minus CONFIG_STM due to https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    else
        unset LOG_COMMENT
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake OBJCOPY=objcopy olddefconfig all
    log "x86_64 opensuse config${LOG_COMMENT} $(results "${?}")"
}

# Build Sami Tolvanen's LTO/CFI tree
function build_lto_cfi_kernels() {
    local KMAKE_ARGS
    KMAKE_ARGS=("ARCH=arm64" "CROSS_COMPILE=aarch64-linux-gnu-" "LLVM=1" "LLVM_IAS=1")

    header "Building LTO/CFI kernels"

    # Grab the latest kernel source
    LINUX_SRC=${SRC}/linux-clang-cfi
    OUT=${LINUX_SRC}/out
    rm -rf "${LINUX_SRC}"
    curl -LSso "${LINUX_SRC}.zip" https://github.com/samitolvanen/linux/archive/clang-cfi.zip
    (cd "${SRC}" && unzip -q "${LINUX_SRC}.zip")
    rm -rf "${LINUX_SRC}.zip"

    # arm64
    KLOG=arm64-lto-cfi
    kmake "${KMAKE_ARGS[@]}" distclean defconfig
    scripts_config \
        -d LTO_NONE \
        -e LTO_CLANG_THIN \
        -e CFI_CLANG \
        -e SHADOW_CALL_STACK \
        -e FTRACE \
        -e FUNCTION_TRACER \
        -e DYNAMIC_FTRACE \
        -e LOCK_TORTURE_TEST \
        -e RCU_TORTURE_TEST
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 LTO+CFI+SCS config $(results "${?}")"
    qemu_boot_kernel arm64
    log "arm64 LTO+CFI+SCS config qemu boot $(QEMU=1 results "${?}")"

    # x86_64
    # Patch https://github.com/ClangBuiltLinux/linux/issues/1216 for now
    grep -q "vmsave" "${LINUX_SRC}"/arch/x86/kvm/svm/sev.c &&
        b4 am -o - -l 20201219063711.3526947-1-natechancellor@gmail.com | patch -d "${LINUX_SRC}" -p1
    KLOG=x86_64-lto-cfi
    kmake LLVM=1 LLVM_IAS=1 distclean defconfig
    scripts_config \
        -d LTO_NONE \
        -e LTO_CLANG_THIN \
        -e CFI_CLANG \
        -e KVM \
        -e KVM_AMD \
        -e KVM_INTEL \
        -e LOCK_TORTURE_TEST \
        -e RCU_TORTURE_TEST
    kmake LLVM=1 LLVM_IAS=1 olddefconfig all
    log "x86_64 LTO+CFI config $(results "${?}")"
    qemu_boot_kernel x86_64
    log "x86_64 LTO+CFI config qemu boot $(QEMU=1 results "${?}")"
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
    log_tc_lnx_ver
    create_lnx_ver_code
    create_llvm_ver_code

    for ARCH in "${ARCHES[@]}"; do
        OUT=$(cd "${LINUX_SRC}" && readlink -f -m "${O:-out}")/${ARCH}
        if ! check_clang_target "${ARCH}"; then
            header "Skipping ${ARCH} kernels"
            echo "Reason: clang was not configured with this target"
            continue
        fi
        build_"${ARCH}"_kernels || exit ${?}
    done
    ${TEST_LTO_CFI_KERNEL:=false} && build_lto_cfi_kernels
}

# Boot the kernel in QEMU
function qemu_boot_kernel() {
    "${SRC}"/boot-utils/boot-qemu.sh -a "${1:?}" -k "${OUT}"
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
