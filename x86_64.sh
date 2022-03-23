#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function x86_64_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    llvm_ver_code=
    linux_src=
    lnx_ver_code=
    echo "$klog"
}

# Build x86_64 kernels
function build_x86_64_kernels() {
    local log_comment kmake_args
    header "Building x86_64 kernels"

    kmake_args=(ARCH=x86_64)

    if [[ $(uname -m) = "x86_64" ]]; then
        unset CROSS_COMPILE
    else
        CROSS_COMPILE=x86_64-linux-gnu-
    fi

    if [[ $lnx_ver_code -ge 510000 ]]; then
        export LLVM_IAS=1
        if [[ ! -f $linux_src/scripts/Makefile.clang && -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
    else
        if [[ -n $CROSS_COMPILE ]]; then
            kmake_args+=(CROSS_COMPILE="$CROSS_COMPILE")
        fi
        check_binutils x86_64 || return
        print_binutils_info
        echo
    fi

    # Upstream
    klog=x86_64-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "x86_64 defconfig $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 qemu boot $(qemu=1 results "$?")"

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig; then
        klog=x86_64-defconfig-lto
        kmake "${kmake_args[@]}" distclean defconfig
        scripts_config -d LTO_NONE -e LTO_CLANG_THIN
        kmake "${kmake_args[@]}" olddefconfig all
        krnl_rc=$?
        log "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y $(results "$krnl_rc")"
        qemu_boot_kernel x86_64
        log "x86_64 defconfig + CONFIG_LTO_CLANG_THIN=y qemu boot $(qemu=1 results "$?")"
    fi

    $defconfigs_only && return 0

    klog=x86_64-allmodconfig
    configs_to_disable=()
    grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
    # https://github.com/ClangBuiltLinux/linux/issues/515
    [[ $lnx_ver_code -lt 507000 ]] && configs_to_disable+=(CONFIG_STM CONFIG_TEST_MEMCAT_P)
    gen_allconfig
    [[ $lnx_ver_code -lt 507000 ]] && log_comment+=" + (https://github.com/ClangBuiltLinux/linux/issues/515)"
    kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
    log "x86_64 allmodconfig$log_comment $(results "$?")"
    rm -f "$config_file"

    klog=x86_64-allmodconfig-O3
    kmake "${kmake_args[@]}" distclean allmodconfig
    # https://github.com/ClangBuiltLinux/linux/issues/678
    if [[ $lnx_ver_code -lt 508000 ]]; then
        log_comment=" + CONFIG_SENSORS_APPLESMC=n (https://github.com/ClangBuiltLinux/linux/issues/678)"
        scripts_config -d CONFIG_SENSORS_APPLESMC
    elif grep -q "config WERROR" "$linux_src"/init/Kconfig; then
        ctod=CONFIG_WERROR
        log_comment=" + ${ctod}=n"
        scripts_config -d $ctod
    else
        unset log_comment
    fi
    kmake "${kmake_args[@]}" olddefconfig all KCFLAGS="${KCFLAGS:+${KCFLAGS} }-O3"
    log "x86_64 allmodconfig at -O3$log_comment $(results "$?")"

    if grep -q "config LTO_CLANG_THIN" "$linux_src"/arch/Kconfig && [[ $llvm_ver_code -ge 110000 ]]; then
        configs_to_disable=(CONFIG_GCOV_KERNEL CONFIG_KASAN)
        grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
        gen_allconfig
        echo "CONFIG_LTO_CLANG_THIN=y" >>"$config_file"
        klog=x86_64-allmodconfig-thinlto
        kmake "${kmake_args[@]}" KCONFIG_ALLCONFIG="$config_file" distclean allmodconfig all
        log "x86_64 allmodconfig$log_comment + CONFIG_LTO_CLANG_THIN=y $(results "$?")"
        rm -f "$config_file"
    fi

    # Alpine Linux
    klog=x86_64-alpine
    log_comment=""
    setup_config alpine/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "x86_64 alpine config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 alpine config$log_comment qemu boot $(qemu=1 results "$?")"

    # Arch Linux
    klog=x86_64-archlinux
    log_comment=""
    setup_config archlinux/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "x86_64 archlinux config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 archlinux config$log_comment qemu boot $(qemu=1 results "$?")"

    # Debian
    klog=x86_64-debian
    setup_config debian/amd64.config
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake "${kmake_args[@]}" OBJCOPY=${CROSS_COMPILE}objcopy olddefconfig all
    krnl_rc=$?
    log "x86_64 debian config $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 debian config qemu boot $(qemu=1 results "$?")"

    # Fedora
    klog=x86_64-fedora
    log_comment=""
    setup_config fedora/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n + CONFIG_TEST_MEMCAT_P=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM -d CONFIG_TEST_MEMCAT_P
    fi
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "x86_64 fedora config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 fedora config$log_comment qemu boot $(qemu=1 results "$?")"

    # OpenSUSE
    klog=x86_64-opensuse
    log_comment=""
    setup_config opensuse/x86_64.config
    # https://github.com/ClangBuiltLinux/linux/issues/515
    if [[ $lnx_ver_code -lt 507000 ]]; then
        log_comment+=" + CONFIG_STM=n (https://github.com/ClangBuiltLinux/linux/issues/515)"
        scripts_config -d CONFIG_STM
    fi
    # https://github.com/ClangBuiltLinux/linux/issues/514
    kmake "${kmake_args[@]}" OBJCOPY=${CROSS_COMPILE}objcopy olddefconfig all
    krnl_rc=$?
    log "x86_64 opensuse config$log_comment $(results "$krnl_rc")"
    qemu_boot_kernel x86_64
    log "x86_64 opensuse config$log_comment qemu boot $(qemu=1 results "$?")"

    unset LLVM_IAS
}
