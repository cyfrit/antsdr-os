#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create deterministic, profile-specific AntSDR OS release archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from board_data import BoardDataError, load_board
from release_metadata import ReleaseMetadataError, load_metadata


class PackageError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise PackageError(f"missing release input: {path}")
    return path


def write_zip(source: Path, destination: Path, epoch: int) -> None:
    timestamp = max(epoch, 315532800)  # ZIP timestamps start at 1980-01-01.
    date_time = datetime.fromtimestamp(timestamp, timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in source.iterdir() if item.is_file()):
            info = zipfile.ZipInfo(path.name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)


def package(release: Path, output: Path) -> list[Path]:
    release = release.resolve()
    output = output.resolve()
    manifest = json.loads(require_file(release / "manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads(require_file(release / "build-metadata.json").read_text(encoding="utf-8"))
    release_metadata = load_metadata()
    product_name = str(release_metadata["product"]["name"])
    expected_version = str(release_metadata["product"]["version"])
    board_id = manifest.get("board")
    if not isinstance(board_id, str) or metadata.get("board") != board_id:
        raise PackageError("release manifest and build metadata disagree on the hardware board")
    board_entry = next(
        (entry for entry in release_metadata["supported_boards"] if entry["id"] == board_id),
        None,
    )
    if board_entry is None:
        raise PackageError(f"release board is not supported: {board_id}")
    if metadata.get("hardware_target") != board_entry["artifact_id"]:
        raise PackageError("build metadata does not identify the expected hardware target")
    if metadata.get("os_name") != product_name:
        raise PackageError("build metadata does not identify the expected OS product")
    if metadata.get("os_version") != expected_version:
        raise PackageError(
            f"release version {metadata.get('os_version')} does not match {expected_version}"
        )
    expected_tag = release_metadata["artifacts"]["tag_template"].format(
        product=release_metadata["product"]["slug"],
        version=expected_version,
    )
    if metadata.get("release_tag") != expected_tag:
        raise PackageError("build metadata does not identify the OS release tag")
    if manifest.get("fit", {}).get("signed") is not True:
        raise PackageError("refusing to package an unsigned FIT release")

    board = load_board(board_id)
    firmware = board["build"]["firmware"]
    output.mkdir(parents=True, exist_ok=True)
    epoch = int(metadata["source_date_epoch"])
    common = release / "common"
    archives: list[Path] = []
    for profile in manifest["profiles"]:
        profile_id = profile["id"]
        profile_dir = release / profile["profile_directory"]
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            for name in (firmware["boot_image"], firmware["fit_image"]):
                shutil.copy2(require_file(common / name), staging / name)
            for name in ("uEnv.txt", "qspi-boot.bin", "qspi-extra-env.bin", "firmware-update.conf"):
                shutil.copy2(require_file(profile_dir / name), staging / name)
            inventory = {
                path.name: {"sha256": sha256(path), "size_bytes": path.stat().st_size}
                for path in sorted(staging.iterdir())
            }
            package_manifest = {
                "schema_version": 1,
                "product": product_name,
                "version": metadata["os_version"],
                "board": board_id,
                "hardware_revision": metadata["hardware_revision"],
                "hardware_target": metadata["hardware_target"],
                "adi_baseline": metadata["adi_baseline"],
                "profile": profile_id,
                "fit_configuration": profile["fit_configuration"],
                "fit_signed": True,
                "files": inventory,
            }
            (staging / "manifest.json").write_text(
                json.dumps(package_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            name = f"{metadata['artifact_stem']}-{profile_id}.zip"
            archive = output / name
            write_zip(staging, archive, epoch)
            archives.append(archive)
    return archives


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        for archive in package(args.release, args.output):
            print(archive)
        return 0
    except (
        BoardDataError,
        ReleaseMetadataError,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        PackageError,
    ) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
