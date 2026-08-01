#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify every explicit ANTSDR FIT profile with U-Boot's host verifier."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from board_data import BoardDataError, load_profiles


Runner = Callable[[list[str]], None]


class FitVerificationError(RuntimeError):
    pass


def default_runner(command: list[str]) -> None:
    subprocess.run(command, check=True)


def require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FitVerificationError(f"missing {label}: {resolved}")
    return resolved


def verify_profiles(
    fit: Path,
    control_dtb: Path,
    fit_check_sign: Path,
    fdtput: str,
    board: str,
    *,
    runner: Runner = default_runner,
) -> list[str]:
    fit = require_file(fit, "FIT image")
    control_dtb = require_file(control_dtb, "embedded U-Boot control DTB")
    fit_check_sign = require_file(fit_check_sign, "U-Boot FIT signature verifier")
    configurations = [str(profile["artifacts"]["fit_configuration"]) for profile in load_profiles(board)]
    if not configurations or len(configurations) != len(set(configurations)):
        raise FitVerificationError("board profiles must provide unique FIT configurations")

    # ADI's fit_check_sign only selects /configurations/default.  E310 chooses
    # profiles explicitly at boot, so add that property only to disposable copies.
    with tempfile.TemporaryDirectory(prefix="antsdr-fit-verify-") as directory:
        temporary = Path(directory)
        for index, configuration in enumerate(configurations):
            candidate = temporary / f"profile-{index}.itb"
            shutil.copy2(fit, candidate)
            runner([fdtput, "-p", "-t", "s", str(candidate), "/configurations", "default", configuration])
            runner([str(fit_check_sign), "-f", str(candidate), "-k", str(control_dtb)])
    return configurations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit", required=True, type=Path)
    parser.add_argument("--control-dtb", required=True, type=Path)
    parser.add_argument("--fit-check-sign", required=True, type=Path)
    parser.add_argument("--fdtput", default="fdtput")
    parser.add_argument("--board", default="e310")
    args = parser.parse_args()
    try:
        configurations = verify_profiles(
            args.fit,
            args.control_dtb,
            args.fit_check_sign,
            args.fdtput,
            args.board,
        )
        print(f"verified FIT signatures for {len(configurations)} profile(s)")
        return 0
    except (BoardDataError, FitVerificationError, OSError, subprocess.CalledProcessError, KeyError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
