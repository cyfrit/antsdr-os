#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the committed FIT public key data and release certificate policy."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


class KeyVerificationError(RuntimeError):
    pass


def openssl(*args: str) -> str:
    result = subprocess.run(
        ["openssl", *args], check=False, capture_output=True, text=True
    )
    if result.returncode:
        raise KeyVerificationError(result.stderr.strip() or "openssl failed")
    return result.stdout


def cells(source: str, property_name: str) -> list[int]:
    match = re.search(rf"{re.escape(property_name)}\s*=\s*<(?P<body>.*?)>;", source, re.S)
    if not match:
        raise KeyVerificationError(f"missing DTS property: {property_name}")
    return [int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]+)", match.group("body"))]


def verify(certificate: Path, dtsi: Path) -> None:
    text = dtsi.read_text(encoding="utf-8")
    modulus_output = openssl("x509", "-in", str(certificate), "-noout", "-modulus").strip()
    if not modulus_output.startswith("Modulus="):
        raise KeyVerificationError("openssl did not return an RSA modulus")
    certificate_modulus = int(modulus_output.removeprefix("Modulus="), 16)
    modulus_words = cells(text, "rsa,modulus")
    modulus = sum(word << (32 * index) for index, word in enumerate(reversed(modulus_words)))
    if modulus != certificate_modulus:
        raise KeyVerificationError("DTS modulus does not match the release certificate")
    expected_n0 = (-pow(modulus & 0xFFFFFFFF, -1, 1 << 32)) & 0xFFFFFFFF
    if cells(text, "rsa,n0-inverse") != [expected_n0]:
        raise KeyVerificationError("DTS rsa,n0-inverse is invalid")
    expected_r2 = (1 << (64 * len(modulus_words))) % modulus
    r2_words = cells(text, "rsa,r-squared")
    r2 = sum(word << (32 * index) for index, word in enumerate(reversed(r2_words)))
    if r2 != expected_r2:
        raise KeyVerificationError("DTS rsa,r-squared is invalid")

    details = openssl("x509", "-in", str(certificate), "-noout", "-text")
    for required in ("CA:FALSE", "Digital Signature", "Subject Key Identifier", "Authority Key Identifier"):
        if required not in details:
            raise KeyVerificationError(f"release certificate lacks {required}")
    if "Basic Constraints: critical" not in details or "Key Usage: critical" not in details:
        raise KeyVerificationError("release certificate constraints and key usage must be critical")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--dtsi", required=True, type=Path)
    args = parser.parse_args()
    try:
        verify(args.certificate, args.dtsi)
        print("verified ANTSDR OS FIT release key")
        return 0
    except (OSError, ValueError, KeyVerificationError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
