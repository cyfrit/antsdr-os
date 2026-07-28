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


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "tools" / "prepare_component.py"
COMPONENTS = ("hdl", "linux", "u_boot", "buildroot")


class BuildError(RuntimeError):
    pass


def load_board() -> dict[str, object]:
    with (ROOT / "boards" / "e310" / "board.yaml").open(encoding="utf-8") as stream:
        board = yaml.safe_load(stream)
    if not isinstance(board, dict) or board.get("id") != "e310":
        raise BuildError("invalid E310 board contract")
    return board


def external_workspace(path: Path) -> Path:
    workspace = path.expanduser().resolve()
    if workspace == ROOT or workspace.is_relative_to(ROOT):
        raise BuildError("--workspace must be outside this repository")
    return workspace


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
                ("build U-Boot and mkimage", [*common, f"-j{args.jobs}"]),
            ]
        )
    if action in ("hdl", "all"):
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
    return commands


def require_sources(workspace: Path, components: Iterable[str]) -> None:
    missing = [str(source_dir(workspace, component)) for component in components if not source_dir(workspace, component).is_dir()]
    if missing:
        raise BuildError("workspace is not prepared; missing: " + ", ".join(missing))


def run_commands(commands: list[tuple[str, list[str]]], workspace: Path, action: str) -> None:
    required = {
        "rootfs": ("buildroot",),
        "linux": ("linux",),
        "u_boot": ("u_boot",),
        "hdl": ("hdl",),
        "boot_bin": ("hdl", "u_boot"),
        "all": COMPONENTS,
    }.get(action, ())
    if action != "all":
        require_sources(workspace, required)
    for label, command in commands:
        print(f"==> {label}")
        subprocess.run(command, check=True, cwd=workspace, env=os.environ.copy())


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="action", required=True)
    for name in ("plan", "prepare", "rootfs", "linux", "u_boot", "hdl", "boot_bin", "all"):
        command = subparsers.add_parser(name)
        command.add_argument("--workspace", required=True, type=Path)
        command.add_argument("--jobs", type=int, default=1)
        command.add_argument("--make", default="make")
        command.add_argument("--cross-compile", default="arm-linux-gnueabihf-")
        command.add_argument("--xsct", default="xsct")
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
    except (BuildError, OSError, subprocess.CalledProcessError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
