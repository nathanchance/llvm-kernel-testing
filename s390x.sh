#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function riscv_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    linux_src=
    lnx_ver_code=
    echo "$klog"
}

# Build s390x kernels
# Non-working LLVM tools outline:
#   * ld.lld
#   * llvm-objcopy
#   * llvm-objdump
function build_s390x_kernels() {
    local CROSS_COMPILE kmake_args log_comment
    CROSS_COMPILE=s390x-linux-gnu-
    kmake_args=(
        ARCH=s390
        CROSS_COMPILE="$CROSS_COMPILE"
        LD="${CROSS_COMPILE}"ld
        OBJCOPY="${CROSS_COMPILE}"objcopy
        OBJDUMP="${CROSS_COMPILE}"objdump
    )

    # s390 did not build properly until Linux 5.6
    if [[ $lnx_ver_code -lt 506000 ]]; then
        header "Skipping s390x kernels"
        echo "Reason: s390 kernels did not build properly until Linux 5.6"
        echo "        https://lore.kernel.org/lkml/your-ad-here.call-01580230449-ext-6884@work.hours/"
        return 0
    fi

    header "Building s390x kernels"

    check_binutils s390x || return
    print_binutils_info
    echo

    # Upstream
    klog=s390x-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "s390x defconfig $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x defconfig qemu boot $(qemu=1 results "$?")"

    $defconfigs_only && return 0

    klog=s390x-allnoconfig
    kmake "${kmake_args[@]}" distclean allnoconfig all
    log "s390x allnoconfig $(results "$?")"

    klog=s390x-tinyconfig
    kmake "${kmake_args[@]}" distclean tinyconfig all
    log "s390x tinyconfig $(results "$?")"

    klog=s390x-allmodconfig
    configs_to_disable=()
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    gen_allconfig
    kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "s390x allmodconfig$log_comment $(results "$?")"
    rm -f "$config_file"

    # Debian
    klog=s390x-debian
    setup_config debian/s390x.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "s390x debian config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x debian config qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=s390x-fedora
    log_comment=""
    setup_config fedora/s390x.config
    if grep -Eq '"(o|n|x)i.*%0,%b1.*n"' "$linux_src"/arch/s390/include/asm/bitops.h; then
        log_comment+=" + CONFIG_MARCH_Z196=y (https://github.com/ClangBuiltLinux/linux/issues/1264)"
        scripts_config -d MARCH_ZEC12 -e MARCH_Z196
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "s390x fedora config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x fedora config$log_comment qemu boot $(qemu=1 results "$?")"

    # OpenSUSE
    klog=s390x-opensuse
    setup_config opensuse/s390x.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "s390x opensuse config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel s390
    log "s390x opensuse config qemu boot $(qemu=1 results "$?")"
}
