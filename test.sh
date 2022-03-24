#!/usr/bin/env bash

# Make sure that we instantly exit on Ctrl-C
trap 'exit' INT

# Get the absolute location of this repo
root=$(dirname "$(readlink -f "$0")")
[[ -z $root || ! -d $root ]] && exit

# Utility functions
source "$root"/configs.sh || exit
source "$root"/qemu.sh || exit
source "$root"/utils.sh || exit

# Folder setup
src=$root/src

# Start tracking script runtime
start_time=$(date +%s)

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
            -s | --save-objects) save_objects=true ;;
            -t | --tc-prefix) shift && tc_prefix=$(readlink -f "$1") ;;
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
    [[ -z $save_objects ]] && save_objects=false
    [[ -z $use_ccache ]] && use_ccache=false

    # We purposefully do not use [[ -z ... ]] here so that a user can
    # override this with LOCALVERSION=
    : "${LOCALVERSION=-cbl}"
    export LOCALVERSION

    mkdir -p "$bld_log_dir" "$src"

    failed_log=$bld_log_dir/failed.log
    info_log=$bld_log_dir/info.log
    skipped_log=$bld_log_dir/skipped.log
    success_log=$bld_log_dir/success.log
}

# Build kernels with said toolchains
function build_kernels() {
    export_path_if_exists "$binutils_prefix/bin"
    export_path_if_exists "$llvm_prefix/bin"
    export_path_if_exists "$tc_prefix/bin"
    export_path_if_exists "$qemu_prefix/bin"

    set_tool_vars

    header "Build information"
    print_tc_lnx_env_info >"$info_log"
    cat "$info_log"

    create_lnx_ver_code
    create_llvm_ver_code

    for arch in "${arches[@]}"; do
        out=$(cd "$linux_src" && readlink -f -m "${O:-.build}")/$arch
        if ! check_clang_target "$arch"; then
            header "Skipping $arch kernels"
            echo "Reason: clang was not configured with this target"
            log "$arch kernels skipped due to missing clang target"
            continue
        fi
        # shellcheck disable=SC1090
        source "$root"/"$arch".sh || die "$arch.sh does not exist?"
        build_"$arch"_kernels
        $save_objects || rm -fr "$out"
    done
}

# Show the results from the build log and show total script runtime
function report_results() {
    total_runtime="Total script runtime: $(print_time "$start_time" "$(date +%s)")"
    log "$total_runtime"

    # Remove last blank line and full path from errors/warnings because I am OCD :^)
    sed -i -e '${/^$/d}' -e "s;$linux_src/;;g" "$failed_log" "$info_log" "$skipped_log" "$success_log"

    header "Toolchain and kernel information"
    head -n7 "$info_log"

    header "List of successful tests"
    sed '/^$/d' "$success_log"

    if [[ -f $failed_log ]]; then
        header "List of failed tests"
        sed '/^$/d' "$failed_log"
    fi

    if [[ -f $skipped_log ]]; then
        header "List of skipped tests"
        sed '/^$/d' "$skipped_log"
    fi

    echo
    echo "$total_runtime"
}

parse_parameters "$@"
dwnld_update_boot_utils
build_kernels
report_results
