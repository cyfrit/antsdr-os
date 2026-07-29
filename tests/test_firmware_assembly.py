# SPDX-License-Identifier: MIT
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import assemble_e310  # noqa: E402


class FirmwareAssemblyTest(unittest.TestCase):
    def test_assembly_creates_sd_profiles_qspi_fit_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            inputs = temporary / "inputs"
            inputs.mkdir()
            kernel = inputs / "zImage"
            rootfs = inputs / "rootfs.cpio.gz"
            bitstream = inputs / "system_top.bit"
            boot_bin = inputs / "BOOT.BIN"
            mkimage = inputs / "mkimage"
            for path in (kernel, rootfs, bitstream, boot_bin, mkimage):
                path.write_bytes(path.name.encode("ascii"))

            dtb_dir = inputs / "dtbs"
            dtb_dir.mkdir()
            board, profiles = assemble_e310.load_board()
            for profile in profiles:
                (dtb_dir / profile["artifacts"]["linux_dtb"]).write_bytes(profile["id"].encode("ascii"))

            output = temporary / "release"
            commands: list[tuple[list[str], Path]] = []

            def runner(command: list[str], cwd: Path) -> None:
                commands.append((command, cwd))
                self.assertEqual(command[1:3], ["-f", "antsdr-e310.its"])
                Path(command[3]).write_bytes(b"FIT")

            assembled = assemble_e310.build_release(
                assemble_e310.AssemblyInputs(
                    kernel=kernel,
                    rootfs=rootfs,
                    bitstream=bitstream,
                    dtb_dir=dtb_dir,
                    boot_bin=boot_bin,
                    output=output,
                    mkimage=mkimage,
                ),
                runner=runner,
            )
            self.assertEqual(assembled, output)
            self.assertEqual(len(commands), 1)
            self.assertTrue((output / "qspi" / "antsdr-e310.itb").is_file())

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["board"], "e310")
            self.assertFalse(manifest["fit"]["signed"])
            self.assertEqual(manifest["qspi"]["partition"], "qspi-linux")
            self.assertEqual(len(manifest["profiles"]), 4)
            self.assertIn("qspi/antsdr-e310.itb", manifest["files"])

            for profile in profiles:
                directory = output / "sd" / profile["id"]
                self.assertTrue((directory / "BOOT.BIN").is_file())
                self.assertTrue((directory / "antsdr-e310.itb").is_file())
                self.assertEqual(
                    (directory / "uEnv.txt").read_text(encoding="ascii"),
                    f"rf_model={profile['selection']['rf_model']}\n"
                    f"rf_topology={profile['selection']['rf_topology']}\n",
                )

    def test_output_inside_repository_is_rejected(self) -> None:
        with self.assertRaises(assemble_e310.AssemblyError):
            assemble_e310.ensure_external_output(ROOT / "build" / "release")


if __name__ == "__main__":
    unittest.main()
