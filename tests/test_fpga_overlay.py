# SPDX-License-Identifier: MIT
import re
import subprocess
import sys
import tkinter
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
FPGA = ROOT / "boards" / "e310" / "hw" / "fpga"
PROJECT = FPGA / "project"


class FpgaOverlayTest(unittest.TestCase):
    def test_overlay_materializes_on_pinned_hdl(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "prepare_component.py"),
                "e310",
                "hdl",
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tcl_is_lexically_complete(self) -> None:
        interpreter = tkinter.Tcl()
        files = list(PROJECT.glob("*.tcl")) + list(FPGA.glob("library/**/*.tcl"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(path=path):
                self.assertEqual(
                    interpreter.call("info", "complete", path.read_text(encoding="utf-8")),
                    1,
                )

    def test_xdc_only_references_top_level_ports(self) -> None:
        top = (PROJECT / "system_top.v").read_text(encoding="utf-8")
        header = top.split(");", 1)[0]
        ports = set(
            re.findall(
                r"\b(?:input|output|inout)\s+(?:wire\s+|reg\s+)?(?:\[[^]]+\]\s+)?([A-Za-z_]\w*)",
                header,
            )
        )
        xdc = (PROJECT / "system_constr.xdc").read_text(encoding="utf-8")
        constrained = set(re.findall(r"get_ports\s+\{?([A-Za-z_]\w*)", xdc))
        self.assertFalse(constrained - ports, f"unknown constrained ports: {constrained - ports}")

    def test_xdc_exactly_matches_the_complete_pl_io_contract(self) -> None:
        xdc = (PROJECT / "system_constr.xdc").read_text(encoding="utf-8")
        pins = re.findall(r"PACKAGE_PIN\s+([A-Z][0-9]+)", xdc)
        self.assertEqual(len(pins), len(set(pins)), "duplicate FPGA package pin")

        board = yaml.safe_load((ROOT / "boards" / "e310" / "board.yaml").read_text(encoding="utf-8"))
        signals = board["hardware"]["pl_io"]["signals"]
        expected = {
            (signal["port"], signal.get("index")): (
                signal["package_pin"],
                signal["iostandard"],
                signal["pull"],
            )
            for signal in signals
        }
        self.assertEqual(len(expected), len(signals), "duplicate PL I/O contract entry")
        self.assertEqual(len(expected), 63, "unexpected E310 PL pin count")

        constrained: dict[tuple[str, int | None], tuple[str, str, str]] = {}
        pattern = re.compile(
            r"set_property -dict \{(?P<properties>[^}]+)\} "
            r"\[get_ports (?P<target>\{?[^}\s]+\}?)\]"
        )
        for match in pattern.finditer(xdc):
            target = match.group("target").strip("{}")
            target_match = re.fullmatch(r"([A-Za-z_]\w*)(?:\[(\d+)\])?", target)
            self.assertIsNotNone(target_match, target)
            assert target_match is not None
            port, index = target_match.groups()
            properties = match.group("properties").split()
            self.assertGreaterEqual(len(properties), 4, target)
            self.assertEqual(properties[0], "PACKAGE_PIN", target)
            self.assertEqual(properties[2], "IOSTANDARD", target)
            pull = "up" if properties[4:] == ["PULLUP", "true"] else "none"
            self.assertNotIn("PULLDOWN", properties, target)
            key = (port, int(index) if index is not None else None)
            self.assertNotIn(key, constrained, f"duplicate XDC port: {key}")
            constrained[key] = (properties[1], properties[3], pull)

        self.assertEqual(constrained, expected)

        top = (PROJECT / "system_top.v").read_text(encoding="utf-8")
        header = top.split(");", 1)[0]
        directions = {
            port: direction
            for direction, port in re.findall(
                r"\b(input|output|inout)\s+(?:\[[^]]+\]\s+)?([A-Za-z_]\w*)",
                header,
            )
        }
        pl_ports = {
            port
            for port in directions
            if not port.startswith("ddr_") and not port.startswith("fixed_io_")
        }
        self.assertEqual({signal["port"] for signal in signals}, pl_ports)
        for signal in signals:
            self.assertEqual(directions[signal["port"]], signal["direction"])

    def test_board_contract_matches_hdl_parameters(self) -> None:
        board = yaml.safe_load((ROOT / "boards" / "e310" / "board.yaml").read_text(encoding="utf-8"))
        block_design = (PROJECT / "system_bd.tcl").read_text(encoding="utf-8")
        project = (PROJECT / "system_project.tcl").read_text(encoding="utf-8")
        self.assertIn(
            "set_property is_enabled false [get_files *system_sys_ps7_0.xdc]",
            project,
        )

        soc = board["hardware"]["soc"]
        self.assertIn(
            f'xc7z020{soc["package"].lower()}{soc["speed_grade"]}',
            project,
        )
        ddr = board["hardware"]["ddr"]
        self.assertIn(ddr["memory_device"].replace("M16RE", "M16 RE"), block_design)
        self.assertIn(f'{{{ddr["data_width_bits"]} Bit}}', block_design)

        datapath = board["hardware"]["datapath"]
        for address in (
            datapath["ad936x_core_address"],
            datapath["rx_dma"]["address"],
            datapath["tx_dma"]["address"],
            datapath["vcxo_control_address"],
        ):
            self.assertIn(f"0x{address:08X}", block_design)

        vcxo = datapath["vcxo_control"]
        controller = (
            FPGA / "library" / "axi_e310_vcxo_ctrl" / "axi_e310_vcxo_ctrl.v"
        ).read_text(encoding="utf-8")
        regmap = (
            FPGA / "library" / "axi_e310_vcxo_ctrl" / "axi_e310_vcxo_ctrl_regmap.v"
        ).read_text(encoding="utf-8")
        self.assertEqual(vcxo["reset_mode"], "automatic")
        self.assertIn(f"HOLDOVER_DAC = 16'd{vcxo['automatic_holdover_dac_value']}", controller)
        self.assertIn(
            f"manual_dac <= 16'd{vcxo['manual_dac_register_reset_value']};",
            regmap,
        )

        top = (PROJECT / "system_top.v").read_text(encoding="utf-8")
        for gpio in board["hardware"]["gpios"]:
            if gpio["name"].endswith("-band"):
                self.assertIn(f"gpio_o[{gpio['emio']}]", top)

    def test_verilog_modules_are_balanced(self) -> None:
        files = list(PROJECT.glob("*.v")) + list(FPGA.glob("library/**/*.v"))
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertEqual(len(re.findall(r"\bmodule\b", text)), len(re.findall(r"\bendmodule\b", text)))
                self.assertIsNone(re.search(r"\bpl_gpio[0-9]*\b", text))
                self.assertIsNone(re.search(r"\bclk_out\b", text))

    def test_ltc2630_tracks_the_value_actually_transmitted(self) -> None:
        source = (
            FPGA / "library" / "axi_e310_vcxo_ctrl" / "ltc2630_spi.v"
        ).read_text(encoding="utf-8")
        self.assertIn("transfer_value <= value;", source)
        self.assertIn("last_value <= transfer_value;", source)
        self.assertNotIn("last_value <= value;", source)

    def test_vcxo_cdc_uses_mailboxes_and_local_reset_release(self) -> None:
        controller = (
            FPGA / "library" / "axi_e310_vcxo_ctrl" / "axi_e310_vcxo_ctrl.v"
        ).read_text(encoding="utf-8")
        regmap = (
            FPGA
            / "library"
            / "axi_e310_vcxo_ctrl"
            / "axi_e310_vcxo_ctrl_regmap.v"
        ).read_text(encoding="utf-8")
        reference_pll = (
            FPGA / "library" / "axi_e310_vcxo_ctrl" / "e310_ref_pll.v"
        ).read_text(encoding="utf-8")
        xdc = (PROJECT / "system_constr.xdc").read_text(encoding="utf-8")

        self.assertIn("control_mailbox_axi", controller)
        self.assertIn("control_request_axi", controller)
        self.assertIn("control_ack_200m", controller)
        self.assertIn("status_mailbox_200m", controller)
        self.assertIn("status_request_200m", controller)
        self.assertIn("status_ack_axi", controller)
        self.assertIn("vcxo_reset_release", controller)
        self.assertIn("always @(posedge clk_200m or posedge vcxo_reset)", controller)
        self.assertIn("reference_reset_release", reference_pll)
        self.assertIn("always @(posedge reference_clock or posedge reference_reset)", reference_pll)
        self.assertIn("} <= control_bus_sync;", controller)
        self.assertIn("active_dac_axi <= status_bus_sync[18:3];", controller)
        self.assertNotIn("control_update", controller)
        self.assertNotIn("active_dac_sync", controller)
                
        for endpoint in (
            "external_reference_sync",
            "control_bus_meta",
            "control_request_sync",
            "control_ack_sync",
            "status_bus_meta",
            "status_request_sync",
            "status_ack_sync",
            "vcxo_reset_release",
            "reference_reset_release",
        ):
            self.assertIn(endpoint, xdc)


if __name__ == "__main__":
    unittest.main()
