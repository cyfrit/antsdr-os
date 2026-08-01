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

from board_data import (
    BoardDataError,
    REPOSITORY_ROOT,
    board_directory,
    load_board,
    load_profiles,
)
from validate_boards import ContractError, validate_contract


ROOT = REPOSITORY_ROOT


class FitError(RuntimeError):
    pass


def fit_image_name(prefix: str, value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", value.rsplit(".", 1)[0])
    return f"{prefix}-{name}"


def quoted(value: str) -> str:
    if '"' in value or "\\" in value:
        raise FitError(f"unsupported FIT string: {value!r}")
    return f'"{value}"'


def profile_description(profile: dict[str, Any]) -> str:
    transceiver = profile["transceiver"]["physical_marking"]
    topology = profile["datapath"]["mode"].upper()
    return f"ANTSDR E310 {transceiver} {topology}"


def render_its(
    board: dict[str, Any],
    profiles: list[dict[str, Any]],
    *,
    signed: bool = False,
) -> str:
    firmware = board["build"]["firmware"]
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
        f'\t\t\tdata = /incbin/({quoted(firmware["kernel_image"])});',
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
        f'\t\t\tdata = /incbin/({quoted(firmware["rootfs_image"])});',
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
            ]
        )
        if signed:
            lines.extend(
                [
                    "\t\t\tsignature {",
                    '\t\t\t\talgo = "sha256,rsa2048";',
                    '\t\t\t\tkey-name-hint = "antsdr-os-release";',
                    '\t\t\t\tsign-images = "kernel", "ramdisk", "fdt", "fpga";',
                    "\t\t\t};",
                ]
            )
        lines.append("\t\t};")
    lines.extend(["\t};", "};", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--signed", action="store_true")
    args = parser.parse_args()

    if args.check == (args.output is not None):
        parser.error("provide exactly one of --check or --output")

    board_dir = board_directory(args.board)
    try:
        validate_contract(board_dir / "board.yaml")
        board = load_board(args.board, validate=False)
        its = render_its(board, load_profiles(args.board), signed=args.signed)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(its, encoding="utf-8")
            print(args.output)
        else:
            print(f"checked FIT source for {args.board}")
    except (BoardDataError, ContractError, FitError, OSError, KeyError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
