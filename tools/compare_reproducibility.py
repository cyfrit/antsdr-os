#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare two ANTSDR OS release directories for reproducibility."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): digest(path)
        for path in root.rglob("*")
        if path.is_file()
    }


def tool_generated(path: str) -> bool:
    name = Path(path).name
    return name == "BOOT.BIN" or Path(path).suffix.lower() in {".bit", ".xsa"}


def compare(first: Path, second: Path) -> int:
    left = inventory(first.resolve())
    right = inventory(second.resolve())
    changed = sorted(
        path for path in set(left) | set(right) if left.get(path) != right.get(path)
    )
    if not changed:
        print("reproducibility check passed: all release files match")
        return 0
    tool_differences = [path for path in changed if tool_generated(path)]
    content_differences = [path for path in changed if path not in tool_differences]
    for path in tool_differences:
        print(f"WARNING tool-generated nondeterminism: {path}")
    for path in content_differences:
        print(f"ERROR reproducibility mismatch: {path}", file=sys.stderr)
    if content_differences:
        return 1
    print("reproducibility check passed with tool-generated differences reported")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", required=True, type=Path)
    parser.add_argument("--second", required=True, type=Path)
    args = parser.parse_args()
    try:
        return compare(args.first, args.second)
    except OSError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
