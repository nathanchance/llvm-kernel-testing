#!/usr/bin/env bash

BASE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
SRC=${BASE}/src
mkdir -p "${SRC}"
rm -rf "${SRC}"/logs

# LLVM 11.0.0 and linux-next
[[ -d ${SRC}/linux-next ]] || git -C "${SRC}" clone git://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git
( cd "${SRC}"/linux-next && \
  git fetch origin && \
  git reset --hard origin/master )
"${BASE}"/qualify-llvm.sh --linux-src "${SRC}"/linux-next --llvm-branch master

# LLVM 11.0.0 and mainline + LTO/CFI kernel
[[ -d ${SRC}/linux ]] || git -C "${SRC}" clone git://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git
( cd "${SRC}"/linux-next && git pull --rebase )
"${BASE}"/qualify-llvm.sh --linux-src "${SRC}"/linux --skip-tc-build --test-lto-cfi-kernel

# LLVM 11.0.0 and latest stable + LTS kernel
[[ -d ${SRC}/linux-stable ]] || git -C "${SRC}" clone git://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git linux-stable
for VER in 5.6 5.4; do
    ( cd "${SRC}"/linux-stable && \
      git checkout linux-${VER}.y && \
      git pull --rebase ) &&
    "${BASE}"/qualify-llvm.sh --linux-src "${SRC}"/linux-stable --skip-tc-build
done

# LLVM 10.0.0 and linux-next
"${BASE}"/qualify-llvm.sh --linux-src "${SRC}"/linux-next

# LLVM 10.0.0 and mainline + LTO/CFI kernel
"${BASE}"/qualify-llvm.sh --linux-src "${SRC}"/linux --skip-tc-build --test-lto-cfi-kernel

# LLVM 10.0.0 and latest stable + LTS kernel
for VER in 5.6 5.4; do
    ( cd "${SRC}"/linux-stable && git checkout linux-${VER}.y ) && \
    "${BASE}"/qualify-llvm.sh --linux-src "${SRC}"/linux-stable --skip-tc-build
done
