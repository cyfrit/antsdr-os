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
DTSI = LINUX / "dts" / "zynq-antsdr-e310.dtsi"
DEFCONFIG = LINUX / "configs" / "zynq_antsdr_e310_defconfig"
UPSTREAM = ROOT / "upstream" / "adi-plutosdr-fw" / "linux"
DTBS = {
    "ad9363-1r1t": (
        LINUX / "dts" / "zynq-antsdr-e310-ad9363-1r1t.dts",
        "adi,ad9363a",
        "1r1t",
    ),
    "ad9363-2r2t": (
        LINUX / "dts" / "zynq-antsdr-e310-ad9363-2r2t.dts",
        "adi,ad9363a",
        "2r2t",
    ),
    "ad9361-1r1t": (
        LINUX / "dts" / "zynq-antsdr-e310-ad9361-1r1t.dts",
        "adi,ad9361",
        "1r1t",
    ),
    "ad9361-2r2t": (
        LINUX / "dts" / "zynq-antsdr-e310-ad9361-2r2t.dts",
        "adi,ad9361",
        "2r2t",
    ),
}


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
            "ADI_AXI_TDD",
            "ANTSDR_E310_VCXO_CTRL",
            "AXI_DMAC",
            "CF_AXI_DDS",
            "MACB",
            "MARVELL_PHY",
            "MMC_SDHCI_OF_ARASAN",
            "USB_CHIPIDEA",
            "USB_GADGET",
            "USB_ULPI",
        }
        self.assertFalse(required - enabled, f"missing kernel options: {required - enabled}")

        self.assertIn("# CONFIG_SENSORS_JC42 is not set", config)
        self.assertIn("# CONFIG_SENSORS_IIO_HWMON is not set", config)
        for disabled in (
            "# CONFIG_CF_AXI_TDD is not set",
            "# CONFIG_CFG80211 is not set",
            "# CONFIG_MODULES is not set",
            "# CONFIG_SUSPEND is not set",
            "# CONFIG_WLAN is not set",
        ):
            self.assertIn(disabled, config)
        self.assertFalse(
            [line for line in config if line.endswith("=m")],
            "the initramfs build does not install loadable kernel modules",
        )

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
        dtbs = {
            "ad9363-1r1t": (
                LINUX / "dts" / "zynq-antsdr-e310-ad9363-1r1t.dts",
                "adi,ad9363a",
                "1r1t",
            ),
            "ad9363-2r2t": (
                LINUX / "dts" / "zynq-antsdr-e310-ad9363-2r2t.dts",
                "adi,ad9363a",
                "2r2t",
            ),
            "ad9361-1r1t": (
                LINUX / "dts" / "zynq-antsdr-e310-ad9361-1r1t.dts",
                "adi,ad9361",
                "1r1t",
            ),
            "ad9361-2r2t": (
                LINUX / "dts" / "zynq-antsdr-e310-ad9361-2r2t.dts",
                "adi,ad9361",
                "2r2t",
            ),
        }
        gpio_lines = {entry["name"]: entry["line"] for entry in board["hardware"]["gpios"]}

        dimensions = board["build"]["profile_selection"]["dimensions"]
        self.assertEqual(dimensions["rf_model"], ["ad9363", "ad9361"])
        self.assertEqual(dimensions["rf_topology"], ["1r1t", "2r2t"])
        self.assertEqual(
            set(board["build"]["linux_dtbs"]),
            {path.with_suffix(".dtb").name for path, _, _ in dtbs.values()},
        )
        self.assertIn("ad936x_phy: ad936x-phy@0", dtsi)
        self.assertNotIn('compatible = "adi,ad936', dtsi)
        self.assertNotIn("adi,2rx-2tx-mode-enable;", dtsi)
        self.assertIn("adi,tx-lo-powerdown-managed-enable;", dtsi)
        self.assertIn(
            f'reset-gpios = <&gpio0 {gpio_lines["ethernet-phy-reset"]} GPIO_ACTIVE_LOW>;',
            dtsi,
        )
        self.assertIn(
            f'reset-gpios = <&gpio0 {gpio_lines["ad936x-reset"]} GPIO_ACTIVE_HIGH>;',
            dtsi,
        )
        self.assertIn(
            f'xlnx,phy-reset-gpio = <&gpio0 {gpio_lines["usb-phy-reset"]} GPIO_ACTIVE_LOW>;',
            dtsi,
        )
        self.assertIn('compatible = "adi,axi-tdd";', dtsi)
        self.assertNotIn('compatible = "adi,axi-tdd-1.00";', dtsi)
        self.assertIn('compatible = "adi,iio-fake-platform-device";', dtsi)
        self.assertIn("adi,faked-dev = <&axi_tdd>;", dtsi)

        datapath = board["hardware"]["datapath"]
        for address in (
            datapath["ad936x_core_address"],
            datapath["rx_dma"]["address"],
            datapath["tx_dma"]["address"],
            datapath["vcxo_control_address"],
        ):
            self.assertIn(f"@{address:x}", dtsi)

        for profile_path in sorted((BOARD / "profiles").glob("*.yaml")):
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            with self.subTest(profile=profile["id"]):
                self.assertEqual(
                    profile["transceiver"]["physical_marking"],
                    profile["selection"]["rf_model"].upper(),
                )
                self.assertIn(profile["id"], dtbs)
                dts_path, compatible, topology = dtbs[profile["id"]]
                self.assertEqual(profile["artifacts"]["linux_dtb"], dts_path.with_suffix(".dtb").name)
                self.assertEqual(profile["selection"]["rf_topology"], topology)
                self.assertEqual(profile["datapath"]["mode"], topology)
                self.assertEqual(profile["artifacts"]["fpga_bitstream"], "system_top.bit")
                dts = dts_path.read_text(encoding="utf-8")
                self.assertIn(f'compatible = "{compatible}";', dts)
                if topology == "2r2t":
                    self.assertIn("adi,2rx-2tx-mode-enable;", dts)
                    self.assertNotIn("adi,axi-ad9364-dds-6.00.a", dts)
                else:
                    self.assertNotIn("adi,2rx-2tx-mode-enable;", dts)
                    self.assertIn("adi,1rx-1tx-mode-use-rx-num = <1>;", dts)
                    self.assertIn("adi,1rx-1tx-mode-use-tx-num = <1>;", dts)
                    self.assertIn('compatible = "adi,axi-ad9364-dds-6.00.a";', dts)

    def test_vcxo_driver_uses_managed_resources(self) -> None:
        driver = (LINUX / "drivers" / "antsdr-e310-vcxo.c").read_text(encoding="utf-8")
        self.assertIn("devm_platform_ioremap_resource(pdev, 0)", driver)
        self.assertIn("devm_iio_device_register(&pdev->dev, indio_dev)", driver)
        self.assertIn("E310_VCXO_CORE_VERSION", driver)
        self.assertNotIn("writel(", driver[driver.index("e310_vcxo_probe"):])
        self.assertNotIn("0x43c00000", driver.lower())

    @unittest.skipUnless(shutil.which("cpp") and shutil.which("dtc"), "cpp and dtc are required")
    def test_device_tree_compiles(self) -> None:
        self.assertTrue((UPSTREAM / "arch" / "arm" / "boot" / "dts" / "zynq.dtsi").is_file())
        with tempfile.TemporaryDirectory() as directory:
            for source, _, _ in DTBS.values():
                with self.subTest(source=source.name):
                    preprocessed = Path(directory) / source.name
                    dtb = Path(directory) / source.with_suffix(".dtb").name
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
                            str(source),
                            str(preprocessed),
                        ],
                        cwd=ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(preprocess.returncode, 0, preprocess.stderr)
                    compile_dtb = subprocess.run(
                        [
                            "dtc",
                            "-i",
                            str(LINUX / "dts"),
                            "-i",
                            str(UPSTREAM / "arch" / "arm" / "boot" / "dts"),
                            "-I",
                            "dts",
                            "-O",
                            "dtb",
                            "-o",
                            str(dtb),
                            str(preprocessed),
                        ],
                        cwd=ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(compile_dtb.returncode, 0, compile_dtb.stderr)
                    self.assertGreater(dtb.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
