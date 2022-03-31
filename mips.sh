#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function mips_shellcheck() {
    die "This function should never be called."
    llvm_ver_code=
    linux_src=
    echo "$klog"
}

# Build mips kernels
function build_mips_kernels() {
    local CROSS_COMPILE kmake_args
    for cross_compile in mips{64,el}-linux-gnu-; do
        command -v "$cross_compile"as &>/dev/null && break
    done
    CROSS_COMPILE=$cross_compile
    kmake_args=(
        ARCH=mips
        CROSS_COMPILE="$CROSS_COMPILE"
    )

    header "Building mips kernels"

    check_binutils mips || return
    print_binutils_info
    echo

    # https://git.kernel.org/mips/c/c47c7ab9b53635860c6b48736efdd22822d726d7
    if ! grep -q "CONFIG_BLK_DEV_INITRD=y" "$linux_src"/arch/mips/configs/malta_defconfig; then
        initrd_comment=" + CONFIG_BLK_DEV_INITRD=y"
        enable_initrd=true
    fi

    # Upstream
    klog=mipsel-malta
    kmake "${kmake_args[@]}" distclean malta_defconfig
    ${enable_initrd:=false} && scripts_config -e BLK_DEV_INITRD
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "mips malta_defconfig$initrd_comment $(results "$krnl_rc")"
    qemu_boot_kernel mipsel
    log "mips malta_defconfig$initrd_comment qemu boot $(qemu=1 results "$?")"

    klog=mipsel-malta-kaslr
    kmake "${kmake_args[@]}" distclean malta_defconfig
    ${enable_initrd} && scripts_config -e BLK_DEV_INITRD
    scripts_config \
        -e RELOCATABLE \
        --set-val RELOCATION_TABLE_SIZE 0x00200000 \
        -e RANDOMIZE_BASE
    kmake "${kmake_args[@]}" olddefconfig all
    krnl_rc=$?
    log "mips malta_defconfig$initrd_comment + CONFIG_RANDOMIZE_BASE=y $(results "$krnl_rc")"
    qemu_boot_kernel mipsel
    log "mips malta_defconfig$initrd_comment + CONFIG_RANDOMIZE_BASE=y qemu boot $(qemu=1 results "$?")"

    # https://github.com/ClangBuiltLinux/linux/issues/1025
    klog=mips-malta
    [[ -f $linux_src/arch/mips/vdso/Kconfig && $llvm_ver_code -lt 130000 ]] && mips_be_ld=${CROSS_COMPILE}ld
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean malta_defconfig
    ${enable_initrd} && scripts_config -e BLK_DEV_INITRD
    swap_endianness l2b
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} olddefconfig all
    krnl_rc=$?
    log "mips malta_defconfig$initrd_comment + CONFIG_CPU_BIG_ENDIAN=y $(results "$krnl_rc")"
    qemu_boot_kernel mips
    log "mips malta_defconfig$initrd_comment + CONFIG_CPU_BIG_ENDIAN=y qemu boot $(qemu=1 results "$?")"

    klog=mips-32r1
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r1_defconfig all
    log "mips 32r1_defconfig $(results "$?")"

    klog=mips-32r1el
    kmake "${kmake_args[@]}" distclean 32r1el_defconfig all
    log "mips 32r1el_defconfig $(results "$?")"

    klog=mips-32r2
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r2_defconfig all
    log "mips 32r2_defconfig $(results "$?")"

    klog=mips-32r2el
    kmake "${kmake_args[@]}" distclean 32r2el_defconfig all
    log "mips 32r2el_defconfig $(results "$?")"

    # https://github.com/ClangBuiltLinux/linux/issues/1241
    klog=mips-32r2
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r2_defconfig all
    log "mips 32r2_defconfig $(results "$?")"

    klog=mips-32r2el
    kmake "${kmake_args[@]}" distclean 32r2el_defconfig all
    log "mips 32r2el_defconfig $(results "$?")"

    # https://github.com/llvm/llvm-project/issues/48039
    if [[ $llvm_ver_code -ge 120000 ]]; then
        klog=mips-32r6
        kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean 32r6_defconfig all
        log "mips 32r6_defconfig $(results "$?")"

        klog=mips-32r6el
        kmake "${kmake_args[@]}" distclean 32r6el_defconfig all
        log "mips 32r6el_defconfig $(results "$?")"
    fi

    klog=mips-allnoconfig
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean allnoconfig all
    log "mips allnoconfig $(results "$?")"

    klog=mips-tinyconfig
    kmake "${kmake_args[@]}" ${mips_be_ld:+LD=$mips_be_ld} distclean tinyconfig all
    log "mips tinyconfig $(results "$?")"
}
