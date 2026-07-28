#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate board manifests, profiles, source references, and hardware invariants."""

from __future__ import annotations

import argparse
import itertools
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


def validate_profile(board: dict[str, Any], path: Path) -> dict[str, Any]:
    profile = load_yaml(path)
    validate_schema(profile, load_json(PROFILE_SCHEMA), path)
    if profile["board"] != board["id"]:
        raise ContractError(f"{path}: profile board does not match {board['id']}")
    if profile["id"] != path.stem:
        raise ContractError(f"{path}: profile id does not match its filename")
    validate_sources(board, profile)
    validate_ranges(profile)
    return profile


def validate_profile_selection(
    board: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
) -> None:
    dimensions = board["build"]["profile_selection"]["dimensions"]
    dimension_names = set(dimensions)
    expected = {
        tuple(values)
        for values in itertools.product(
            *(dimensions[name] for name in dimensions)
        )
    }

    selected: dict[tuple[str, ...], str] = {}
    for profile_id, profile in profiles.items():
        selection = profile["selection"]
        if set(selection) != dimension_names:
            raise ContractError(
                f"{profile_id}: selection keys must match profile-selection dimensions"
            )
        for name, value in selection.items():
            if value not in dimensions[name]:
                raise ContractError(
                    f"{profile_id}: invalid {name} selection {value!r}"
                )
        key = tuple(selection[name] for name in dimensions)
        if key in selected:
            raise ContractError(
                f"duplicate profile selection: {profile_id} and {selected[key]}"
            )
        selected[key] = profile_id

        topology = selection.get("rf_topology")
        if topology and profile["datapath"]["mode"] != topology:
            raise ContractError(
                f"{profile_id}: datapath mode does not match rf_topology"
            )

    if set(selected) != expected:
        missing = sorted("-".join(values) for values in expected - set(selected))
        extra = sorted("-".join(values) for values in set(selected) - expected)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected: {', '.join(extra)}")
        raise ContractError(
            "profiles must cover each profile-selection combination exactly once"
            + f" ({'; '.join(details)})"
        )


def validate_contract(path: Path) -> None:
    board = load_yaml(path)
    validate_schema(board, load_json(BOARD_SCHEMA), path)

    if path.parent.name != board["id"]:
        raise ContractError(
            f"{path}: board id {board['id']!r} does not match directory {path.parent.name!r}"
        )

    profile_paths = sorted((path.parent / "profiles").glob("*.yaml"))
    if not profile_paths:
        raise ContractError(f"no profiles found in {path.parent / 'profiles'}")
    profiles = {profile_path.stem: validate_profile(board, profile_path) for profile_path in profile_paths}
    if len(profiles) != len(profile_paths):
        raise ContractError(f"duplicate profile id in {path.parent / 'profiles'}")

    validate_profile_selection(board, profiles)
    profile_dtbs = {profile["artifacts"]["linux_dtb"] for profile in profiles.values()}
    if profile_dtbs != set(board["build"]["linux_dtbs"]):
        raise ContractError("linux_dtbs must match the DTB artifacts of all board profiles")
    profile_fit_configs = {
        profile["artifacts"]["fit_configuration"] for profile in profiles.values()
    }
    if len(profile_fit_configs) != len(profiles):
        raise ContractError("FIT configuration names must be unique")

    validate_unique_hardware(board)
    validate_qspi(board)

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
