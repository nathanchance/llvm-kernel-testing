#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function arm32_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    llvm_ver_code=
    linux_src=
    lnx_ver_code=
    echo "$klog"
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

