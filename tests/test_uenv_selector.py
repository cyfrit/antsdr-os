# SPDX-License-Identifier: MIT
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "tools" / "select_uboot_uenv.py"


class UenvSelectorTest(unittest.TestCase):
    def run_selector(self, config: Path, mode: str) -> None:
        result = subprocess.run(
            [sys.executable, str(SELECTOR), "--config", str(config), "--mode", mode],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_modes_are_idempotent_and_replace_existing_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".config"
            config.write_text(
                "CONFIG_FIT=y\n"
                "CONFIG_ANTSDR_UENV_COMPAT=y\n"
                "# CONFIG_ANTSDR_UENV_COMPAT is not set\n",
                encoding="utf-8",
            )

            self.run_selector(config, "locked")
            self.assertEqual(
                config.read_text(encoding="utf-8"),
                "CONFIG_FIT=y\n# CONFIG_ANTSDR_UENV_COMPAT is not set\n",
            )

            self.run_selector(config, "locked")
            self.assertEqual(config.read_text(encoding="utf-8").count("ANTSDR_UENV_COMPAT"), 1)

            self.run_selector(config, "compat")
            self.assertEqual(
                config.read_text(encoding="utf-8"),
                "CONFIG_FIT=y\nCONFIG_ANTSDR_UENV_COMPAT=y\n",
            )


if __name__ == "__main__":
    unittest.main()
