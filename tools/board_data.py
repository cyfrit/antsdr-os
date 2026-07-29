#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Shared, read-only access to board contracts and repository paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class BoardDataError(RuntimeError):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping without interpreting board-specific fields."""
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise BoardDataError(f"{path}: expected a YAML mapping")
    return data


def board_directory(board_id: str) -> Path:
    return REPOSITORY_ROOT / "boards" / board_id


def load_board(board_id: str, *, validate: bool = True) -> dict[str, Any]:
    """Load a board contract, optionally enforcing its complete schema."""
    directory = board_directory(board_id)
    contract = directory / "board.yaml"
    if validate:
        # Keep schema validation out of the path-only helpers to avoid a
        # dependency cycle with validate_boards.py.
        from validate_boards import validate_contract

        validate_contract(contract)
    board = load_yaml(contract)
    if board.get("id") != board_id:
        raise BoardDataError(f"board id mismatch in {contract}")
    return board


def load_profiles(board_id: str) -> list[dict[str, Any]]:
    directory = board_directory(board_id) / "profiles"
    profiles = [load_yaml(path) for path in sorted(directory.glob("*.yaml"))]
    if not profiles:
        raise BoardDataError(f"no profiles found in {directory}")
    return profiles


def external_path(path: Path, option: str) -> Path:
    """Resolve an output/workspace path and reject repository-local state."""
    resolved = path.expanduser().resolve()
    if resolved == REPOSITORY_ROOT or resolved.is_relative_to(REPOSITORY_ROOT):
        raise BoardDataError(f"{option} must be outside this repository")
    return resolved
