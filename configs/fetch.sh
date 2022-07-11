#!/usr/bin/env bash
# Update configs from their latest source

# Move to the configs folder
cd "$(dirname "$(realpath "$0")")" || exit ${?}

function parse_parameters() {
    DISTROS=()
    while ((${#})); do
        case ${1} in
            alpine | archlinux | debian | fedora | opensuse) DISTROS=("${DISTROS[@]}" "${1}") ;;
        esac
        shift
    done
    [[ -z ${DISTROS[*]} ]] && DISTROS=(alpine archlinux debian fedora opensuse)
}

# Alpine Linux
function fetch_alpine_config() {
    curl -LSso alpine/"${1}".config https://git.alpinelinux.org/aports/plain/community/linux-edge/config-edge."${1}"
}

# Arch Linux
function fetch_archlinux_config() {
    case ${1} in
        armv7 | aarch64) URL=https://github.com/archlinuxarm/PKGBUILDs/raw/master/core/linux-${1}/config ;;
        x86_64) URL=https://github.com/archlinux/svntogit-packages/raw/packages/linux/trunk/config ;;
        *) return ;;
    esac
    curl -LSso archlinux/"${1}".config "${URL}"
}

# Debian
function fetch_debian_config() { (
    TMP_DIR=$(mktemp -d -p "${PWD}")
    cd "${TMP_DIR}" || exit ${?}

    PACK_VER_SIGNED=5.19.0-rc4
    KER_VER_SIGNED=5.19~rc4-1~exp1
    PACK_VER_UNSIGNED=$PACK_VER_SIGNED
    KER_VER_UNSIGNED=$KER_VER_SIGNED
    case ${1} in
        amd64 | arm64) URL=linux-signed-${1}/linux-image-${PACK_VER_SIGNED}-${1}_${KER_VER_SIGNED}_${1}.deb ;;
        armmp) URL=linux/linux-image-${PACK_VER_UNSIGNED}-${1}_${KER_VER_UNSIGNED}_armhf.deb ;;
        i386) DEB_CONFIG=686 && URL=linux-signed-${1}/linux-image-${PACK_VER_SIGNED}-${DEB_CONFIG}_${KER_VER_SIGNED}_${1}.deb ;;
        powerpc64le) URL=linux/linux-image-${PACK_VER_UNSIGNED}-${1}_${KER_VER_UNSIGNED}_ppc64el.deb ;;
        s390x) URL=linux/linux-image-${PACK_VER_UNSIGNED}-${1}_${KER_VER_UNSIGNED}_${1}.deb ;;
        *) return ;;
    esac

    curl -LSsO http://ftp.us.debian.org/debian/pool/main/l/"${URL}"
    ar x "${URL##*/}"
    tar xJf data.tar.xz
    cp -v boot/config-*-"${DEB_CONFIG:-${1}}" ../debian/"${1}".config
    rm -rf "${TMP_DIR}"
); }

# Fedora
function fetch_fedora_config() {
    curl -LSso fedora/"${1:?}".config https://src.fedoraproject.org/rpms/kernel/raw/rawhide/f/kernel-"${1}"-fedora.config
}

# OpenSUSE
function fetch_opensuse_config() {
    curl -LSso opensuse/"${1:?}".config https://github.com/openSUSE/kernel-source/raw/stable/config/"${1}"/default
}

# Fetch configs for requested distros
function fetch_configs() {
    set -x
    for DISTRO in "${DISTROS[@]}"; do
        case ${DISTRO} in
            alpine) for CONFIG in aarch64 armv7 x86_64; do fetch_alpine_config "${CONFIG}"; done ;;
            archlinux) for CONFIG in armv5 armv7 aarch64 x86_64; do fetch_archlinux_config "${CONFIG}"; done ;;
            debian) for CONFIG in amd64 arm64 armmp i386 powerpc64le s390x; do fetch_debian_config "${CONFIG}"; done ;;
            fedora) for CONFIG in aarch64 armv7hl ppc64le s390x x86_64; do fetch_fedora_config "${CONFIG}"; done ;;
            opensuse) for CONFIG in arm64 armv7hl i386 ppc64le riscv64 s390x x86_64; do fetch_opensuse_config "${CONFIG}"; done ;;
        esac
    done
}

parse_parameters "${@}"
fetch_configs
