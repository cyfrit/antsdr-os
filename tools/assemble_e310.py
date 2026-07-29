#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assemble validated E310 firmware artifacts without programming hardware."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import yaml

from board_data import (
    BoardDataError,
    REPOSITORY_ROOT,
    external_path,
    load_board as load_board_data,
    load_profiles,
)
from generate_fit import render_its
from validate_boards import ContractError


ROOT = REPOSITORY_ROOT
MkimageRunner = Callable[[list[str], Path], None]


class AssemblyError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssemblyInputs:
    kernel: Path
    rootfs: Path
    bitstream: Path
    dtb_dir: Path
    boot_bin: Path
    output: Path
    mkimage: Path


def load_board() -> tuple[dict[str, object], list[dict[str, object]]]:
    return load_board_data("e310"), load_profiles("e310")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise AssemblyError(f"missing {label}: {resolved}")
    return resolved


def qspi_partition(board: dict[str, object]) -> dict[str, object]:
    build = board["build"]
    hardware = board["hardware"]
    assert isinstance(build, dict) and isinstance(hardware, dict)
    firmware = build["firmware"]
    boot = hardware["boot"]
    assert isinstance(firmware, dict) and isinstance(boot, dict)
    qspi = boot["qspi"]
    assert isinstance(qspi, dict)
    for partition in qspi["partitions"]:
        if partition["name"] == firmware["qspi_partition"]:
            return partition
    raise AssemblyError("firmware QSPI partition is absent from board contract")


def default_runner(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def copy_required(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def manifest_files(root: Path) -> dict[str, dict[str, int | str]]:
    entries: dict[str, dict[str, int | str]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "manifest.json":
            continue
        entries[path.relative_to(root).as_posix()] = {
            "sha256": sha256(path),
            "size_bytes": path.stat().st_size,
        }
    return entries


def ensure_external_output(output: Path) -> Path:
    try:
        resolved = external_path(output, "--output")
    except BoardDataError as error:
        raise AssemblyError(str(error)) from error
    if resolved.exists():
        raise AssemblyError(f"output already exists: {resolved}")
    return resolved


def build_release(inputs: AssemblyInputs, runner: MkimageRunner = default_runner) -> Path:
    board, profiles = load_board()
    build = board["build"]
    assert isinstance(build, dict)
    firmware = build["firmware"]
    assert isinstance(firmware, dict)

    kernel = require_file(inputs.kernel, "kernel")
    rootfs = require_file(inputs.rootfs, "root filesystem")
    bitstream = require_file(inputs.bitstream, "FPGA bitstream")
    boot_bin = require_file(inputs.boot_bin, "BOOT.BIN")
    mkimage = require_file(inputs.mkimage, "mkimage")
    dtb_dir = inputs.dtb_dir.expanduser().resolve()
    if not dtb_dir.is_dir():
        raise AssemblyError(f"missing DTB directory: {dtb_dir}")

    output = ensure_external_output(inputs.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        fit_input = staging / "fit-input"
        fit_input.mkdir()
        copy_required(kernel, fit_input / str(firmware["kernel_image"]))
        copy_required(rootfs, fit_input / str(firmware["rootfs_image"]))

        bitstream_names = {profile["artifacts"]["fpga_bitstream"] for profile in profiles}
        if len(bitstream_names) != 1:
            raise AssemblyError("profiles do not agree on a universal FPGA bitstream")
        bitstream_name = next(iter(bitstream_names))
        copy_required(bitstream, fit_input / bitstream_name)

        for profile in profiles:
            dtb_name = profile["artifacts"]["linux_dtb"]
            copy_required(dtb_dir / dtb_name, fit_input / dtb_name)

        its_name = Path(str(firmware["fit_image"])).with_suffix(".its").name
        its = fit_input / its_name
        its.write_text(render_its(board, profiles), encoding="utf-8")
        fit = staging / str(firmware["fit_image"])
        runner([str(mkimage), "-f", its.name, str(fit)], fit_input)
        require_file(fit, "generated FIT image")

        partition = qspi_partition(board)
        if fit.stat().st_size > partition["size"]:
            raise AssemblyError(
                f"FIT image exceeds {partition['name']} capacity: "
                f"{fit.stat().st_size} > {partition['size']}"
            )

        qspi_dir = staging / "qspi"
        qspi_dir.mkdir()
        shutil.copy2(fit, qspi_dir / str(firmware["fit_image"]))

        profile_manifest: list[dict[str, object]] = []
        for profile in profiles:
            profile_dir = staging / "sd" / profile["id"]
            profile_dir.mkdir(parents=True)
            shutil.copy2(boot_bin, profile_dir / str(firmware["boot_image"]))
            shutil.copy2(fit, profile_dir / str(firmware["fit_image"]))
            selection = profile["selection"]
            (profile_dir / "uEnv.txt").write_text(
                f"rf_model={selection['rf_model']}\nrf_topology={selection['rf_topology']}\n",
                encoding="ascii",
            )
            profile_manifest.append(
                {
                    "id": profile["id"],
                    "selection": selection,
                    "sd_directory": profile_dir.relative_to(staging).as_posix(),
                    "fit_configuration": profile["artifacts"]["fit_configuration"],
                }
            )

        shutil.rmtree(fit_input)
        manifest = {
            "schema_version": 1,
            "board": board["id"],
            "fit": {
                "filename": firmware["fit_image"],
                "signed": False,
                "hash": "sha256",
            },
            "qspi": {
                "partition": partition["name"],
                "offset": partition["offset"],
                "max_size_bytes": partition["size"],
                "artifact": (qspi_dir / str(firmware["fit_image"])).relative_to(staging).as_posix(),
            },
            "profiles": profile_manifest,
            "files": manifest_files(staging),
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.replace(output)
        return output
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--kernel", required=True, type=Path)
    result.add_argument("--rootfs", required=True, type=Path)
    result.add_argument("--bitstream", required=True, type=Path)
    result.add_argument("--dtb-dir", required=True, type=Path)
    result.add_argument("--boot-bin", required=True, type=Path)
    result.add_argument("--mkimage", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        output = build_release(
            AssemblyInputs(
                kernel=args.kernel,
                rootfs=args.rootfs,
                bitstream=args.bitstream,
                dtb_dir=args.dtb_dir,
                boot_bin=args.boot_bin,
                output=args.output,
                mkimage=args.mkimage,
            )
        )
        print(output)
        return 0
    except (
        AssemblyError,
        BoardDataError,
        ContractError,
        OSError,
        subprocess.CalledProcessError,
        yaml.YAMLError,
    ) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
