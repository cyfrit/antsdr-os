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

    def test_xdc_pins_are_unique_and_cover_contract(self) -> None:
        xdc = (PROJECT / "system_constr.xdc").read_text(encoding="utf-8")
        pins = re.findall(r"PACKAGE_PIN\s+([A-Z][0-9]+)", xdc)
        self.assertEqual(len(pins), len(set(pins)), "duplicate FPGA package pin")

        board = yaml.safe_load((ROOT / "boards" / "e310" / "board.yaml").read_text(encoding="utf-8"))
        contract_pins = {
            fact["fpga_pin"]
            for group in ("clocks", "gpios")
            for fact in board["hardware"][group]
            if "fpga_pin" in fact
        }
        self.assertFalse(contract_pins - set(pins), f"contract pins missing from XDC: {contract_pins - set(pins)}")

    def test_board_contract_matches_hdl_parameters(self) -> None:
        board = yaml.safe_load((ROOT / "boards" / "e310" / "board.yaml").read_text(encoding="utf-8"))
        block_design = (PROJECT / "system_bd.tcl").read_text(encoding="utf-8")
        project = (PROJECT / "system_project.tcl").read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
