#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build E310 components only in an explicitly selected external workspace."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import yaml

from board_data import BoardDataError, REPOSITORY_ROOT, external_path, load_board as load_board_data
from validate_boards import ContractError


ROOT = REPOSITORY_ROOT
PREPARE = ROOT / "tools" / "prepare_component.py"
ASSEMBLE = ROOT / "tools" / "assemble_e310.py"
SELECT_UENV = ROOT / "tools" / "select_uboot_uenv.py"
FPGA_CACHE = ROOT / "tools" / "fpga_cache.py"
COMPONENTS = ("hdl", "linux", "u_boot", "buildroot")


class BuildError(RuntimeError):
    pass


def load_board() -> dict[str, object]:
    return load_board_data("e310")


def external_workspace(path: Path) -> Path:
    return external_path(path, "--workspace")


def source_dir(workspace: Path, component: str) -> Path:
    names = {"hdl": "hdl", "linux": "linux", "u_boot": "u-boot-xlnx", "buildroot": "buildroot"}
    return workspace / "src" / names[component]


def output_dir(workspace: Path, component: str) -> Path:
    names = {"linux": "linux", "u_boot": "u-boot", "buildroot": "buildroot"}
    return workspace / "out" / names[component]


def artifact_paths(workspace: Path, board: dict[str, object]) -> dict[str, Path]:
    build = board["build"]
    assert isinstance(build, dict)
    firmware = build["firmware"]
    assert isinstance(firmware, dict)
    linux_output = output_dir(workspace, "linux")
    buildroot_output = output_dir(workspace, "buildroot")
    hdl_project = str(build["hdl_project"])
    return {
        "kernel": linux_output / "arch" / "arm" / "boot" / str(firmware["kernel_image"]),
        "rootfs": buildroot_output / "images" / str(firmware["rootfs_image"]),
        "dtb_dir": linux_output / "arch" / "arm" / "boot" / "dts",
        "u_boot_elf": output_dir(workspace, "u_boot") / "u-boot",
        "xsa": source_dir(workspace, "hdl") / "projects" / hdl_project / f"{hdl_project}.sdk" / "system_top.xsa",
        "bitstream": source_dir(workspace, "hdl") / "projects" / hdl_project / f"{hdl_project}.runs" / "impl_1" / "system_top.bit",
        "boot_bin": workspace / "out" / "boot" / str(firmware["boot_image"]),
        "mkimage": output_dir(workspace, "u_boot") / "tools" / "mkimage",
        "mkenvimage": output_dir(workspace, "u_boot") / "tools" / "mkenvimage",
    }


def plan_commands(args: argparse.Namespace, board: dict[str, object]) -> list[tuple[str, list[str]]]:
    workspace = external_workspace(args.workspace)
    build = board["build"]
    assert isinstance(build, dict)
    commands: list[tuple[str, list[str]]] = []
    action = "all" if args.action == "plan" else args.action
    selected = tuple(args.components) if action == "prepare" else COMPONENTS
    if action in ("prepare", "all"):
        for component in selected:
            commands.append(
                (
                    f"materialize {component}",
                    [
                        sys.executable,
                        str(PREPARE),
                        "e310",
                        component,
                        "--output",
                        str(source_dir(workspace, component)),
                    ],
                )
            )
        if action == "all" and args.fpga_cache_bundle:
            commands.append(
                (
                    "restore verified FPGA build bundle",
                    [
                        sys.executable,
                        str(FPGA_CACHE),
                        "restore",
                        "--bundle",
                        str(args.fpga_cache_bundle),
                        "--identity",
                        str(args.fpga_cache_identity),
                        "--workspace",
                        str(workspace),
                    ],
                )
            )
    if action in ("rootfs", "all"):
        source = source_dir(workspace, "buildroot")
        output = output_dir(workspace, "buildroot")
        commands.extend(
            [
                ("configure Buildroot", [args.make, "-C", str(source), f"O={output}", str(build["buildroot_defconfig"])]),
                ("build Buildroot rootfs", [args.make, "-C", str(source), f"O={output}", f"-j{args.jobs}"]),
            ]
        )
    if action in ("linux", "all"):
        source = source_dir(workspace, "linux")
        output = output_dir(workspace, "linux")
        common = [args.make, "-C", str(source), f"O={output}", "ARCH=arm", f"CROSS_COMPILE={args.cross_compile}"]
        commands.extend(
            [
                ("configure Linux", [*common, str(build["linux_defconfig"])]),
                ("build Linux kernel and DTBs", [*common, f"-j{args.jobs}", "zImage", "dtbs", "UIMAGE_LOADADDR=0x00008000"]),
            ]
        )
    if action in ("u_boot", "all"):
        source = source_dir(workspace, "u_boot")
        output = output_dir(workspace, "u_boot")
        common = [args.make, "-C", str(source), f"O={output}", "ARCH=arm", f"CROSS_COMPILE={args.cross_compile}"]
        commands.extend(
            [
                ("configure U-Boot", [*common, str(build["u_boot_defconfig"])]),
                (
                    "select U-Boot uEnv mode",
                    [
                        sys.executable,
                        str(SELECT_UENV),
                        "--config",
                        str(output / ".config"),
                        "--mode",
                        args.uenv_mode,
                        *(["--fit-signature-required"] if args.fit_signing_key_dir else []),
                    ],
                ),
                ("refresh U-Boot configuration", [*common, "olddefconfig"]),
                ("build U-Boot and mkimage", [*common, f"-j{args.jobs}"]),
            ]
        )
    if action in ("hdl", "all"):
        if args.fpga_cache_bundle:
            if action == "hdl":
                commands.append(
                    (
                        "restore verified FPGA build bundle",
                        [
                            sys.executable,
                            str(FPGA_CACHE),
                            "restore",
                            "--bundle",
                            str(args.fpga_cache_bundle),
                            "--identity",
                            str(args.fpga_cache_identity),
                            "--workspace",
                            str(workspace),
                        ],
                    )
                )
        else:
            project = source_dir(workspace, "hdl") / "projects" / str(build["hdl_project"])
            commands.append(("build FPGA project", [args.make, "-C", str(project), f"-j{args.jobs}"]))
    if action in ("boot_bin", "all"):
        artifacts = artifact_paths(workspace, board)
        commands.append(
            (
                "create FSBL and BOOT.BIN",
                [args.xsct, str(source_dir(workspace, "hdl") / "projects" / "scripts" / "adi_make_boot_bin.tcl"), str(artifacts["xsa"]), str(artifacts["u_boot_elf"]), str(artifacts["boot_bin"].parent)],
            )
        )
    if action in ("assemble", "all"):
        artifacts = artifact_paths(workspace, board)
        release = args.release or workspace / "release"
        commands.append(
            (
                "assemble SD and QSPI delivery artifacts",
                [
                    sys.executable,
                    str(ASSEMBLE),
                    "--kernel",
                    str(artifacts["kernel"]),
                    "--rootfs",
                    str(artifacts["rootfs"]),
                    "--bitstream",
                    str(artifacts["bitstream"]),
                    "--dtb-dir",
                    str(artifacts["dtb_dir"]),
                    "--boot-bin",
                    str(artifacts["boot_bin"]),
                    "--mkimage",
                    str(artifacts["mkimage"]),
                    "--mkenvimage",
                    str(artifacts["mkenvimage"]),
                    "--output",
                    str(release),
                    *(
                        ["--signing-key-dir", str(args.fit_signing_key_dir)]
                        if args.fit_signing_key_dir
                        else []
                    ),
                ],
            )
        )
    return commands


