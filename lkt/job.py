import lkt.utils


class TestJob:
    def __init__(
        self,
        arch: str,
        configs: list[lkt.utils.PathString],
        bootable: bool = False,
        boot_utils_arch: str = '',
        image_target: str = '',
    ) -> None:
        if not boot_utils_arch:
            boot_utils_arch = arch

        self.bootable: bool = bootable
        self.boot_utils_arch: str = boot_utils_arch
        self.configs: list[lkt.utils.PathString] = configs
        self.extra_make_targets: list[str] = []
        self.image_target: str = image_target
        self.make_vars: lkt.utils.MakeVars = {
            'ARCH': arch,
            'LLVM': '1',
            'LLVM_IAS': '1',
            'LOCALVERSION': '-cbl',
        }
        self.override_make_vars: lkt.utils.MakeVars = {}
