#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write stable SHA256SUMS for every final release file."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        files = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        ]
        lines = [f"{checksum(path)}  {path.relative_to(root).as_posix()}" for path in sorted(files)]
        (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
        print(root / "SHA256SUMS")
        return 0
    except OSError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
