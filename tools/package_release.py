#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create deterministic, profile-specific ANTSDR OS release archives."""

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
    if manifest.get("board") != "e310" or metadata.get("os_version") != "1.0":
        raise PackageError("release metadata is not ANTSDR OS 1.0 for E310")
    if manifest.get("fit", {}).get("signed") is not True:
        raise PackageError("refusing to package an unsigned FIT release")

    output.mkdir(parents=True, exist_ok=True)
    epoch = int(metadata["source_date_epoch"])
    common = release / "common"
    archives: list[Path] = []
    for profile in manifest["profiles"]:
        profile_id = profile["id"]
        profile_dir = release / profile["profile_directory"]
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            for name in ("BOOT.BIN", "antsdr-e310.itb"):
                shutil.copy2(require_file(common / name), staging / name)
            for name in ("uEnv.txt", "qspi-boot.bin", "qspi-extra-env.bin", "firmware-update.conf"):
                shutil.copy2(require_file(profile_dir / name), staging / name)
            inventory = {
                path.name: {"sha256": sha256(path), "size_bytes": path.stat().st_size}
                for path in sorted(staging.iterdir())
            }
            package_manifest = {
                "schema_version": 1,
                "product": "ANTSDR OS",
                "version": metadata["os_version"],
                "board": "e310",
                "hardware_revision": metadata["hardware_revision"],
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
            name = (
                f"antsdr-e310-revc-os-{metadata['os_version']}-adi-{metadata['adi_baseline']}-"
                f"{profile_id}.zip"
            )
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
    except (OSError, ValueError, KeyError, json.JSONDecodeError, PackageError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
