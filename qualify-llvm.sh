#!/usr/bin/env bash

# Get the absolute location of the tc-build repo
BASE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
[[ -z ${BASE} ]] && exit 1

# Folder setup
SRC=${BASE}/src
TC_BLD=${SRC}/tc-build

# Logging for the script
BLD_LOG=${BASE}/logs/$(date +%Y%m%d-%H%M).log

# Start tracking script runtime
START_TIME=$(date +%s)

# Create necessary folders
mkdir -p "${BLD_LOG%/*}" "${SRC}"

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
    echo "${1}" >>"${BLD_LOG}"
}

# Parse inputs to the script
function parse_parameters() {
    BLD_LLVM_ARGS=()
    while ((${#})); do
        case ${1} in
            -b | --llvm-branch) shift && LLVM_BRANCH=${1} ;;
            -d | --debug) set -x ;;
            -j | --jobs) shift && JOBS=${1} ;;
            -j*) JOBS=${1/-j/} ;;
            -l | --linux-src) shift && LINUX_SRC=$(readlink -f "${1}") ;;
            --lto=* | -n | --no-update | --pgo) BLD_LLVM_ARGS=("${BLD_LLVM_ARGS[@]}" "${1}") ;;
            --lto) shift && BLD_LLVM_ARGS=("${BLD_LLVM_ARGS[@]}" --lto "${1}") ;;
            -s | --skip-tc-build) SKIP_TC_BUILD=true ;;
            -t | --tc-prefix) shift && TC_PREFIX=$(readlink -f "${1}") ;;
            --test-lto-cfi-kernel) TEST_LTO_CFI_KERNEL=true ;;
            *) die "Invalid parameter '${1}'" ;;
        esac
        shift
    done

    [[ -z ${TC_PREFIX} ]] && TC_PREFIX=${BASE}/toolchain
}

# Builds the tools that we are testing
function build_llvm_binutils() {
    ${SKIP_TC_BUILD:=false} && return 0

    header "Building LLVM and binutils"

    [[ -d ${TC_BLD} ]] || git clone git://github.com/ClangBuiltLinux/tc-build "${TC_BLD}"
    git -C "${TC_BLD}" pull --rebase || die "Error updating tc-build" "${?}"

    "${TC_BLD}"/build-llvm.py --assertions \
        --branch "${LLVM_BRANCH:=release/10.x}" \
        --check-targets clang lld llvm \
        --install-folder "${TC_PREFIX}" \
        "${BLD_LLVM_ARGS[@]}" ||
        die "build-llvm.py failed" "${?}"

    "${TC_BLD}"/build-binutils.py --install-folder "${TC_PREFIX}" ||
        die "build-binutils.py failed" "${?}"
}

# Download the kernel source that we are testing if LINUX_SOURCE wasn't specified
function dwnld_kernel_src() {
    [[ -n ${LINUX_SRC} ]] && return 0

    LINUX=linux-5.6.8
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
    header "Updating boot-utils"

    BOOT_UTILS=${SRC}/boot-utils
    [[ -d ${BOOT_UTILS} ]] || git -C "${BOOT_UTILS%/*}" clone git://github.com/ClangBuiltLinux/boot-utils
    git -C "${BOOT_UTILS}" pull
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
        "${TC_PREFIX}"/bin/clang --version | head -n1
        "${TC_PREFIX}"/bin/as --version | head -n1
        echo "Linux $(make -C "${LINUX_SRC}" -s kernelversion)$(get_config_localversion_auto)"
    } >"${BLD_LOG}"
}

# make wrapper for the kernel so we can set all variables that we need
function kmake() { (
    set -x
    time PATH=${TC_PREFIX}/bin:${PATH} \
        make -C "${LINUX_SRC}" \
        -j"${JOBS:=$(nproc)}" \
        -s \
        AR="${AR:-llvm-ar}" \
        CC="${CC:-clang}" \
        HOSTAR="${HOSTAR:-llvm-ar}" \
        HOSTCC="${HOSTCC:-clang}" \
        HOSTCXX="${HOSTCXX:-clang++}" \
        HOSTLD="${HOSTLD:-ld.lld}" \
        HOSTLDFLAGS="${HOSTLDFLAGS--fuse-ld=lld}" \
        LD="${LD:-ld.lld}" \
        O=out \
        NM="${NM:-llvm-nm}" \
        OBJCOPY="${OBJCOPY:-llvm-objcopy}" \
        OBJDUMP="${OBJDUMP:-llvm-objdump}" \
        OBJSIZE="${OBJSIZE:-llvm-size}" \
        READELF="${READELF:-llvm-readelf}" \
        STRIP="${LLVM_STRIP:-llvm-strip}" \
        "${@}"
    RET=${?}
    set +x
    exit ${RET}
); }

