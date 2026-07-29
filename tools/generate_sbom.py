#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate a deterministic SPDX file inventory for a release directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def created_time(metadata: dict[str, object]) -> str:
    epoch = int(str(metadata.get("source_date_epoch", "0")))
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def generate(release: Path) -> dict[str, object]:
    metadata_path = release / "build-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    board = str(metadata.get("board", "unknown"))
    version = str(metadata.get("os_version", "unknown"))
    namespace_seed = hashlib.sha256(f"ANTSDR OS:{board}:{version}".encode("utf-8")).hexdigest()
    files = []
    for path in sorted(item for item in release.rglob("*") if item.is_file() and item.name != "SHA256SUMS"):
        relative = path.relative_to(release).as_posix()
        file_id = "SPDXRef-File-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
        files.append(
            {
                "SPDXID": file_id,
                "fileName": relative,
                "checksums": [{"algorithm": "SHA256", "checksumValue": sha256(path)}],
                "licenseConcluded": "NOASSERTION",
                "licenseInfoInFiles": ["NOASSERTION"],
                "copyrightText": "NOASSERTION",
            }
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"ANTSDR OS {board} {version} release inventory",
        "documentNamespace": f"https://github.com/cyfrit/antsdr-os/releases/{namespace_seed}",
        "creationInfo": {
            "created": created_time(metadata),
            "creators": ["Tool: ANTSDR OS release tooling"],
        },
        "comment": "File-level release inventory. Source dependency coordinates are recorded in build-metadata.json.",
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = generate(args.release.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(args.output)
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
