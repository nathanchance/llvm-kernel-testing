#!/usr/bin/env bash
# Update configs from their latest source

# Move to the configs folder
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" || exit ${?}

function parse_parameters() {
    DISTROS=( )
    while (( ${#} )); do
        case ${1} in
            archlinux|debian|fedora|opensuse) DISTROS=( "${DISTROS[@]}" "${1}" ) ;;
        esac
        shift
    done
    [[ -z ${DISTROS[*]} ]] && DISTROS=( archlinux debian fedora )
}

# Arch Linux
function fetch_archlinux_config() {
    curl -LSso archlinux/x86_64.config 'https://git.archlinux.org/svntogit/packages.git/plain/trunk/config?h=packages/linux'
}

# Debian
function fetch_debian_config() {(
    TMP_DIR=$(mktemp -d -p "${PWD}")
    cd "${TMP_DIR}" || exit ${?}

    PACK_VER=5.4.0-4
    KER_VER=5.4.19-1
    case ${1} in
        amd64|arm64) URL=linux-signed-${1}/linux-image-${PACK_VER}-${1}_${KER_VER}_${1}.deb ;;
        armmp) URL=linux/linux-image-${PACK_VER}-${1}_${KER_VER}_armhf.deb ;;
        powerpc64le) URL=linux/linux-image-${PACK_VER}-${1}_${KER_VER}_ppc64el.deb ;;
        s390x) URL=linux/linux-image-${PACK_VER}-${1}_${KER_VER}_${1}.deb ;;
        *) return ;;
    esac

    curl -LSsO http://ftp.us.debian.org/debian/pool/main/l/"${URL}"
    ar x "${URL##*/}"
    tar xJf data.tar.xz
    cp -v boot/config-${PACK_VER}-"${1}" ../debian/"${1}".config
    rm -rf "${TMP_DIR}"
)}

# Fedora
function fetch_fedora_config() {
    curl -LSso fedora/"${1:?}".config 'https://git.kernel.org/pub/scm/linux/kernel/git/jwboyer/fedora.git/plain/fedora/configs/kernel-5.6.0-'"${1}"'.config?h=kernel-5.6.0-300.fc32'
}

# OpenSUSE
function fetch_opensuse_config() {
    curl -LSso opensuse/"${1:?}".config 'http://kernel.opensuse.org/cgit/kernel-source/plain/config/'"${1}"'/default'
}

# Fetch configs for requested distros
function fetch_configs() {
    for DISTRO in "${DISTROS[@]}"; do
        case ${DISTRO} in
            archlinux) fetch_archlinux_config ;;
            debian) for CONFIG in amd64 arm64 armmp powerpc64le s390x; do fetch_debian_config "${CONFIG}"; done ;;
            fedora) for CONFIG in aarch64 armv7hl ppc64le s390x x86_64; do fetch_fedora_config "${CONFIG}"; done ;;
            opensuse) for CONFIG in arm64 armv7hl ppc64le s390x x86_64; do fetch_opensuse_config "${CONFIG}"; done ;;
        esac
    done
}

parse_parameters "${@}"
fetch_configs