def require_sources(workspace: Path, components: Iterable[str]) -> None:
    missing = [str(source_dir(workspace, component)) for component in components if not source_dir(workspace, component).is_dir()]
    if missing:
        raise BuildError("workspace is not prepared; missing: " + ", ".join(missing))


def build_environment(workspace: Path) -> dict[str, str]:
    environment = os.environ.copy()
    host_bin = output_dir(workspace, "buildroot") / "host" / "bin"
    if host_bin.is_dir():
        environment["PATH"] = str(host_bin) + os.pathsep + environment.get("PATH", "")
    return environment


def run_commands(commands: list[tuple[str, list[str]]], workspace: Path, action: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    required = {
        "rootfs": ("buildroot",),
        "linux": ("linux",),
        "u_boot": ("u_boot",),
        "hdl": ("hdl",),
        "boot_bin": ("hdl", "u_boot"),
        "assemble": (),
        "all": COMPONENTS,
    }.get(action, ())
    if action != "all":
        require_sources(workspace, required)
    for label, command in commands:
        print(f"==> {label}")
        subprocess.run(command, check=True, cwd=workspace, env=build_environment(workspace))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="action", required=True)
    for name in ("plan", "prepare", "rootfs", "linux", "u_boot", "hdl", "boot_bin", "assemble", "all"):
        command = subparsers.add_parser(name)
        command.add_argument("--workspace", required=True, type=Path)
        command.add_argument("--jobs", type=int, default=1)
        command.add_argument("--make", default="make")
        command.add_argument("--cross-compile", default="arm-linux-gnueabihf-")
        command.add_argument("--uenv-mode", choices=("compat", "locked"), default="compat")
        command.add_argument("--xsct", default="xsct")
        command.add_argument("--release", type=Path)
        command.add_argument("--fit-signing-key-dir", type=Path)
        command.add_argument("--fpga-cache-bundle", type=Path)
        command.add_argument("--fpga-cache-identity", type=Path)
        if name == "prepare":
            command.add_argument("--components", choices=COMPONENTS, nargs="+", default=list(COMPONENTS))
        if name != "plan":
            command.add_argument("--execute", action="store_true", help="run the planned commands")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.jobs < 1:
        print("--jobs must be positive", file=sys.stderr)
        return 2
    try:
        if bool(args.fpga_cache_bundle) != bool(args.fpga_cache_identity):
            raise BuildError("--fpga-cache-bundle and --fpga-cache-identity must be provided together")
        board = load_board()
        workspace = external_workspace(args.workspace)
        commands = plan_commands(args, board)
        for label, command in commands:
            print(f"{label}: {shlex.join(command)}")
        if args.action != "plan" and args.execute:
            run_commands(commands, workspace, args.action)
        elif args.action != "plan":
            print("dry run only; pass --execute to modify the external workspace")
        return 0
    except (
        BoardDataError,
        BuildError,
        ContractError,
        OSError,
        subprocess.CalledProcessError,
        yaml.YAMLError,
    ) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
