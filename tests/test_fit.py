# SPDX-License-Identifier: MIT
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "boards" / "e310"


class FitGenerationTest(unittest.TestCase):
    def test_fit_source_covers_each_e310_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "antsdr-e310.its"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "generate_fit.py"),
                    "e310",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            its = output.read_text(encoding="utf-8")

        profiles = [
            yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted((BOARD / "profiles").glob("*.yaml"))
        ]
        self.assertNotIn("md5", its.lower())
        self.assertGreaterEqual(its.count('algo = "sha256"'), len(profiles) + 3)
        self.assertEqual(its.count('fpga = "fpga-system_top";'), len(profiles))

        for profile in profiles:
            artifacts = profile["artifacts"]
            self.assertIn(f"{artifacts['fit_configuration']} {{", its)
            self.assertIn(f'/incbin/("{artifacts["linux_dtb"]}")', its)

    def test_fit_contract_is_valid_without_build_outputs(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "generate_fit.py"),
                "e310",
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_signed_fit_signs_every_configuration(self) -> None:
        sys.path.insert(0, str(ROOT / "tools"))
        from board_data import load_board, load_profiles
        from generate_fit import render_its

        profiles = load_profiles("e310")
        its = render_its(load_board("e310"), profiles, signed=True)
        self.assertEqual(its.count('algo = "sha256,rsa2048";'), len(profiles))
        self.assertEqual(its.count('key-name-hint = "antsdr-os-release";'), len(profiles))
        self.assertEqual(
            its.count('sign-images = "kernel", "ramdisk", "fdt", "fpga";'),
            len(profiles),
        )


if __name__ == "__main__":
    unittest.main()
