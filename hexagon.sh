#!/usr/bin/env bash

# Bogus function for shellcheck, it is not called anywhere
function hexagon_shellcheck() {
    die "This function should never be called."
    defconfigs_only=
    linux_src=
    echo "$klog"
}

# Build hexagon kernels
function build_hexagon_kernels() {
    kmake_args=(
        ARCH=hexagon
        LLVM_IAS=1
    )
    if [[ ! -f $linux_src/scripts/Makefile.clang ]]; then
        kmake_args+=(CROSS_COMPILE=hexagon-linux-gnu-)
    fi

    # Hexagon was broken without some fixes
    if ! grep -q "KBUILD_CFLAGS += -mlong-calls" "$linux_src"/arch/hexagon/Makefile || ! [[ -f $linux_src/arch/hexagon/lib/divsi3.S ]]; then
        header "Skipping hexagon kernels"
        echo "Hexagon needs the following fixes from Linux 5.13 to build properly:"
        echo
        echo '  * https://git.kernel.org/linus/788dcee0306e1bdbae1a76d1b3478bb899c5838e'
        echo '  * https://git.kernel.org/linus/6fff7410f6befe5744d54f0418d65a6322998c09'
        echo '  * https://git.kernel.org/linus/f1f99adf05f2138ff2646d756d4674e302e8d02d'
        echo
        echo "Provide a kernel tree with Linux 5.13+ or one with these fixes to build Hexagon kernels."

        log "hexagon kernels skipped due to missing 788dcee0306e, 6fff7410f6be, and/or f1f99adf05f2"

        return 0
    fi

    header "Building hexagon kernels"

    # Upstream
    klog=hexagon-defconfig
    kmake "${kmake_args[@]}" distclean defconfig all
    krnl_rc=$?
    log "hexagon defconfig $(results "$krnl_rc")"

    $defconfigs_only && return 0

    if grep -Fq "EXPORT_SYMBOL(__raw_readsw)" "$linux_src"/arch/hexagon/lib/io.c; then
        klog=hexagon-allmodconfig
        configs_to_disable=()
        grep -q "config WERROR" "$linux_src"/init/Kconfig && configs_to_disable+=(CONFIG_WERROR)
        gen_allconfig
        kmake "${kmake_args[@]}" ${config_file:+KCONFIG_ALLCONFIG=$config_file} distclean allmodconfig all
        krnl_rc=$?
        log "hexagon allmodconfig $(results "$krnl_rc")"
        rm -f "$config_file"
    else
        log "hexagon allmodconfig skipped due to missing ffb92ce826fd"
    fi
}
