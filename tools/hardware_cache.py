#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create and consume content-addressed E310 FPGA and FSBL bundles."""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any

from board_data import BoardDataError, REPOSITORY_ROOT, external_path, load_board
from fpga_cache import (
    FPGA_SOURCE_ROOT,
    HDL_UPSTREAM,
    MATERIALIZER,
    canonical_digest,
    embedded_bitstream,
    git_head,
    sha256_file,
    source_inventory,
    without_provenance,
)


SCHEMA_VERSION = 1
CACHE_NAMESPACE = "antsdr-hardware-e310-v1"
FSBL_GENERATOR = HDL_UPSTREAM / "projects" / "scripts" / "adi_make_boot_bin.tcl"
TOOLCHAIN_INPUT_FILES = (
    REPOSITORY_ROOT / "ci" / "vivado" / "install-vivado.sh",
    REPOSITORY_ROOT / "ci" / "vivado" / "install_config.txt.in",
    REPOSITORY_ROOT / "ci" / "vivado" / "web-installer.env",
)
BUNDLE_FILES = ("system_top.bit", "system_top.xsa", "timing_impl.log", "fsbl.elf")


class HardwareCacheError(RuntimeError):
    pass


def build_identity(
    board: dict[str, Any],
    inventory: dict[str, str],
    actual_hdl_commit: str,
    fsbl_generator_sha256: str,
    toolchain_inputs: dict[str, str],
) -> dict[str, Any]:
    expected_commit = str(board["upstream"]["components"]["hdl"]["commit"])
    if actual_hdl_commit != expected_commit:
        raise HardwareCacheError(
            f"ADI HDL commit mismatch: expected {expected_commit}, got {actual_hdl_commit}"
        )
    hardware = board["hardware"]
    build = board["build"]
    soc = hardware["soc"]
    inputs = {
        "board": str(board["id"]),
        "hdl_commit": expected_commit,
        "fpga_sources": inventory,
        "materializer_sha256": sha256_file(MATERIALIZER),
        "hardware_contract": without_provenance(
            {
                name: hardware[name]
                for name in ("soc", "ddr", "clocks", "gpios", "pl_io", "rf", "datapath")
            }
        ),
        "tools": {
            "vivado": str(board["toolchain"]["vivado"]["version"]),
            "fsbl": str(board["toolchain"]["fsbl"]["version"]),
            "inputs": toolchain_inputs,
        },
        "fsbl_generator_sha256": fsbl_generator_sha256,
        "build": {
            "project": str(build["hdl_project"]),
            "device": str(soc["device"]),
            "package": str(soc["package"]),
            "speed_grade": str(soc["speed_grade"]),
            "mode": "default",
            "ooc_synthesis": True,
            "max_ooc_jobs": 4,
            "incremental_implementation": False,
            "bitstream_compression": True,
        },
    }
    digest = canonical_digest(inputs)
    return {
        "schema_version": SCHEMA_VERSION,
        "cache_namespace": CACHE_NAMESPACE,
        "cache_key": f"{CACHE_NAMESPACE}-{digest}",
        "input_sha256": digest,
        "inputs": inputs,
    }


def resolve_identity() -> dict[str, Any]:
    if not FSBL_GENERATOR.is_file():
        raise HardwareCacheError(f"FSBL generator is missing: {FSBL_GENERATOR}")
    return build_identity(
        load_board("e310"),
        source_inventory(FPGA_SOURCE_ROOT),
        git_head(HDL_UPSTREAM),
        sha256_file(FSBL_GENERATOR),
        {
            path.relative_to(REPOSITORY_ROOT).as_posix(): sha256_file(path)
            for path in TOOLCHAIN_INPUT_FILES
        },
    )


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HardwareCacheError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise HardwareCacheError(f"{label} must contain a JSON object")
    return value


def load_identity(path: Path) -> dict[str, Any]:
    value = load_json(path, "hardware cache identity")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise HardwareCacheError("unsupported hardware cache identity schema")
    if value.get("cache_namespace") != CACHE_NAMESPACE:
        raise HardwareCacheError("unsupported hardware cache namespace")
    if value.get("cache_key") != f"{CACHE_NAMESPACE}-{value.get('input_sha256', '')}":
        raise HardwareCacheError("hardware cache identity key does not match its input digest")
    if value.get("input_sha256") != canonical_digest(value.get("inputs")):
        raise HardwareCacheError("hardware cache identity digest is invalid")
    return value


def artifact_paths(workspace: Path) -> dict[str, Path]:
    project = workspace / "src" / "hdl" / "projects" / "e310"
    return {
        "system_top.bit": project / "e310.runs" / "impl_1" / "system_top.bit",
        "system_top.xsa": project / "e310.sdk" / "system_top.xsa",
        "timing_impl.log": project / "timing_impl.log",
        "fsbl.elf": workspace / "out" / "boot" / "fsbl.elf",
    }


def validate_zynq_fsbl(path: Path) -> None:
    header = path.read_bytes()[:20]
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise HardwareCacheError("FSBL is not an ELF executable")
    if header[4:7] != b"\x01\x01\x01":
        raise HardwareCacheError("FSBL must be a 32-bit little-endian ELF executable")
    if struct.unpack_from("<H", header, 18)[0] != 40:
        raise HardwareCacheError("FSBL ELF target is not ARM")


