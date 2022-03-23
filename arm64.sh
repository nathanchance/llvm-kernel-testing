#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function arm64_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    llvm_ver_code=
    linux_src=
    lnx_ver_code=
    echo "$klog"
}

# Build arm64 kernels
function build_arm64_kernels() {
    local kmake_args
    kmake_args=(ARCH=arm64)

    header "Building arm64 kernels"

    if [[ $(uname -m) = "aarch64" ]]; then
        unset CROSS_COMPILE
    else
        CROSS_COMPILE=aarch64-linux-gnu-
    fi

    if [[ $lnx_ver_code -ge 510000 ]]; then
        kmake_args+=(LLVM_IAS=1)
        if [[ ! -f $linux_src/scripts/Makefile.clang && -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
    else
        if [[ -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
        check_binutils arm64 || return
        print_binutils_info
        echo
    fi

    # Upstream
    klog=arm64-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "arm64 defconfig $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 defconfig qemu boot $(qemu=1 results "$?")"

    if [[ $llvm_ver_code -ge 130000 ]]; then
        klog=arm64be-defconfig
        kmake "${kmake_args[@]}" distclean defconfig
        swap_endianness l2b
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y $(results "$krnl_rc")"
        qemu_boot_kernel arm64be
        log "arm64 defconfig + CONFIG_CPU_BIG_ENDIAN=y qemu boot $(qemu=1 results "$?")"
    fi

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig; then
        klog=arm64-defconfig-lto
        kmake "${kmake_args[@]}" distclean defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "$krnl_rc")"
        qemu_boot_kernel arm64
        log "arm64 defconfig + CONFIG_LTO_CLANG_THIN=y qemu boot $(qemu=1 results "$?")"
    fi

    if grep -q "config CFI_CLANG" "$linux_src"/arch/Kconfig && [[ $llvm_ver_code -ge 120000 ]]; then
        klog=arm64-defconfig-lto-scs-cfi
        kmake "${kmake_args[@]}" distclean defconfig
        tmp_config=$(mktemp --suffix=.config)
        cat <<EOF >"$tmp_config"
CONFIG_CFI_CLANG=y
CONFIG_LTO_CLANG_THIN=y
CONFIG_LTO_NONE=n
CONFIG_SHADOW_CALL_STACK=y
EOF
        merge_config "$tmp_config"
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y $(results "$krnl_rc")"
        qemu_boot_kernel arm64
        log "arm64 defconfig + CONFIG_CFI_CLANG=y + CONFIG_SHADOW_CALL_STACK=y qemu boot $(qemu=1 results "$?")"
        rm "$tmp_config"
    fi

    $defconfigs_only && return 0

    configs_to_disable=()
    grep -q 'prompt "Endianness"' "$linux_src"/arch/arm64/Kconfig || configs_to_disable+=(CONFIG_CPU_BIG_ENDIAN)
    # https://github.com/ClangBuiltLinux/continuous-integration2/issues/246
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    gen_allconfig
    klog=arm64-allmodconfig
    kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "arm64 allmodconfig$log_comment $(results "$?")"
    rm -f "$config_file"

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig; then
        configs_to_disable=(CONFIG_GCOV_KERNEL CONFIG_KASAN)
        grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
        gen_allconfig
        echo "CONFIG_LTO_CLANG_THIN=y" >>"$config_file"
        klog=arm64-allmodconfig-thinlto
        kmake "${kmake_args[@]}" KCONFIG_ALLCONFIG="$config_file" distclean allmodconfig all
        log "arm64 allmodconfig$log_comment + CONFIG_LTO_CLANG_THIN=y $(results "$?")"
        rm -f "$config_file"
    fi

    klog=arm64-allnoconfig
    kmake "${kmake_args[@]}" distclean allnoconfig all
    log "arm64 allnoconfig $(results "$?")"

    klog=arm64-tinyconfig
    kmake "${kmake_args[@]}" distclean tinyconfig all
    log "arm64 tinyconfig $(results "$?")"

    # Alpine Linux
    klog=arm64-alpine
    setup_config alpine/aarch64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 alpine config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 alpine config qemu boot $(qemu=1 results "$?")"

    # Arch Linux ARM
    klog=arm64-archlinux
    setup_config archlinux/aarch64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 archlinux config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 archlinux config qemu boot $(qemu=1 results "$?")"

    # Debian
    klog=arm64-debian
    setup_config debian/arm64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 debian config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 debian config qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=arm64-fedora
    log_comment=""
    setup_config fedora/aarch64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 fedora config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 fedora config$log_comment qemu boot $(qemu=1 results "$?")"

    # OpenSUSE
    klog=arm64-opensuse
    setup_config opensuse/arm64.config
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "arm64 opensuse config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel arm64
    log "arm64 opensuse config qemu boot $(qemu=1 results "$?")"
}
