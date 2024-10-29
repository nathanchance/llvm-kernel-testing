#!/usr/bin/env python3

import lkt.runner
from lkt.version import ClangVersion, LinuxVersion

KERNEL_ARCH = 'hexagon'
CLANG_TARGET = 'hexagon-linux-musl'


class HexagonLKTRunner(lkt.runner.LKTRunner):

    def __init__(self):
        super().__init__(KERNEL_ARCH, CLANG_TARGET)

    def _add_defconfig_runners(self):
        runner = lkt.runner.LLVMKernelRunner()
        runner.configs = ['defconfig']
        self._runners.append(runner)

    def _add_otherconfig_runners(self):
        # ffb92ce826fd8 landed in 5.16 but it had 'Cc: stable', so we need to
        # check for its presence. However, just checking for that is no longer
        # sufficient, as arch/hexagon/lib/io.c is getting removed in 6.13
        # (https://git.kernel.org/arnd/asm-generic/c/a8cb1e92d29096b1fe58ef6fdcee699196eac1bd),
        # which breaks the check in lkt/source.py.
        ffb92ce826fd8_ver = LinuxVersion(5, 16, 0)
        have_ffb92ce826fd8 = self.lsm.version >= ffb92ce826fd8_ver or 'ffb92ce826fd8' in self.lsm.commits
        # https://github.com/ClangBuiltLinux/linux/issues/1407
        min_llvm_ver_for_allmod = ClangVersion(13, 0, 0)
        if have_ffb92ce826fd8 and self._llvm_version >= min_llvm_ver_for_allmod:
            runner = lkt.runner.LLVMKernelRunner()
            runner.configs = ['allmodconfig']
            # https://github.com/llvm/llvm-project/issues/80185#issuecomment-2187294487
            if self._llvm_version >= ClangVersion(19, 0, 0):
                runner.configs.append('CONFIG_FORTIFY_KUNIT_TEST=n')
            self._runners.append(runner)
        else:
            self._skip_one(
                f"{KERNEL_ARCH} allmodconfig",
                f"either lack of ffb92ce826fd8 (from {ffb92ce826fd8_ver}) or LLVM < {min_llvm_ver_for_allmod} (using '{self._llvm_version}')",
            )

    def run(self):
        if self.only_test_boot:
            return self._skip_all('only testing boot', 'Only boot testing was requested')

        if not ('788dcee0306e1' in self.lsm.commits and 'f1f99adf05f21' in self.lsm.commits):
            print_text = (
                'Hexagon needs the following fixes from Linux 5.13 to build properly:\n'
                '\n'
                '  * https://git.kernel.org/linus/788dcee0306e1bdbae1a76d1b3478bb899c5838e\n'
                '  * https://git.kernel.org/linus/6fff7410f6befe5744d54f0418d65a6322998c09\n'
                '  * https://git.kernel.org/linus/f1f99adf05f2138ff2646d756d4674e302e8d02d\n'
                '\n'
                'Provide a kernel tree with Linux 5.13+ or one with these fixes to build Hexagon kernels.'
            )
            return self._skip_all(
                f"missing 788dcee0306e, 6fff7410f6be, and/or f1f99adf05f2 (from {LinuxVersion(5, 13 ,0)})",
                print_text)

        if '6f5b41a2f5a63' not in self.lsm.commits:
            self.make_vars['CROSS_COMPILE'] = CLANG_TARGET

        if 'def' in self.targets:
            self._add_defconfig_runners()

        if 'other' in self.targets:
            self._add_otherconfig_runners()

        return super().run()
