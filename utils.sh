#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function utils_sh_shellcheck() {
    die "This function should never be called."
    bld_log_dir=
    failed_log=
    info_log=
    klog=
    krnl_rc=
    linux_src=
    out=
    raw_qemu_ver=
    skipped_log=
    src=
    success_log=
    use_ccache=

    echo "$llvm_ver_code $lnx_ver_code"
}

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
    local log

    case "$1" in
        *failed*) log=$failed_log ;;
        *skipped*) log=$skipped_log ;;
        *success*) log=$success_log ;;
        *) log=$info_log ;;
    esac

    printf "%b\n\n" "$1" >>"$log"
}

# Print formatted time with Python 3
function print_time() {
    python3 -c "import datetime; print(str(datetime.timedelta(seconds=int($2 - $1))))"
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

    echo "Source location: $linux_src"
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

# Print LLVM/clang version as a 5-6 digit number (e.g. clang 11.0.0 will be 110000)
function create_llvm_ver_code() {
    llvm_ver=$(echo "__clang_major__ __clang_minor__ __clang_patchlevel__" | clang -E -x c - | tail -n 1)
    read -ra llvm_ver <<<"$llvm_ver"
    llvm_ver_code=$(printf "%d%02d%02d" "${llvm_ver[@]}")
}

# Print Linux version as a 6 digit number (e.g. Linux 5.6.2 will be 506002)
function create_lnx_ver_code() {
    lnx_ver=$(make -C "$linux_src" -s kernelversion | sed 's/-rc.*//')
    IFS=. read -ra lnx_ver <<<"$lnx_ver"
    lnx_ver_code=$(printf "%d%02d%03d" "${lnx_ver[@]}")
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
