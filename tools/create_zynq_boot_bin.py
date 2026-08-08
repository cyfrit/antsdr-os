#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assemble a Zynq-7000 BOOT.BIN from verified component files."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hardware_cache import HardwareCacheError, validate_zynq_fsbl


class BootImageError(RuntimeError):
    pass


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise BootImageError(f"missing {label}: {path}")
    return path


def bif_text() -> str:
    return """the_ROM_image:
{
[bootloader] fsbl.elf
system_top.bit
u-boot.elf
}
"""


def create_boot_image(
    fsbl: Path,
    bitstream: Path,
    u_boot: Path,
    bootgen: Path,
    output: Path,
) -> None:
    fsbl = require_file(fsbl, "FSBL")
    bitstream = require_file(bitstream, "FPGA bitstream")
    u_boot = require_file(u_boot, "U-Boot ELF")
    bootgen = require_file(bootgen, "host bootgen")
    validate_zynq_fsbl(fsbl)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".boot-bin-", dir=output.parent) as directory:
        staging = Path(directory)
        shutil.copy2(fsbl, staging / "fsbl.elf")
        shutil.copy2(bitstream, staging / "system_top.bit")
        shutil.copy2(u_boot, staging / "u-boot.elf")
        (staging / "zynq.bif").write_text(bif_text(), encoding="ascii")
        result = subprocess.run(
            [str(bootgen), "-image", "zynq.bif", "-w", "-o", "BOOT.BIN"],
            cwd=staging,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise BootImageError(f"bootgen failed with status {result.returncode}: {detail}")
        temporary_output = require_file(staging / "BOOT.BIN", "generated BOOT.BIN")
        os.replace(temporary_output, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fsbl", required=True, type=Path)
    parser.add_argument("--bitstream", required=True, type=Path)
    parser.add_argument("--u-boot", required=True, type=Path)
    parser.add_argument("--bootgen", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        create_boot_image(args.fsbl, args.bitstream, args.u_boot, args.bootgen, args.output)
        print(args.output.expanduser().resolve())
        return 0
    except (BootImageError, HardwareCacheError, OSError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