# Use config script in kernel source to enable/disable options
function modify_config() {
    set -x
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
        debian/*) modify_config -d CONFIG_SYSTEM_TRUSTED_KEYS ;;

        # Fedora enables BTF, which does not work with Linux 5.6
        # https://github.com/ClangBuiltLinux/linux/issues/871
        # Once 5.7 is out, we can make this depend on pahole being available
        fedora/*) modify_config -d CONFIG_DEBUG_INFO_BTF ;;
    esac
}

# Build arm32 kernels
function build_arm32_kernels() {
    local CROSS_COMPILE KMAKE_ARGS LOG_COMMENT
    CROSS_COMPILE=arm-linux-gnueabi-
    KMAKE_ARGS=("ARCH=arm" "CROSS_COMPILE=${CROSS_COMPILE}" "KCONFIG_ALLCONFIG=${BASE}/configs/le.config")

    header "Building arm32 kernels"

    # Upstream
    kmake "${KMAKE_ARGS[@]}" distclean multi_v5_defconfig
    # https://github.com/ClangBuiltLinux/linux/issues/954
    if [[ ${LLVM_VER_CODE} -lt 120000 ]]; then
        LOG_COMMENT=" (minus CONFIG_TRACING, CONFIG_OPROFILE, and CONFIG_RCU_TRACE)"
        modify_config -d CONFIG_TRACING -d CONFIG_OPROFILE -d CONFIG_RCU_TRACE
    fi
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm32 multi_v5_defconfig${LOG_COMMENT} exit code: ${?}"
    qemu_boot_kernel arm32_v5
    log "arm32 multi_v5_defconfig${LOG_COMMENT} qemu boot exit code: ${?}"

    # https://github.com/ClangBuiltLinux/linux/issues/732
    LD=${CROSS_COMPILE}ld kmake "${KMAKE_ARGS[@]}" distclean aspeed_g5_defconfig all
    log "arm32 aspeed_g5_defconfig exit code: ${?}"
    qemu_boot_kernel arm32_v6
    log "arm32 aspeed_g5_defconfig qemu boot exit code: ${?}"

    kmake "${KMAKE_ARGS[@]}" distclean multi_v7_defconfig all
    log "arm32 multi_v7_defconfig exit code: ${?}"
    qemu_boot_kernel arm32_v7
    log "arm32 multi_v7_defconfig qemu boot exit code: ${?}"

    kmake "${KMAKE_ARGS[@]}" distclean allmodconfig all
    log "arm32 allmodconfig exit code: ${?}"

    kmake "${KMAKE_ARGS[@]}" distclean allyesconfig all
    log "arm32 allyesconfig exit code: ${?}"

    # Debian
    setup_config debian/armmp.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm32 debian config exit code: ${?}"

    # Fedora
    setup_config fedora/armv7hl.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "armv7hl fedora config exit code: ${?}"

    # OpenSUSE
    setup_config opensuse/armv7hl.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "armv7hl opensuse config exit code: ${?}"
}

# Build arm64 kernels
function build_arm64_kernels() {
    local KMAKE_ARGS
    KMAKE_ARGS=("ARCH=arm64" "CROSS_COMPILE=aarch64-linux-gnu-" "KCONFIG_ALLCONFIG=${BASE}/configs/le.config")

    header "Building arm64 kernels"

    # Upstream
    kmake "${KMAKE_ARGS[@]}" distclean defconfig all
    log "arm64 defconfig exit code: ${?}"
    qemu_boot_kernel arm64
    log "arm64 defconfig qemu boot exit code: ${?}"

    kmake "${KMAKE_ARGS[@]}" distclean allmodconfig all
    log "arm64 allmodconfig exit code: ${?}"

    kmake "${KMAKE_ARGS[@]}" distclean allyesconfig all
    log "arm64 allyesconfig exit code: ${?}"

    # Debian
    setup_config debian/arm64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 debian config exit code: ${?}"

    # Fedora
    setup_config fedora/aarch64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 fedora config exit code: ${?}"

    # OpenSUSE
    setup_config opensuse/arm64.config
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 opensuse config exit code: ${?}"
}

# Build mips kernels
function build_mips_kernels() {
    local CROSS_COMPILE KMAKE_ARGS
    CROSS_COMPILE=mipsel-linux-gnu-
    KMAKE_ARGS=("ARCH=mips" "CROSS_COMPILE=${CROSS_COMPILE}")

    header "Building mips kernels"

    # Upstream
    kmake "${KMAKE_ARGS[@]}" distclean malta_kvm_guest_defconfig all
    log "mips malta_kvm_guest_defconfig exit code: ${?}"
    qemu_boot_kernel mipsel
    log "mips malta_kvm_guest_defconfig qemu boot exit code: ${?}"

    kmake "${KMAKE_ARGS[@]}" distclean malta_kvm_guest_defconfig
    modify_config -d CONFIG_CPU_LITTLE_ENDIAN -e CONFIG_CPU_BIG_ENDIAN
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "mips malta_kvm_guest_defconfig plus CONFIG_CPU_BIG_ENDIAN=y exit code: ${?}"
    qemu_boot_kernel mips
    log "mips malta_kvm_guest_defconfig plus CONFIG_CPU_BIG_ENDIAN=y qemu boot exit code: ${?}"
}

# Build powerpc kernels
# Non-working LLVM tools outline:
#   * ld.lld
#     * pseries_defconfig: https://github.com/ClangBuiltLinux/linux/issues/602
#     * ppc64le_defconfig / fedora/ppc64le.config: https://github.com/ClangBuiltLinux/linux/issues/811
#   * llvm-objdump
#     * https://github.com/ClangBuiltLinux/linux/issues/666
function build_powerpc_kernels() {
    local CROSS_COMPILE CTOD KMAKE_ARGS LOG_COMMENT
    CROSS_COMPILE=powerpc-linux-gnu-
    KMAKE_ARGS=("ARCH=powerpc" "CROSS_COMPILE=${CROSS_COMPILE}")

    header "Building powerpc kernels"

    # Upstream
    kmake "${KMAKE_ARGS[@]}" distclean ppc44x_defconfig all
    log "powerpc ppc44x_defconfig exit code: ${?}"
    qemu_boot_kernel ppc32
    log "powerpc ppc44x_defconfig qemu boot exit code: ${?}"

    LD=${CROSS_COMPILE}ld kmake "${KMAKE_ARGS[@]}" distclean pseries_defconfig all
    log "powerpc pseries_defconfig exit code: ${?}"
    qemu_boot_kernel ppc64
    log "powerpc pseries_defconfig qemu boot exit code: ${?}"

    CROSS_COMPILE=powerpc64-linux-gnu-
    KMAKE_ARGS=("ARCH=powerpc" "CROSS_COMPILE=${CROSS_COMPILE}")

    kmake "${KMAKE_ARGS[@]}" distclean powernv_defconfig all
    log "powerpc powernv_defconfig exit code: ${?}"
    qemu_boot_kernel ppc64le
    log "powerpc powernv_defconfig qemu boot exit code: ${?}"

    LD=${CROSS_COMPILE}ld OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" distclean ppc64le_defconfig all
    log "powerpc ppc64le_defconfig exit code: ${?}"

    # Debian
    setup_config debian/powerpc64le.config
    # https://github.com/ClangBuiltLinux/linux/issues/944
    if [[ ${LLVM_VER_CODE} -lt 100001 ]]; then
        CTOD=CONFIG_DRM_AMD_DC
        LOG_COMMENT=" (minus ${CTOD})"
        modify_config -d ${CTOD}
    fi
    LD=${CROSS_COMPILE}ld OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "ppc64le debian config${LOG_COMMENT} exit code: ${?}"

    # Fedora
    setup_config fedora/ppc64le.config
    # https://github.com/ClangBuiltLinux/linux/issues/944
    [[ ${LLVM_VER_CODE} -lt 100001 ]] && modify_config -d ${CTOD}
    LD=${CROSS_COMPILE}ld OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "ppc64le fedora config${LOG_COMMENT} exit code: ${?}"

    # OpenSUSE
    setup_config opensuse/ppc64le.config
    # https://github.com/ClangBuiltLinux/linux/issues/944
    [[ ${LLVM_VER_CODE} -lt 100001 ]] && modify_config -d ${CTOD}
    LD=${CROSS_COMPILE}ld OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "ppc64le opensuse config exit code: ${?}"
}

# Build riscv kernels
function build_riscv_kernels() {
    local KMAKE_ARGS
    KMAKE_ARGS=("ARCH=riscv" "CROSS_COMPILE=riscv64-linux-gnu-")

    # riscv did not build properly for Linux prior to 5.7 and there is an
    # inordinate amount of spam about '-save-restore' before LLVM 11: https://llvm.org/pr44853
    if [[ ${LNX_VER_CODE} -lt 507000 || ${LLVM_VER_CODE} -lt 110000 ]]; then
        header "Skipping riscv kernels"
        return 0
    fi

    kmake "${KMAKE_ARGS[@]}" LLVM_IAS=1 distclean defconfig all
    log "riscv64 defconfig exit code: ${?}"
}

# Build s390x kernels
# Non-working LLVM tools outline:
#   * ld.lld
#   * llvm-objcopy
#   * llvm-objdump
function build_s390x_kernels() {
    local CROSS_COMPILE KMAKE_ARGS
    CROSS_COMPILE=s390x-linux-gnu-
    # For some reason, -Waddress-of-packed-member does not get disabled...
    # Disable it so that real issues/errors can be found
    # TODO: Investigate and file a bug or fix
    KMAKE_ARGS=("ARCH=s390" "CROSS_COMPILE=${CROSS_COMPILE}" "KCFLAGS=-Wno-address-of-packed-member")

    # s390 did not build properly until Linux 5.6
    if [[ ${LNX_VER_CODE} -lt 506000 ]]; then
        header "Skipping s390x kernels"
        return 0
    fi

    header "Building s390x kernels"

    # Upstream
    LD=${CROSS_COMPILE}ld \
        OBJCOPY=${CROSS_COMPILE}objcopy \
        OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" distclean defconfig all
    log "s390x defconfig exit code: ${?}"

    # Debian
    setup_config debian/s390x.config
    LD=${CROSS_COMPILE}ld \
        OBJCOPY=${CROSS_COMPILE}objcopy \
        OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x debian config exit code: ${?}"

    # Fedora
    setup_config fedora/s390x.config
    LD=${CROSS_COMPILE}ld \
        OBJCOPY=${CROSS_COMPILE}objcopy \
        OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x fedora config exit code: ${?}"

    # OpenSUSE
    setup_config opensuse/s390x.config
    LD=${CROSS_COMPILE}ld \
        OBJCOPY=${CROSS_COMPILE}objcopy \
        OBJDUMP=${CROSS_COMPILE}objdump \
        kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "s390x opensuse config exit code: ${?}"
}

# Build x86_64 kernels
function build_x86_64_kernels() {
    local LOG_COMMENT
    header "Building x86_64 kernels"

    # Upstream
    kmake distclean defconfig all
    log "x86_64 defconfig exit code: ${?}"
    qemu_boot_kernel x86_64
    log "x86_64 qemu boot exit code: ${?}"

    kmake distclean allmodconfig
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" (minus CONFIG_STM and CONFIG_TEST_MEMCAT_P)"
        modify_config -d CONFIG_STM -d CONFIG_TEST_MEMCAT_P
    fi
    kmake olddefconfig all
    log "x86_64 allmodconfig${LOG_COMMENT} exit code: ${?}"

    kmake distclean allyesconfig all
    log "x86_64 allyesconfig exit code: ${?}"

    kmake distclean allyesconfig
    # https://github.com/ClangBuiltLinux/linux/issues/678
    modify_config -d CONFIG_SENSORS_APPLESMC
    kmake olddefconfig all KCFLAGS=-O3
    log "x86_64 allyesconfig at -O3 (minus CONFIG_SENSORS_APPLESMC) exit code: ${?}"

    # Arch Linux
    setup_config archlinux/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" (minus CONFIG_STM)"
        modify_config -d CONFIG_STM
    fi
    kmake olddefconfig all
    log "x86_64 archlinux config${LOG_COMMENT} exit code: ${?}"

    # Debian
    setup_config debian/amd64.config
    # https://github.com/ClangBuiltLinux/linux/issues/514
    OBJCOPY=objcopy kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "x86_64 debian config exit code: ${?}"

    # Fedora
    setup_config fedora/x86_64.config
    kmake olddefconfig all
    log "x86_64 fedora config exit code: ${?}"

    # OpenSUSE
    setup_config opensuse/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ ${LNX_VER_CODE} -lt 507000 ]]; then
        LOG_COMMENT=" (minus CONFIG_STM)"
        modify_config -d CONFIG_STM
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/514
    OBJCOPY=objcopy kmake olddefconfig all
    log "x86_64 opensuse config${LOG_COMMENT} exit code: ${?}"
}

# Build Sami Tolvanen's LTO/CFI tree
function build_lto_cfi_kernels() {
    local KMAKE_ARGS
    KMAKE_ARGS=("ARCH=arm64" "CROSS_COMPILE=aarch64-linux-gnu-")

    header "Building LTO/CFI kernels"

    # Grab the latest kernel source
    LINUX_SRC=${SRC}/linux-clang-cfi
    OUT=${LINUX_SRC}/out
    rm -rf "${LINUX_SRC}"
    curl -LSso "${LINUX_SRC}.zip" https://github.com/samitolvanen/linux/archive/clang-cfi.zip
    (cd "${SRC}" && unzip -q "${LINUX_SRC}.zip")
    rm -rf "${LINUX_SRC}.zip"

    # arm64
    kmake "${KMAKE_ARGS[@]}" distclean defconfig
    modify_config -e LTO_CLANG \
        -e CFI_CLANG \
        -e FTRACE \
        -e FUNCTION_TRACER \
        -e DYNAMIC_FTRACE \
        -e LOCK_TORTURE_TEST \
        -e RCU_TORTURE_TEST
    kmake "${KMAKE_ARGS[@]}" olddefconfig all
    log "arm64 defconfig (plus CONFIG_{LTO,CFI}_CLANG and CONFIG_DYNAMIC_FTRACE_WITH_REGS) exit code: ${?}"
    qemu_boot_kernel arm64
    log "arm64 defconfig (plus CONFIG_{LTO,CFI}_CLANG and CONFIG_DYNAMIC_FTRACE_WITH_REGS) qemu boot exit code: ${?}"

    # x86_64
    kmake distclean defconfig
    modify_config -e LTO_CLANG \
        -e CFI_CLANG \
        -e LOCK_TORTURE_TEST \
        -e RCU_TORTURE_TEST
    kmake olddefconfig all
    log "x86_64 defconfig (plus CONFIG_{LTO,CFI}_CLANG) exit code: ${?}"
    qemu_boot_kernel x86_64
    log "x86_64 defconfig (plus CONFIG_{LTO,CFI}_CLANG) qemu boot exit code: ${?}"
}

# Print LLVM/clang version as a 5-6 digit number (e.g. clang 11.0.0 will be 110000)
function create_llvm_ver_code() {
    local CLANG MAJOR MINOR PATCHLEVEL
    CLANG=${TC_PREFIX}/bin/clang
    MAJOR=$(echo __clang_major__ | "${CLANG}" -E -x c - | tail -n 1)
    MINOR=$(echo __clang_minor__ | "${CLANG}" -E -x c - | tail -n 1)
    PATCHLEVEL=$(echo __clang_patchlevel__ | "${CLANG}" -E -x c - | tail -n 1)
    LLVM_VER_CODE=$(printf "%d%02d%02d" "${MAJOR}" "${MINOR}" "${PATCHLEVEL}")
}

# Print Linux version as a 6 digit number (e.g. Linux 5.6.2 will be 506002)
function create_lnx_ver_code() {
    LNX_VER=$(make -C "${LINUX_SRC}" -s kernelversion | sed 's/-rc.*//')
    IFS=. read -ra LNX_VER <<<"${LNX_VER}"
    LNX_VER_CODE=$(printf "%d%02d%03d" "${LNX_VER[@]}")
}

