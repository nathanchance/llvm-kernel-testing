#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function x86_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    llvm_ver_code=
    linux_src=
    lnx_ver_code=
    log_comment=
    nft_log_comment=
    echo "$klog"
}

# Build x86 kernels
function build_x86_kernels() {
    # x86 did not build properly until Linux 5.9
    if [[ $lnx_ver_code -lt 509000 ]]; then
        header "Skipping x86 kernels"
        echo "Reason: x86 kernels did not build properly until Linux 5.9"
        echo "        https://github.com/ClangBuiltLinux/linux/issues/194"

        log "x86 kernels skipped due to missing 158807de5822"

        return 0
    elif [[ $llvm_ver_code -gt 120000 ]] &&
        ! grep -q "R_386_PLT32:" "$linux_src"/arch/x86/tools/relocs.c; then
        header "Skipping x86 kernels"

        echo "Reason: x86 kernels do not build properly with LLVM 12.0.0+ without R_386_PLT32 handling"
        echo "        https://github.com/ClangBuiltLinux/linux/issues/1210"

        log "x86 kernels skipped due to missing bb73d07148c4 with LLVM > 12.0.0"

        return 0
    elif ! grep -q CLANG_FLAGS "$linux_src"/arch/x86/boot/compressed/Makefile; then
        header "Skipping x86_64 kernels"
        echo "x86 kernels do not cross compile without https://git.kernel.org/linus/d5cbd80e302dfea59726c44c56ab7957f822409f"

        log "x86 kernels skipped due to missing d5cbd80e302d on a non-x86_64 host"

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
    x86_fortify_configs -a
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
    x86_fortify_configs
    kmake "${kmake_args[@]}" olddefconfig all
    log "i386 debian config$log_comment $(results "$?")"

    # OpenSUSE
    klog=i386-opensuse
    setup_config opensuse/i386.config
    kmake "${kmake_args[@]}" olddefconfig all
    log "i386 opensuse config$log_comment $(results "$?")"
}
