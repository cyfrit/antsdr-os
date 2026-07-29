#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run read-only E310 boot smoke checks after an operator explicitly permits it."""

from __future__ import annotations

import argparse
import configparser
import socket
import subprocess
import sys
from pathlib import Path


class SmokeError(RuntimeError):
    pass


REMOTE_SERVICE_CHECK = r"""set -eu
pidof iiod
grep -q '^hw_model=' /etc/libiio.ini
test -r /opt/antsdr/config.vfat
test -e /sys/kernel/config/usb_gadget/antsdr/functions/mass_storage.0/lun.0/file
"""


def check_port(host: str, port: int, timeout: float) -> None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as error:
        raise SmokeError(f"cannot reach {host}:{port}: {error}") from error


def check_config_volume(path: Path) -> None:
    if not path.is_file():
        raise SmokeError(f"configuration volume is missing config.txt: {path}")
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    with path.open(encoding="utf-8-sig") as stream:
        parser.read_file(stream)
    for section, keys in {
        "USB_ETHERNET": {"ipaddr", "ipaddr_host", "netmask"},
        "NETWORK": {"mode", "ipaddr_eth", "netmask_eth"},
    }.items():
        if section not in parser:
            raise SmokeError(f"configuration volume has no [{section}] section")
        missing = keys - set(parser[section])
        if missing:
            raise SmokeError(f"configuration volume [{section}] is missing: {', '.join(sorted(missing))}")


def ssh_command(args: argparse.Namespace) -> list[str]:
    command = [
        args.ssh_bin,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={args.timeout}",
        "-p",
        str(args.ssh_port),
    ]
    if args.identity:
        command.extend(["-i", str(args.identity)])
    command.extend([f"{args.ssh_user}@{args.host}", REMOTE_SERVICE_CHECK])
    return command


def check_ssh(args: argparse.Namespace) -> None:
    result = subprocess.run(ssh_command(args), check=False, capture_output=True, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SmokeError(f"read-only remote smoke check failed: {detail}")


def check_serial(port: str, baud: int, expect: str, timeout: float) -> None:
    try:
        import serial
    except ImportError as error:
        raise SmokeError("--serial-port requires pyserial on the host") from error
    with serial.Serial(port, baudrate=baud, timeout=timeout) as console:
        output = console.read(4096).decode("utf-8", errors="replace")
    if expect not in output:
        raise SmokeError(f"serial console did not contain expected text: {expect!r}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--execute", action="store_true", help="perform read-only checks against hardware")
    result.add_argument("--host", default="10.31.0.1")
    result.add_argument("--ssh-user", default="root")
    result.add_argument("--ssh-port", type=int, default=22)
    result.add_argument("--iio-port", type=int, default=30431)
    result.add_argument("--timeout", type=float, default=5.0)
    result.add_argument("--ssh-check", action="store_true", help="also run remote service checks")
    result.add_argument("--ssh-bin", default="ssh")
    result.add_argument("--identity", type=Path)
    result.add_argument("--config-volume", type=Path, help="host path to exported config.txt")
    result.add_argument("--serial-port", help="read-only serial console port, for example COM8")
    result.add_argument("--serial-baud", type=int, default=115200)
    result.add_argument("--serial-expect", default="login:")
    return result


def plan(args: argparse.Namespace) -> list[str]:
    checks = [f"TCP {args.host}:{args.ssh_port}", f"TCP {args.host}:{args.iio_port}"]
    if args.config_volume:
        checks.append(f"read {args.config_volume}")
    if args.ssh_check:
        checks.append("SSH read-only IIOD, config volume, and USB gadget state")
    if args.serial_port:
        checks.append(f"read serial {args.serial_port} at {args.serial_baud} baud")
    return checks


def main() -> int:
    args = parser().parse_args()
    if args.timeout <= 0 or args.ssh_port <= 0 or args.iio_port <= 0 or args.serial_baud <= 0:
        print("ports, baud rate, and timeout must be positive", file=sys.stderr)
        return 2
    for check in plan(args):
        print(check)
    if not args.execute:
        print("plan only; pass --execute to contact hardware")
        return 0
    try:
        check_port(args.host, args.ssh_port, args.timeout)
        check_port(args.host, args.iio_port, args.timeout)
        if args.config_volume:
            check_config_volume(args.config_volume)
        if args.ssh_check:
            check_ssh(args)
        if args.serial_port:
            check_serial(args.serial_port, args.serial_baud, args.serial_expect, args.timeout)
        print("E310 read-only smoke checks passed")
        return 0
    except SmokeError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
