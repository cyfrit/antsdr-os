# SPDX-License-Identifier: MIT
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "boards" / "e310"
LINUX = BOARD / "hw" / "linux"
DTS = LINUX / "dts" / "zynq-antsdr-e310.dts"
DTSI = LINUX / "dts" / "zynq-antsdr-e310.dtsi"
DEFCONFIG = LINUX / "configs" / "zynq_antsdr_e310_defconfig"
UPSTREAM = ROOT / "upstream" / "adi-plutosdr-fw" / "linux"


class LinuxOverlayTest(unittest.TestCase):
    def test_overlay_materializes_on_pinned_linux(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "prepare_component.py"),
                "e310",
                "linux",
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_defconfig_enables_e310_hardware(self) -> None:
        config = DEFCONFIG.read_text(encoding="utf-8").splitlines()
        enabled = {line.removeprefix("CONFIG_").split("=", 1)[0] for line in config if line.startswith("CONFIG_")}
        required = {
            "AD9361",
            "AD9361_EXT_BAND_CONTROL",
            "ANTSDR_E310_VCXO_CTRL",
            "AXI_DMAC",
            "CF_AXI_DDS",
            "CF_AXI_TDD",
            "MACB",
            "MARVELL_PHY",
            "MMC_SDHCI_OF_ARASAN",
            "USB_CHIPIDEA",
            "USB_GADGET",
            "USB_ULPI",
        }
        self.assertFalse(required - enabled, f"missing kernel options: {required - enabled}")

        symbols = [
            match.group(1)
            for line in config
            if (match := re.match(r"(?:# )?CONFIG_([A-Z0-9_]+)", line))
        ]
        duplicates = {symbol for symbol in symbols if symbols.count(symbol) > 1}
        self.assertFalse(duplicates, f"duplicate kernel options: {duplicates}")

    def test_device_tree_matches_board_contract(self) -> None:
        board = yaml.safe_load((BOARD / "board.yaml").read_text(encoding="utf-8"))
        dtsi = DTSI.read_text(encoding="utf-8")
        gpio_lines = {entry["name"]: entry["line"] for entry in board["hardware"]["gpios"]}

        self.assertIn('compatible = "adi,ad9361";', dtsi)
        self.assertNotIn('compatible = "adi,ad9363a";', dtsi)
        self.assertIn("adi,2rx-2tx-mode-enable;", dtsi)
        self.assertIn("adi,tx-lo-powerdown-managed-enable;", dtsi)
        self.assertIn(
            f'reset-gpios = <&gpio0 {gpio_lines["ethernet-phy-reset"]} GPIO_ACTIVE_LOW>;',
            dtsi,
        )
        self.assertIn(
            f'reset-gpios = <&gpio0 {gpio_lines["ad936x-reset"]} GPIO_ACTIVE_HIGH>;',
            dtsi,
        )

        datapath = board["hardware"]["datapath"]
        for address in (
            datapath["ad936x_core_address"],
            datapath["rx_dma"]["address"],
            datapath["tx_dma"]["address"],
            datapath["vcxo_control_address"],
        ):
            self.assertIn(f"@{address:x}", dtsi)

    def test_vcxo_driver_uses_managed_resources(self) -> None:
        driver = (LINUX / "drivers" / "antsdr-e310-vcxo.c").read_text(encoding="utf-8")
        self.assertIn("devm_platform_ioremap_resource(pdev, 0)", driver)
        self.assertIn("devm_iio_device_register(&pdev->dev, indio_dev)", driver)
        self.assertNotIn("0x43c00000", driver.lower())

    @unittest.skipUnless(shutil.which("cpp") and shutil.which("dtc"), "cpp and dtc are required")
    def test_device_tree_compiles(self) -> None:
        self.assertTrue((UPSTREAM / "arch" / "arm" / "boot" / "dts" / "zynq.dtsi").is_file())
        with tempfile.TemporaryDirectory() as directory:
            preprocessed = Path(directory) / "zynq-antsdr-e310.dts"
            dtb = Path(directory) / "zynq-antsdr-e310.dtb"
            preprocess = subprocess.run(
                [
                    "cpp",
                    "-nostdinc",
                    "-undef",
                    "-D__DTS__",
                    "-x",
                    "assembler-with-cpp",
                    "-I",
                    str(LINUX / "dts"),
                    "-I",
                    str(UPSTREAM / "arch" / "arm" / "boot" / "dts"),
                    "-I",
                    str(UPSTREAM / "include"),
                    str(DTS),
                    str(preprocessed),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(preprocess.returncode, 0, preprocess.stderr)
            compile_dtb = subprocess.run(
                ["dtc", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(preprocessed)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_dtb.returncode, 0, compile_dtb.stderr)
            self.assertGreater(dtb.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
