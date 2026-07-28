#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Materialize a board component in a clean worktree without touching upstream."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    "hdl": ("fpga", "hdl"),
    "linux": ("linux", "linux"),
}


class PrepareError(RuntimeError):
    pass


def run(command: list[str], cwd: Path, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=capture,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() if capture else ""
        raise PrepareError(f"command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result.stdout.strip() if capture else ""


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise PrepareError(f"{path}: expected a YAML mapping")
    return data


def safe_relative(value: str, label: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise PrepareError(f"unsafe {label} path: {value}")
    return Path(*posix.parts)


def load_overlay(board_id: str, component: str) -> tuple[dict[str, Any], Path, Path, str]:
    hardware_name, upstream_name = COMPONENTS[component]
    board_dir = ROOT / "boards" / board_id
    board = load_yaml(board_dir / "board.yaml")
    if board.get("id") != board_id:
        raise PrepareError(f"board id mismatch in {board_dir / 'board.yaml'}")

    overlay_path = board_dir / "hw" / hardware_name / "overlay.yaml"
    overlay = load_yaml(overlay_path)
    if overlay.get("schema_version") != 1 or overlay.get("component") != component:
        raise PrepareError(f"invalid component overlay: {overlay_path}")

    upstream = ROOT / "upstream" / "adi-plutosdr-fw" / upstream_name
    expected_commit = board["upstream"]["components"][component]["commit"]
    return overlay, overlay_path.parent, upstream, expected_commit


def validate_overlay(overlay: dict[str, Any], overlay_root: Path, upstream: Path) -> None:
    files = overlay.get("files")
    if not isinstance(files, list) or not files:
        raise PrepareError("overlay must contain at least one file")

    destinations: set[Path] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"source", "destination"}:
            raise PrepareError("overlay files require exactly source and destination")
        source = overlay_root / safe_relative(entry["source"], "source")
        destination = safe_relative(entry["destination"], "destination")
        if not source.is_file():
            raise PrepareError(f"overlay source does not exist: {source}")
        if destination in destinations:
            raise PrepareError(f"duplicate overlay destination: {destination}")
        destinations.add(destination)
        if (upstream / destination).exists():
            raise PrepareError(f"overlay would replace an upstream file: {destination}")


def patch_files(board_id: str, component: str) -> list[Path]:
    directory = ROOT / "boards" / board_id / "patches" / component
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.patch"))


def verify_upstream(upstream: Path, expected_commit: str) -> None:
    if not (upstream / ".git").exists():
        raise PrepareError(f"upstream component is not initialized: {upstream}")
    actual = run(["git", "rev-parse", "HEAD"], upstream, capture=True)
    if actual != expected_commit:
        raise PrepareError(f"upstream commit mismatch: expected {expected_commit}, got {actual}")


def apply_component(
    board_id: str,
    component: str,
    destination: Path,
) -> tuple[Path, Path]:
    overlay, overlay_root, upstream, expected_commit = load_overlay(board_id, component)
    validate_overlay(overlay, overlay_root, upstream)
    verify_upstream(upstream, expected_commit)

    if destination.exists():
        raise PrepareError(f"output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "worktree", "add", "--detach", str(destination), expected_commit], upstream)

    try:
        for patch in patch_files(board_id, component):
            run(["git", "apply", "--check", str(patch)], destination)
            run(["git", "apply", str(patch)], destination)
        for entry in overlay["files"]:
            source = overlay_root / safe_relative(entry["source"], "source")
            target = destination / safe_relative(entry["destination"], "destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except Exception:
        run(["git", "worktree", "remove", "--force", str(destination)], upstream)
        raise
    return upstream, destination


def check_component(board_id: str, component: str) -> None:
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f"check-{board_id}-{component}-", dir=build_root))
    temporary.rmdir()
    upstream: Path | None = None
    try:
        upstream, _ = apply_component(board_id, component, temporary)
        run(
            ["git", "-c", "core.autocrlf=false", "add", "--intent-to-add", "--", "."],
            temporary,
        )
        run(["git", "diff", "--check"], temporary)
    finally:
        if upstream is not None and temporary.exists():
            run(["git", "worktree", "remove", "--force", str(temporary)], upstream)
        elif temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board")
    parser.add_argument("component", choices=sorted(COMPONENTS))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.check and args.output:
        parser.error("--check and --output are mutually exclusive")
    output = (args.output or ROOT / "build" / args.board / args.component).resolve()

    try:
        if args.check:
            check_component(args.board, args.component)
            print(f"checked {args.board}/{args.component}")
        else:
            _, destination = apply_component(args.board, args.component, output)
            print(destination)
    except (PrepareError, OSError, KeyError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
