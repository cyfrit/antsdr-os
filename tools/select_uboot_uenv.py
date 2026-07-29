#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Select the E310 U-Boot uEnv compatibility mode in an external build."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SETTING = "CONFIG_ANTSDR_UENV_COMPAT"


def select_mode(config: Path, mode: str) -> None:
    text = config.read_text(encoding="utf-8")
    lines = [
        line
        for line in text.splitlines()
        if not re.match(rf"^(# )?{re.escape(SETTING)}(=| is not set$)", line)
    ]
    lines.append(f"{SETTING}=y" if mode == "compat" else f"# {SETTING} is not set")
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("compat", "locked"))
    args = parser.parse_args()
    try:
        select_mode(args.config, args.mode)
    except OSError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
