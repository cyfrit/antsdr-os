#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate a deterministic multi-profile FIT source from a board contract."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from validate_boards import ContractError, validate_contract


ROOT = Path(__file__).resolve().parents[1]


class FitError(RuntimeError):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise FitError(f"{path}: expected a YAML mapping")
    return data


def fit_image_name(prefix: str, value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", value.rsplit(".", 1)[0])
    return f"{prefix}-{name}"


def quoted(value: str) -> str:
    if '"' in value or "\\" in value:
        raise FitError(f"unsupported FIT string: {value!r}")
    return f'"{value}"'


def profile_description(profile: dict[str, Any]) -> str:
    transceiver = profile["transceiver"]["selected_model"]
    topology = profile["datapath"]["mode"].upper()
    return f"ANTSDR E310 {transceiver} {topology}"


def load_profiles(board_dir: Path) -> list[dict[str, Any]]:
    profiles = [
        load_yaml(path)
        for path in sorted((board_dir / "profiles").glob("*.yaml"))
    ]
    if not profiles:
        raise FitError(f"no profiles found in {board_dir / 'profiles'}")
    return profiles


def render_its(board: dict[str, Any], profiles: list[dict[str, Any]]) -> str:
    bitstreams = {
        profile["artifacts"]["fpga_bitstream"]
        for profile in profiles
    }
    if len(bitstreams) != 1:
        raise FitError(
            "a selectable profile set must use one universal FPGA bitstream"
        )

    bitstream = next(iter(bitstreams))
    fpga_image = fit_image_name("fpga", bitstream)
    description = f"ANTSDR {board['name']} multi-profile firmware"
    lines = [
        "/dts-v1/;",
        "",
        "/ {",
        f"\tdescription = {quoted(description)};",
        '\tmagic = "ITB ANTSDR";',
        "\t#address-cells = <1>;",
        "",
        "\timages {",
        "\t\tkernel {",
        '\t\t\tdescription = "Linux";',
        '\t\t\tdata = /incbin/("zImage");',
        '\t\t\ttype = "kernel";',
        '\t\t\tarch = "arm";',
        '\t\t\tos = "linux";',
        '\t\t\tcompression = "none";',
        "\t\t\tload = <0x00008000>;",
        "\t\t\tentry = <0x00008000>;",
        "\t\t\thash { algo = \"sha256\"; };",
        "\t\t};",
        "",
        "\t\tramdisk {",
        '\t\t\tdescription = "Buildroot root filesystem";',
        '\t\t\tdata = /incbin/("rootfs.cpio.gz");',
        '\t\t\ttype = "ramdisk";',
        '\t\t\tarch = "arm";',
        '\t\t\tos = "linux";',
        '\t\t\tcompression = "gzip";',
        "\t\t\thash { algo = \"sha256\"; };",
        "\t\t};",
        "",
        f"\t\t{fpga_image} {{",
        '\t\t\tdescription = "E310 universal 2R2T-capable FPGA";',
        f"\t\t\tdata = /incbin/({quoted(bitstream)});",
        '\t\t\ttype = "fpga";',
        '\t\t\tarch = "arm";',
        '\t\t\tcompression = "none";',
        "\t\t\tload = <0x0f000000>;",
        "\t\t\thash { algo = \"sha256\"; };",
        "\t\t};",
        "",
    ]

    for profile in profiles:
        artifact = profile["artifacts"]["linux_dtb"]
        fdt_image = fit_image_name("fdt", profile["id"])
        lines.extend(
            [
                f"\t\t{fdt_image} {{",
                f"\t\t\tdescription = {quoted(profile_description(profile))};",
                f"\t\t\tdata = /incbin/({quoted(artifact)});",
                '\t\t\ttype = "flat_dt";',
                '\t\t\tarch = "arm";',
                '\t\t\tcompression = "none";',
                "\t\t\thash { algo = \"sha256\"; };",
                "\t\t};",
                "",
            ]
        )

    lines.extend(["\t};", "", "\tconfigurations {"])
    for profile in profiles:
        configuration = profile["artifacts"]["fit_configuration"]
        fdt_image = fit_image_name("fdt", profile["id"])
        lines.extend(
            [
                f"\t\t{configuration} {{",
                f"\t\t\tdescription = {quoted(profile_description(profile))};",
                '\t\t\tkernel = "kernel";',
                '\t\t\tramdisk = "ramdisk";',
                f"\t\t\tfdt = {quoted(fdt_image)};",
                f"\t\t\tfpga = {quoted(fpga_image)};",
                "\t\t};",
            ]
        )
    lines.extend(["\t};", "};", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check == (args.output is not None):
        parser.error("provide exactly one of --check or --output")

    board_dir = ROOT / "boards" / args.board
    try:
        validate_contract(board_dir / "board.yaml")
        board = load_yaml(board_dir / "board.yaml")
        if board["id"] != args.board:
            raise FitError(f"{board_dir}: board id mismatch")
        its = render_its(board, load_profiles(board_dir))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(its, encoding="utf-8")
            print(args.output)
        else:
            print(f"checked FIT source for {args.board}")
    except (ContractError, FitError, OSError, KeyError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
