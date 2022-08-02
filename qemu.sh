#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function qemu_shellcheck() {
    die "This function should never be called."
    boot_utils=
    krnl_rc=
    out=
}

# Print QEMU version as a 5-6 digit number (e.g. QEMU 6.1.0 will be 60100)
function create_qemu_ver_code() {
    raw_qemu_ver=$(qemu-system-"$qemu_suffix" --version | head -1 | cut -d ' ' -f 4)
    IFS=. read -ra qemu_ver <<<"$raw_qemu_ver"
    qemu_ver_code=$(printf "%d%02d%02d" "${qemu_ver[@]}")
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
        "$boot_utils"/boot-qemu.py -a "$1" -k "$out"
    fi
}
