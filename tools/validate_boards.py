#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate board manifests, profiles, source references, and hardware invariants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
BOARD_SCHEMA = ROOT / "boards" / "schema" / "board-v1.schema.json"
PROFILE_SCHEMA = ROOT / "boards" / "schema" / "profile-v1.schema.json"


class ContractError(RuntimeError):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ContractError(f"{path}: expected a YAML mapping")
    return data


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def validate_schema(data: dict[str, Any], schema: dict[str, Any], path: Path) -> None:
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    if errors:
        details = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            details.append(f"{path}:{location}: {error.message}")
        raise ContractError("\n".join(details))


def referenced_sources(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "sources" and isinstance(child, list):
                refs.update(item for item in child if isinstance(item, str))
            elif key != "sources":
                refs.update(referenced_sources(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(referenced_sources(child))
    return refs


def validate_sources(board: dict[str, Any], profile: dict[str, Any]) -> None:
    defined = set(board["sources"])
    used = referenced_sources(board) | set(profile["sources"])
    missing = sorted(used - defined)
    if missing:
        raise ContractError(f"undefined source references: {', '.join(missing)}")

    required_groups = ["soc", "ddr", "rf", "datapath", "boot"]
    for group in required_groups:
        if not board["hardware"][group].get("sources"):
            raise ContractError(f"hardware.{group} must cite at least one source")
    for group in ("clocks", "gpios"):
        for index, fact in enumerate(board["hardware"][group]):
            if not fact.get("sources"):
                raise ContractError(f"hardware.{group}[{index}] must cite at least one source")


def validate_unique_hardware(board: dict[str, Any]) -> None:
    clocks = [clock["name"] for clock in board["hardware"]["clocks"]]
    if len(clocks) != len(set(clocks)):
        raise ContractError("clock names must be unique")

    gpio_keys = [
        (gpio["controller"], gpio["line"])
        for gpio in board["hardware"]["gpios"]
    ]
    if len(gpio_keys) != len(set(gpio_keys)):
        raise ContractError("GPIO controller/line assignments must be unique")


def validate_qspi(board: dict[str, Any]) -> None:
    qspi = board["hardware"]["boot"]["qspi"]
    partitions = sorted(qspi["partitions"], key=lambda part: part["offset"])
    cursor = 0
    for partition in partitions:
        if partition["offset"] < cursor:
            raise ContractError(f"QSPI partition overlaps: {partition['name']}")
        cursor = partition["offset"] + partition["size"]
    if cursor > qspi["size_bytes"]:
        raise ContractError("QSPI partitions exceed declared flash size")


def validate_ranges(profile: dict[str, Any]) -> None:
    for name in ("rx_frequency_hz", "tx_frequency_hz", "bandwidth_hz"):
        value = profile["transceiver"][name]
        if value["min"] >= value["max"]:
            raise ContractError(f"profile transceiver.{name} has an invalid range")


def validate_contract(path: Path) -> None:
    board = load_yaml(path)
    validate_schema(board, load_json(BOARD_SCHEMA), path)

    if path.parent.name != board["id"]:
        raise ContractError(
            f"{path}: board id {board['id']!r} does not match directory {path.parent.name!r}"
        )

    profile_path = path.parent / "profiles" / f"{board['build']['default_profile']}.yaml"
    if not profile_path.is_file():
        raise ContractError(f"default profile does not exist: {profile_path}")
    profile = load_yaml(profile_path)
    validate_schema(profile, load_json(PROFILE_SCHEMA), profile_path)
    if profile["board"] != board["id"]:
        raise ContractError(f"{profile_path}: profile board does not match {board['id']}")
    if profile["id"] != board["build"]["default_profile"]:
        raise ContractError(f"{profile_path}: profile id does not match its filename")

    validate_sources(board, profile)
    validate_unique_hardware(board)
    validate_qspi(board)
    validate_ranges(profile)

    if board["status"] == "hardware-validated" and board["support"]["firmware_validation"] != "hardware-tested":
        raise ContractError("hardware-validated status requires hardware-tested firmware evidence")


def discover_contracts() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "boards").glob("*/board.yaml")
        if path.parent.name != "schema"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contracts", nargs="*", type=Path)
    args = parser.parse_args()

    contracts = [path.resolve() for path in args.contracts] or discover_contracts()
    if not contracts:
        print("no board contracts found", file=sys.stderr)
        return 1

    try:
        for contract in contracts:
            validate_contract(contract)
            print(f"validated {contract.relative_to(ROOT)}")
    except (ContractError, OSError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
