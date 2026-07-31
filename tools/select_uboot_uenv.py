#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Select the E310 U-Boot uEnv compatibility mode in an external build."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


UENV_SETTING = "CONFIG_ANTSDR_UENV_COMPAT"
FIT_SETTING = "CONFIG_ANTSDR_FIT_SIGNATURE_REQUIRED"


def select_mode(config: Path, mode: str, fit_signature_required: bool = False) -> None:
    text = config.read_text(encoding="utf-8")
    lines = [
        line
        for line in text.splitlines()
        if not any(
            re.match(rf"^(# )?{re.escape(setting)}(=| is not set$)", line)
            for setting in (UENV_SETTING, FIT_SETTING)
        )
    ]
    lines.append(f"{UENV_SETTING}=y" if mode == "compat" else f"# {UENV_SETTING} is not set")
    lines.append(f"{FIT_SETTING}=y" if fit_signature_required else f"# {FIT_SETTING} is not set")
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("compat", "locked"))
    parser.add_argument("--fit-signature-required", action="store_true")
    args = parser.parse_args()
    try:
        select_mode(args.config, args.mode, args.fit_signature_required)
    except OSError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
