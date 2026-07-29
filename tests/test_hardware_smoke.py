# SPDX-License-Identifier: MIT
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import e310_smoke_test  # noqa: E402


class HardwareSmokeTest(unittest.TestCase):
    def test_default_invocation_is_plan_only(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "e310_smoke_test.py")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TCP 10.31.0.1:22", result.stdout)
        self.assertIn("TCP 10.31.0.1:30431", result.stdout)
        self.assertIn("plan only", result.stdout)

    def test_remote_check_is_read_only(self) -> None:
        command = e310_smoke_test.REMOTE_SERVICE_CHECK
        self.assertIn("pidof iiod", command)
        for forbidden in ("fw_setenv", "reboot", "dfu", "iio_attr", "echo ", "> /sys", "dd "):
            self.assertNotIn(forbidden, command)

    def test_configuration_volume_uses_the_two_network_abis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.txt"
            config.write_text(
                "[USB_ETHERNET]\n"
                "ipaddr = 10.31.0.1\n"
                "ipaddr_host = 10.31.0.10\n"
                "netmask = 255.255.255.0\n"
                "[NETWORK]\n"
                "mode = dhcp\n"
                "ipaddr_eth =\n"
                "netmask_eth = 255.255.255.0\n",
                encoding="utf-8",
            )
            e310_smoke_test.check_config_volume(config)

            config.write_text("[USB_ETHERNET]\nipaddr = 10.31.0.1\n", encoding="utf-8")
            with self.assertRaises(e310_smoke_test.SmokeError):
                e310_smoke_test.check_config_volume(config)


if __name__ == "__main__":
    unittest.main()