# Build kernels with said toolchains
function build_kernels() {
    OUT=${LINUX_SRC}/out
    create_lnx_ver_code
    create_llvm_ver_code

    build_arm32_kernels
    build_arm64_kernels
    build_mips_kernels
    build_powerpc_kernels
    build_s390x_kernels
    build_x86_64_kernels
    ${TEST_LTO_CFI_KERNEL:=false} && build_lto_cfi_kernels
}

# Boot the kernel in QEMU
function qemu_boot_kernel() {
    "${SRC}"/boot-utils/boot-qemu.sh -a "${1:?}" -k "${OUT}"
}

# Show the results from the build log and show total script runtime
function report_results() {
    header "Toolchain and kernel information"
    head -n3 "${BLD_LOG}"
    header "List of successes"
    grep ": 0" "${BLD_LOG}"
    FAILS=$(tail -n +4 "${BLD_LOG}" | grep -v ": 0")
    if [[ -n ${FAILS} ]]; then
        header "List of failures"
        echo "${FAILS}"
    fi
    echo
    echo "Total script runtime: $(python3 -c "import datetime; print(str(datetime.timedelta(seconds=int($(date +%s) - ${START_TIME}))))")"
}

parse_parameters "${@}"
build_llvm_binutils
dwnld_kernel_src
dwnld_update_boot_utils
log_tc_lnx_ver
build_kernels
report_results