def validate_bundle(bundle: Path, identity: dict[str, Any]) -> dict[str, Any]:
    bundle = bundle.expanduser().resolve()
    manifest = load_json(bundle / "manifest.json", "hardware cache manifest")
    if set(manifest) != {"schema_version", "identity", "timing_status", "files"}:
        raise HardwareCacheError("hardware cache manifest fields are invalid")
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["identity"] != identity:
        raise HardwareCacheError("hardware cache manifest identity mismatch")
    if manifest["timing_status"] != "passed":
        raise HardwareCacheError("hardware cache does not record successful timing closure")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != set(BUNDLE_FILES):
        raise HardwareCacheError("hardware cache file inventory is invalid")
    for name in BUNDLE_FILES:
        path = bundle / name
        record = files[name]
        if not path.is_file() or not isinstance(record, dict):
            raise HardwareCacheError(f"hardware cache file is missing: {name}")
        if record.get("size_bytes") != path.stat().st_size:
            raise HardwareCacheError(f"hardware cache file size is invalid: {name}")
        if record.get("sha256") != sha256_file(path):
            raise HardwareCacheError(f"hardware cache file digest is invalid: {name}")
    if embedded_bitstream(bundle / "system_top.xsa") != (bundle / "system_top.bit").read_bytes():
        raise HardwareCacheError("XSA embedded bitstream differs from system_top.bit")
    validate_zynq_fsbl(bundle / "fsbl.elf")
    return manifest


def pack_bundle(workspace: Path, bundle: Path, identity: dict[str, Any]) -> None:
    workspace = external_path(workspace, "--workspace")
    bundle = external_path(bundle, "--bundle")
    artifacts = artifact_paths(workspace)
    for source in artifacts.values():
        if not source.is_file() or source.stat().st_size == 0:
            raise HardwareCacheError(f"hardware build artifact is missing: {source}")
    if embedded_bitstream(artifacts["system_top.xsa"]) != artifacts["system_top.bit"].read_bytes():
        raise HardwareCacheError("built XSA and bitstream do not match")
    validate_zynq_fsbl(artifacts["fsbl.elf"])

    bundle.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{bundle.name}-", dir=bundle.parent))
    try:
        for name, source in artifacts.items():
            shutil.copy2(source, temporary / name)
        files = {
            name: {
                "sha256": sha256_file(temporary / name),
                "size_bytes": (temporary / name).stat().st_size,
            }
            for name in BUNDLE_FILES
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "identity": identity,
            "timing_status": "passed",
            "files": files,
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        validate_bundle(temporary, identity)
        if bundle.exists():
            shutil.rmtree(bundle)
        temporary.replace(bundle)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def restore_bundle(bundle: Path, workspace: Path, identity: dict[str, Any]) -> None:
    validate_bundle(bundle, identity)
    workspace = external_path(workspace, "--workspace")
    for name, destination in artifact_paths(workspace).items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle / name, destination)


def annotate_metadata(metadata: Path, identity: dict[str, Any]) -> None:
    value = load_json(metadata, "build metadata")
    value["hardware_build"] = {
        "cache_key": identity["cache_key"],
        "input_sha256": identity["input_sha256"],
        "vivado_version": identity["inputs"]["tools"]["vivado"],
        "fsbl_version": identity["inputs"]["tools"]["fsbl"],
    }
    metadata.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    identity_parser = subparsers.add_parser("identity")
    identity_parser.add_argument("--output", required=True, type=Path)
    identity_parser.add_argument("--github-output", type=Path)
    for name in ("validate", "restore", "pack"):
        command = subparsers.add_parser(name)
        command.add_argument("--bundle", required=True, type=Path)
        command.add_argument("--identity", required=True, type=Path)
        if name in {"restore", "pack"}:
            command.add_argument("--workspace", required=True, type=Path)
    annotate = subparsers.add_parser("annotate")
    annotate.add_argument("--metadata", required=True, type=Path)
    annotate.add_argument("--identity", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.action == "identity":
            value = resolve_identity()
            write_json(args.output, value)
            if args.github_output:
                with args.github_output.open("a", encoding="utf-8") as stream:
                    stream.write(f"key={value['cache_key']}\n")
                    stream.write(f"input-sha256={value['input_sha256']}\n")
            print(value["cache_key"])
        else:
            identity = load_identity(args.identity)
            if args.action == "validate":
                validate_bundle(args.bundle, identity)
                print(f"validated hardware cache bundle {identity['cache_key']}")
            elif args.action == "restore":
                restore_bundle(args.bundle, args.workspace, identity)
                print(f"restored hardware cache bundle {identity['cache_key']}")
            elif args.action == "pack":
                pack_bundle(args.workspace, args.bundle, identity)
                print(f"packed hardware cache bundle {identity['cache_key']}")
            else:
                annotate_metadata(args.metadata, identity)
                print(f"annotated build metadata with {identity['cache_key']}")
        return 0
    except (BoardDataError, HardwareCacheError, OSError, KeyError, TypeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
