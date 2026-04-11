#!/usr/bin/env python3

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'hexagon'
CLANG_TARGET = 'hexagon-linux-musl'


class HexagonLKTRunner(lkt.runner.LKTRunner):
    def __init__(self) -> None:
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self) -> None:
        runner = lkt.runner.LLVMKernelRunner()
        runner.configs = ['defconfig']
        self._runners.append(runner)

    def _add_otherconfig_runners(self) -> None:
        # ffb92ce826fd8 landed in 5.16 but it had 'Cc: stable', so we need to
        # check for its presence. However, just checking for that is no longer
        # sufficient, as arch/hexagon/lib/io.c is getting removed in 6.13
        # (https://git.kernel.org/linus/a8cb1e92d29096b1fe58ef6fdcee699196eac1bd),
        # which breaks the check in lkt/source.py.
        ffb92ce826fd8_ver = LinuxVersion(5, 16, 0)
        have_ffb92ce826fd8 = (
            self.lsm.version >= ffb92ce826fd8_ver
            or 'ffb92ce826fd801acb0f4e15b75e4ddf0d189bde' in self.lsm.commits
        )
        # Misaligned constant address
        # https://github.com/ClangBuiltLinux/linux/issues/1407
        min_llvm_ver_for_allmod = ClangVersion(13, 0, 0)
        if have_ffb92ce826fd8 and self._llvm_version >= min_llvm_ver_for_allmod:
            runner = lkt.runner.LLVMKernelRunner()
            runner.configs = ['allmodconfig']
            # https://github.com/llvm/llvm-project/issues/80185#issuecomment-2187294487
            if self._llvm_version[0] == 19:
                runner.configs.append('CONFIG_FORTIFY_KUNIT_TEST=n')
            self._runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} allmodconfig",
                f"either lack of ffb92ce826fd8 (from {ffb92ce826fd8_ver}) or LLVM < {min_llvm_ver_for_allmod} (using '{self._llvm_version}')",
            )

    def run(self) -> list[lkt.runner.Result]:
        if self.only_test_boot:
            return self._skip_all('only testing boot', 'Only boot testing was requested')

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if 'other' in self.targets:
            self._add_otherconfig_runners()

        return super().run()
