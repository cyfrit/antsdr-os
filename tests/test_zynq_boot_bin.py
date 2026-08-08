# SPDX-License-Identifier: MIT
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import create_zynq_boot_bin  # noqa: E402
from test_hardware_cache import zynq_elf  # noqa: E402


class ZynqBootBinTest(unittest.TestCase):
    def test_assembly_uses_fsbl_bitstream_then_current_u_boot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fsbl = root / "input-fsbl.elf"
            bitstream = root / "input.bit"
            u_boot = root / "u-boot"
            bootgen = root / "bootgen"
            output = root / "output" / "BOOT.BIN"
            fsbl.write_bytes(zynq_elf())
            bitstream.write_bytes(b"bitstream")
            u_boot.write_bytes(b"u-boot")
            bootgen.write_bytes(b"host tool")
            observed: dict[str, object] = {}

            def fake_bootgen(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                staging = Path(str(kwargs["cwd"]))
                observed["command"] = command
                observed["bif"] = (staging / "zynq.bif").read_text(encoding="ascii")
                observed["fsbl"] = (staging / "fsbl.elf").read_bytes()
                observed["bitstream"] = (staging / "system_top.bit").read_bytes()
                observed["u_boot"] = (staging / "u-boot.elf").read_bytes()
                (staging / "BOOT.BIN").write_bytes(b"boot-image")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(create_zynq_boot_bin.subprocess, "run", side_effect=fake_bootgen):
                create_zynq_boot_bin.create_boot_image(fsbl, bitstream, u_boot, bootgen, output)

            self.assertEqual(output.read_bytes(), b"boot-image")
            self.assertEqual(
                observed["bif"],
                "the_ROM_image:\n{\n[bootloader] fsbl.elf\nsystem_top.bit\nu-boot.elf\n}\n",
            )
            self.assertEqual(observed["fsbl"], zynq_elf())
            self.assertEqual(observed["bitstream"], b"bitstream")
            self.assertEqual(observed["u_boot"], b"u-boot")
            self.assertEqual(observed["command"][1:], ["-image", "zynq.bif", "-w", "-o", "BOOT.BIN"])

    def test_invalid_fsbl_is_rejected_before_bootgen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("fsbl", "bitstream", "u-boot", "bootgen"):
                (root / name).write_bytes(b"not-an-elf")
            with self.assertRaises(create_zynq_boot_bin.HardwareCacheError):
                create_zynq_boot_bin.create_boot_image(
                    root / "fsbl",
                    root / "bitstream",
                    root / "u-boot",
                    root / "bootgen",
                    root / "BOOT.BIN",
                )


if __name__ == "__main__":
    unittest.main()
