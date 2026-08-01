#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create and consume content-addressed E310 FPGA build bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from board_data import BoardDataError, REPOSITORY_ROOT, external_path, load_board


SCHEMA_VERSION = 1
CACHE_NAMESPACE = "antsdr-fpga-e310-v1"
FPGA_SOURCE_ROOT = REPOSITORY_ROOT / "boards" / "e310" / "hw" / "fpga"
FPGA_PATCH_ROOT = REPOSITORY_ROOT / "boards" / "e310" / "patches" / "hdl"
HDL_UPSTREAM = REPOSITORY_ROOT / "upstream" / "adi-plutosdr-fw" / "hdl"
MATERIALIZER = REPOSITORY_ROOT / "tools" / "prepare_component.py"
IGNORED_SOURCE_FILES = {"THIRD_PARTY.md"}
BUNDLE_FILES = ("system_top.bit", "system_top.xsa", "timing_impl.log")


class FpgaCacheError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def without_provenance(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: without_provenance(child)
            for key, child in value.items()
            if key != "sources"
        }
    if isinstance(value, list):
        return [without_provenance(child) for child in value]
    return value


def source_inventory(root: Path = FPGA_SOURCE_ROOT) -> dict[str, str]:
    if not root.is_dir():
        raise FpgaCacheError(f"FPGA source root is missing: {root}")
    inventory = {
        f"hw/fpga/{path.relative_to(root).as_posix()}": sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in IGNORED_SOURCE_FILES
    }
    if FPGA_PATCH_ROOT.is_dir():
        inventory.update(
            {
                f"patches/hdl/{path.relative_to(FPGA_PATCH_ROOT).as_posix()}": sha256_file(path)
                for path in sorted(FPGA_PATCH_ROOT.rglob("*"))
                if path.is_file()
            }
        )
    if not inventory:
        raise FpgaCacheError("FPGA source inventory is empty")
    return inventory


