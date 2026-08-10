#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve and validate AntSDR OS release metadata.

The public release number is intentionally separate from board and upstream
coordinates.  A release artifact must therefore carry both the OS ABI version
and the exact source commits used to make it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from board_data import REPOSITORY_ROOT, load_board


METADATA = REPOSITORY_ROOT / "release" / "antsdr-os.yaml"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ReleaseMetadataError(RuntimeError):
    """Invalid release metadata or tag."""


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseMetadataError(f"{label} must be a mapping")
    return value


def load_metadata(path: Path = METADATA) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ReleaseMetadataError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ReleaseMetadataError(f"{path}: unsupported metadata schema")
    product = _mapping(data.get("product"), "product")
    version = str(product.get("version", ""))
    major = product.get("major")
    point = product.get("point")
    if not isinstance(major, int) or not isinstance(point, int) or not VERSION.fullmatch(version):
        raise ReleaseMetadataError("product major/point/version must be a two-component version")
    if version != f"{major}.{point}":
        raise ReleaseMetadataError("product version must match major.point")
    if not isinstance(product.get("name"), str) or not product["name"]:
        raise ReleaseMetadataError("product.name must be non-empty")
    if not isinstance(product.get("slug"), str) or not SLUG.fullmatch(product["slug"]):
        raise ReleaseMetadataError("product.slug must be a lowercase, hyphenated identifier")
    if not isinstance(data.get("supported_boards"), list) or not data["supported_boards"]:
        raise ReleaseMetadataError("supported_boards must be non-empty")
    board_ids: set[str] = set()
    artifact_ids: set[str] = set()
    for entry in data["supported_boards"]:
        board = _mapping(entry, "supported_boards entry")
        for key in ("id", "hardware_revision", "artifact_id"):
            if not isinstance(board.get(key), str) or not board[key]:
                raise ReleaseMetadataError(f"supported board lacks {key}")
        if not SLUG.fullmatch(board["artifact_id"]):
            raise ReleaseMetadataError("supported board artifact_id must be a lowercase, hyphenated identifier")
        if board["id"] in board_ids or board["artifact_id"] in artifact_ids:
            raise ReleaseMetadataError("supported board ids and artifact ids must be unique")
        board_ids.add(board["id"])
        artifact_ids.add(board["artifact_id"])
    artifacts = _mapping(data.get("artifacts"), "artifacts")
    for key in ("name_template", "tag_template"):
        if not isinstance(artifacts.get(key), str) or not artifacts[key]:
            raise ReleaseMetadataError(f"artifacts.{key} must be non-empty")
    try:
        tag = artifacts["tag_template"].format(product=product["slug"], version=version)
        name = artifacts["name_template"].format(
            product=product["slug"],
            version=version,
            target="target",
            adi_release="upstream",
        )
    except (KeyError, ValueError) as error:
        raise ReleaseMetadataError(f"invalid artifact template: {error}") from error
    if tag != f"{product['slug']}-{version}":
        raise ReleaseMetadataError("release tag template must contain only the product slug and version")
    if not SLUG.fullmatch(name.replace(".", "-")):
        raise ReleaseMetadataError("artifact name template produces an invalid identifier")
    return data


def git_value(args: list[str], default: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return default
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else default


def build_metadata(
    board_id: str,
    *,
    git_sha: str | None = None,
    source_date_epoch: str | None = None,
    version: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    data = load_metadata()
    product = data["product"]
    release_version = version or str(product["version"])
    if not VERSION.fullmatch(release_version):
        raise ReleaseMetadataError(f"invalid release version: {release_version}")
    board = load_board(board_id)
    upstream = board["upstream"]
    components = upstream["components"]
    component_commits = {name: value["commit"] for name, value in components.items()}
    pluto_commit = upstream["plutosdr_fw"]["commit"]
    if not HEX40.fullmatch(pluto_commit) or any(not HEX40.fullmatch(value) for value in component_commits.values()):
        raise ReleaseMetadataError("all upstream commits must be full 40-character SHA-1 values")
    board_entry = next((entry for entry in data["supported_boards"] if entry["id"] == board_id), None)
    if board_entry is None:
        raise ReleaseMetadataError(f"board {board_id} is not listed in release metadata")
    abi = data["compatibility"]
    result = {
        "schema_version": 1,
        "os_name": product["name"],
        "os_version": release_version,
        "channel": channel or product.get("channel", "development"),
        "board": board_id,
        "hardware_revision": board_entry["hardware_revision"],
        "hardware_target": board_entry["artifact_id"],
        "adi_baseline": data["upstream"]["adi_release"],
        "adi_plutosdr_fw_commit": pluto_commit,
        "component_commits": component_commits,
        "boot_abi": abi["boot_abi"],
        "qspi_layout": abi["qspi_layout"],
        "uenv_abi": abi["uenv_abi"],
        "profile_schema": abi["profile_schema"],
        "git_commit": git_sha or git_value(["rev-parse", "HEAD"], "unknown"),
        "source_date_epoch": source_date_epoch or os.environ.get("SOURCE_DATE_EPOCH", "0"),
    }
    if not HEX40.fullmatch(result["git_commit"]):
        if result["git_commit"] != "unknown":
            raise ReleaseMetadataError("git_commit must be a full commit SHA")
    if not str(result["source_date_epoch"]).isdigit():
        raise ReleaseMetadataError("source_date_epoch must be an integer")
    result["artifact_stem"] = data["artifacts"]["name_template"].format(
        product=product["slug"],
        version=release_version,
        target=board_entry["artifact_id"],
        adi_release=data["upstream"]["adi_release"],
    )
    result["release_tag"] = data["artifacts"]["tag_template"].format(
        product=product["slug"],
        version=release_version,
    )
    return result


def release_targets(build_label: str = "release") -> list[dict[str, str]]:
    if not build_label or any(character.isspace() for character in build_label):
        raise ReleaseMetadataError("build label must be non-empty and contain no whitespace")
    data = load_metadata()
    targets: list[dict[str, str]] = []
    for entry in data["supported_boards"]:
        metadata = build_metadata(
            str(entry["id"]),
            git_sha="unknown",
            source_date_epoch="0",
        )
        targets.append(
            {
                "board": str(metadata["board"]),
                "artifact_name": f"{metadata['artifact_stem']}-{build_label}",
            }
        )
    return targets


def validate_tag(value: str) -> str:
    data = load_metadata()
    product = data["product"]
    version = str(product["version"])
    expected = data["artifacts"]["tag_template"].format(
        product=product["slug"],
        version=version,
    )
    if value != expected:
        raise ReleaseMetadataError(
            f"tag must be {expected} for the current release manifest"
        )
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    show = subparsers.add_parser("show")
    show.add_argument("--board", required=True)
    show.add_argument("--format", choices=("json", "github"), default="json")
    show.add_argument("--version")
    show.add_argument("--channel")
    targets = subparsers.add_parser("targets")
    targets.add_argument("--build-label", default="release")
    check = subparsers.add_parser("check")
    check.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        if args.action == "check":
            validate_tag(args.tag)
            print(f"valid tag: {args.tag}")
        elif args.action == "targets":
            print(json.dumps(release_targets(args.build_label), separators=(",", ":")))
        else:
            payload = build_metadata(args.board, version=args.version, channel=args.channel)
            if args.format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for key, value in sorted(payload.items()):
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, separators=(",", ":"))
                    print(f"{key}={value}")
        return 0
    except (ReleaseMetadataError, OSError, KeyError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
