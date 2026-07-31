#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify an assembled ANTSDR OS release without programming hardware."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from board_data import BoardDataError, load_board, load_profiles


class ReleaseVerificationError(RuntimeError):
    pass


GENERATED_FILES = {"SHA256SUMS", "SHA256SUMS.sig", "sbom.spdx.json", "build-metadata.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if candidate.parent == root or root in candidate.parents:
        return candidate
    raise ReleaseVerificationError(f"path escapes release root: {relative}")


def require_file(root: Path, relative: str) -> Path:
    path = safe_file(root, relative)
    if not path.is_file():
        raise ReleaseVerificationError(f"release file is missing: {relative}")
    return path


def verify(release: Path, board_id: str) -> dict[str, Any]:
    release = release.expanduser().resolve()
    if not release.is_dir():
        raise ReleaseVerificationError(f"release directory is missing: {release}")
    manifest_path = require_file(release, "manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseVerificationError(f"cannot read manifest: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ReleaseVerificationError("manifest schema_version must be 1")
    if manifest.get("board") != board_id:
        raise ReleaseVerificationError(f"manifest board is not {board_id}")

    board = load_board(board_id)
    profiles = load_profiles(board_id)
    expected_profiles = {profile["id"] for profile in profiles}
    actual_profiles = {item.get("id") for item in manifest.get("profiles", []) if isinstance(item, dict)}
    if actual_profiles != expected_profiles:
        raise ReleaseVerificationError(
            f"profile set mismatch: expected {sorted(expected_profiles)}, got {sorted(actual_profiles)}"
        )

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ReleaseVerificationError("manifest files inventory is empty")
    listed = set(files)
    for relative, record in files.items():
        if not isinstance(relative, str) or not isinstance(record, dict):
            raise ReleaseVerificationError("manifest files entries must be mappings")
        path = require_file(release, relative)
        if record.get("sha256") != sha256(path):
            raise ReleaseVerificationError(f"SHA-256 mismatch: {relative}")
        if record.get("size_bytes") != path.stat().st_size:
            raise ReleaseVerificationError(f"size mismatch: {relative}")

    actual = {
        path.relative_to(release).as_posix()
        for path in release.rglob("*")
        if path.is_file() and path.name not in GENERATED_FILES and path.name != "manifest.json"
    }
    if actual != listed:
        missing = sorted(listed - actual)
        extra = sorted(actual - listed)
        raise ReleaseVerificationError(f"manifest inventory mismatch; missing={missing}, extra={extra}")

    firmware = board["build"]["firmware"]
    fit_name = str(firmware["fit_image"])
    qspi = manifest.get("qspi")
    if not isinstance(qspi, dict):
        raise ReleaseVerificationError("manifest lacks QSPI contract")
    fit_path = require_file(release, str(qspi["artifact"]))
    if fit_path.name != fit_name or fit_path.stat().st_size > int(qspi["max_size_bytes"]):
        raise ReleaseVerificationError("QSPI FIT artifact is missing or exceeds its partition")
    boot_size = int(qspi["boot_size_bytes"])
    env_size = int(qspi["profile_environment_size_bytes"])
    for item in manifest["profiles"]:
        if not isinstance(item, dict):
            raise ReleaseVerificationError("profile manifest entry must be a mapping")
        profile_id = str(item["id"])
        boot = require_file(release, f"common/{firmware['boot_image']}")
        if boot.stat().st_size == 0:
            raise ReleaseVerificationError(f"empty SD BOOT.BIN for {profile_id}")
        qspi_boot = require_file(release, str(item["qspi_boot_payload"]))
        if qspi_boot.stat().st_size != boot_size:
            raise ReleaseVerificationError(f"QSPI boot payload size mismatch for {profile_id}")
        environment = require_file(release, str(item["qspi_environment"]))
        if environment.stat().st_size != env_size:
            raise ReleaseVerificationError(f"QSPI environment size mismatch for {profile_id}")
        require_file(release, str(item["qspi_firmware_payload"]))
        require_file(release, str(item["qspi_extra_environment_payload"]))
        profile_dir = str(item["profile_directory"])
        require_file(release, f"{profile_dir}/uEnv.txt")
        require_file(release, f"{profile_dir}/firmware-update.conf")

    metadata = release / "build-metadata.json"
    if metadata.is_file():
        try:
            build_metadata = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReleaseVerificationError(f"invalid build-metadata.json: {error}") from error
        if build_metadata.get("board") != board_id or build_metadata.get("os_name") != "ANTSDR OS":
            raise ReleaseVerificationError("build metadata does not identify ANTSDR OS E310")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--board", default="e310")
    args = parser.parse_args()
    try:
        manifest = verify(args.release, args.board)
        print(f"verified {manifest['board']} release with {len(manifest['files'])} inventoried files")
        return 0
    except (BoardDataError, ReleaseVerificationError, OSError, KeyError, TypeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