def git_head(repository: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if result.returncode or len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise FpgaCacheError(f"cannot resolve Git commit for {repository}")
    return value


def vivado_version(executable: str) -> list[str]:
    result = subprocess.run([executable, "-version"], check=False, capture_output=True, text=True)
    if result.returncode:
        raise FpgaCacheError(f"Vivado version query failed with status {result.returncode}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise FpgaCacheError("Vivado version output is empty")
    return lines


def build_identity(
    board: dict[str, Any],
    version_lines: list[str],
    inventory: dict[str, str],
    actual_hdl_commit: str,
) -> dict[str, Any]:
    expected_commit = str(board["upstream"]["components"]["hdl"]["commit"])
    if actual_hdl_commit != expected_commit:
        raise FpgaCacheError(
            f"ADI HDL commit mismatch: expected {expected_commit}, got {actual_hdl_commit}"
        )
    soc = board["hardware"]["soc"]
    hardware = board["hardware"]
    build = board["build"]
    tool = board["toolchain"]["vivado"]
    declared_version = str(tool["version"])
    if not any(declared_version in line for line in version_lines):
        raise FpgaCacheError(
            f"Vivado version output does not contain declared version {declared_version}"
        )
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
        "vivado": {
            "declared_version": declared_version,
            "version_output": version_lines,
        },
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


def resolve_identity(vivado: str) -> dict[str, Any]:
    board = load_board("e310")
    return build_identity(
        board,
        vivado_version(vivado),
        source_inventory(),
        git_head(HDL_UPSTREAM),
    )


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FpgaCacheError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise FpgaCacheError(f"{label} must contain a JSON object")
    return value


def load_identity(path: Path) -> dict[str, Any]:
    value = load_json(path, "FPGA cache identity")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("cache_namespace") != CACHE_NAMESPACE:
        raise FpgaCacheError("unsupported FPGA cache identity")
    if value.get("cache_key") != f"{CACHE_NAMESPACE}-{value.get('input_sha256', '')}":
        raise FpgaCacheError("FPGA cache identity key does not match its input digest")
    if value.get("input_sha256") != canonical_digest(value.get("inputs")):
        raise FpgaCacheError("FPGA cache identity digest is invalid")
    return value


def embedded_bitstream(xsa: Path) -> bytes:
    try:
        with zipfile.ZipFile(xsa) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise FpgaCacheError(f"XSA contains a corrupt member: {bad}")
            names = [name for name in archive.namelist() if Path(name).name == "system_top.bit"]
            if len(names) != 1:
                raise FpgaCacheError("XSA must contain exactly one system_top.bit")
            return archive.read(names[0])
    except zipfile.BadZipFile as error:
        raise FpgaCacheError(f"invalid XSA archive: {error}") from error


def validate_bundle(bundle: Path, identity: dict[str, Any]) -> dict[str, Any]:
    bundle = bundle.expanduser().resolve()
    manifest = load_json(bundle / "manifest.json", "FPGA cache manifest")
    if set(manifest) != {"schema_version", "identity", "timing_status", "files"}:
        raise FpgaCacheError("FPGA cache manifest fields are invalid")
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["identity"] != identity:
        raise FpgaCacheError("FPGA cache manifest identity mismatch")
    if manifest["timing_status"] != "passed":
        raise FpgaCacheError("FPGA cache does not record successful timing closure")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != set(BUNDLE_FILES):
        raise FpgaCacheError("FPGA cache file inventory is invalid")
    for name in BUNDLE_FILES:
        path = bundle / name
        record = files[name]
        if not path.is_file() or not isinstance(record, dict):
            raise FpgaCacheError(f"FPGA cache file is missing: {name}")
        if record.get("size_bytes") != path.stat().st_size or record.get("sha256") != sha256_file(path):
            raise FpgaCacheError(f"FPGA cache file verification failed: {name}")
    bitstream = (bundle / "system_top.bit").read_bytes()
    if embedded_bitstream(bundle / "system_top.xsa") != bitstream:
        raise FpgaCacheError("XSA embedded bitstream differs from system_top.bit")
    return manifest


def artifact_paths(workspace: Path) -> dict[str, Path]:
    project = workspace / "src" / "hdl" / "projects" / "e310"
    return {
        "system_top.bit": project / "e310.runs" / "impl_1" / "system_top.bit",
        "system_top.xsa": project / "e310.sdk" / "system_top.xsa",
        "timing_impl.log": project / "timing_impl.log",
    }


def pack_bundle(workspace: Path, bundle: Path, identity: dict[str, Any]) -> None:
    workspace = external_path(workspace, "--workspace")
    bundle = external_path(bundle, "--bundle")
    artifacts = artifact_paths(workspace)
    for name, source in artifacts.items():
        if not source.is_file() or source.stat().st_size == 0:
            raise FpgaCacheError(f"FPGA build artifact is missing: {source}")
    if embedded_bitstream(artifacts["system_top.xsa"]) != artifacts["system_top.bit"].read_bytes():
        raise FpgaCacheError("built XSA and bitstream do not match")

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
    value["fpga"] = {
        "cache_key": identity["cache_key"],
        "input_sha256": identity["input_sha256"],
        "vivado_version": identity["inputs"]["vivado"]["version_output"],
    }
    metadata.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    identity_parser = subparsers.add_parser("identity")
    identity_parser.add_argument("--vivado", default="vivado")
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
            value = resolve_identity(args.vivado)
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
                print(f"validated FPGA cache bundle {identity['cache_key']}")
            elif args.action == "restore":
                restore_bundle(args.bundle, args.workspace, identity)
                print(f"restored FPGA cache bundle {identity['cache_key']}")
            elif args.action == "pack":
                pack_bundle(args.workspace, args.bundle, identity)
                print(f"packed FPGA cache bundle {identity['cache_key']}")
            else:
                annotate_metadata(args.metadata, identity)
                print(f"annotated build metadata with {identity['cache_key']}")
        return 0
    except (BoardDataError, FpgaCacheError, OSError, KeyError, TypeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
