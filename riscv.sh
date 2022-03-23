#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function riscv_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    llvm_ver_code=
    linux_src=
    lnx_ver_code=
    echo "$klog"
}

# Build riscv kernels
function build_riscv_kernels() {
    local kmake_args
    CROSS_COMPILE=riscv64-linux-gnu-
    kmake_args=(
        ARCH=riscv
        CROSS_COMPILE="$CROSS_COMPILE"
    )

    # riscv did not build properly for Linux prior to 5.7
    if [[ $lnx_ver_code -lt 507000 ]]; then
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
            echo "Provide a kernel tree with Linux 5.7 or newer to build RISC-V kernels."

            log "riscv kernels skipped due to missing 52e7c52d2ded, fdff9911f266, and/or abc71bf0a703"
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
