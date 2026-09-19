import lkt.utils


class MakeJob:
    def __init__(
        self, name: str, prereqs: list[str], cmds: list[str], variables: dict[str, str]
    ) -> None:
        self.cmds: list[str] = cmds
        self.name: str = name[0:251]  # allow job name to be used as a log file name
        self.prereqs: list[str] = prereqs
        self.variables: dict[str, str] = variables

    def __str__(self) -> str:
        parts = [f".PHONY: {self.name}"]
        parts += [
            f"{self.name}: {key} := {value}"
            for key in sorted(self.variables)
            if (value := self.variables[key])
        ]
        parts.append(f"{self.name}: {' '.join(self.prereqs)}")
        parts += [f"\t{cmd}" for cmd in self.cmds]
        return '\n'.join(parts)


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
