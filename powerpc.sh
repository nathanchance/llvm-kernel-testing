#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function powerpc_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    llvm_ver_code=
    linux_src=
    echo "$klog"
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
    else
        log "powerpc pmac32_defconfig skipped due to missing 297565aa22cf"
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
        ctod=CONFIG_PPC_DISABLE_WERROR
        if [[ -f $linux_src/arch/powerpc/configs/disable-werror.config ]]; then
            pseries_targets+=(disable-werror.config all)
        else
            sc_dwerror=true
        fi
        log_comment=" + ${ctod}=y"
    else
        pseries_targets+=(all)
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/602
    kmake "${kmake_args[@]}" LD=${CROSS_COMPILE}ld distclean "${pseries_targets[@]}"
    krnl_rc=$?
    if ${sc_dwerror:=false}; then
        scripts_config -e $ctod
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
