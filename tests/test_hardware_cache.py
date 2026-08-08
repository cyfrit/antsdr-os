# SPDX-License-Identifier: MIT
import copy
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import hardware_cache  # noqa: E402
from board_data import load_board  # noqa: E402


def zynq_elf() -> bytes:
    header = bytearray(52)
    header[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", header, 16, 2)
    struct.pack_into("<H", header, 18, 40)
    return bytes(header)


class HardwareCacheTest(unittest.TestCase):
    def identity(self, inventory: dict[str, str] | None = None) -> dict[str, object]:
        board = load_board("e310")
        return hardware_cache.build_identity(
            board,
            inventory or {"hw/fpga/project/system_top.v": "a" * 64},
            board["upstream"]["components"]["hdl"]["commit"],
            "b" * 64,
            {"ci/vivado/web-installer.env": "c" * 64},
        )

    def create_artifacts(self, workspace: Path, bitstream: bytes = b"fpga-bitstream") -> None:
        paths = hardware_cache.artifact_paths(workspace)
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        paths["system_top.bit"].write_bytes(bitstream)
        with zipfile.ZipFile(paths["system_top.xsa"], "w") as archive:
            archive.writestr("system_top.bit", bitstream)
            archive.writestr("ps7_init.tcl", "set ps7 1\n")
        paths["timing_impl.log"].write_text(
            "All user specified timing constraints are met.\n", encoding="ascii"
        )
        paths["fsbl.elf"].write_bytes(zynq_elf())

    def test_fpga_or_fsbl_input_changes_the_cache_key(self) -> None:
        first = self.identity({"hw/fpga/project/system_top.v": "a" * 64})
        second = self.identity({"hw/fpga/project/system_top.v": "b" * 64})
        self.assertNotEqual(first["cache_key"], second["cache_key"])

        board = load_board("e310")
        changed = copy.deepcopy(board)
        changed["toolchain"]["fsbl"]["version"] = "2024.1"
        third = hardware_cache.build_identity(
            changed,
            {"hw/fpga/project/system_top.v": "a" * 64},
            board["upstream"]["components"]["hdl"]["commit"],
            "b" * 64,
            {"ci/vivado/web-installer.env": "c" * 64},
        )
        self.assertNotEqual(first["cache_key"], third["cache_key"])

        fourth = hardware_cache.build_identity(
            board,
            {"hw/fpga/project/system_top.v": "a" * 64},
            board["upstream"]["components"]["hdl"]["commit"],
            "b" * 64,
            {"ci/vivado/web-installer.env": "d" * 64},
        )
        self.assertNotEqual(first["cache_key"], fourth["cache_key"])

    def test_bundle_round_trip_restores_fpga_and_fsbl_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            bundle = root / "bundle"
            identity = self.identity()
            self.create_artifacts(workspace)

            hardware_cache.pack_bundle(workspace, bundle, identity)
            manifest = hardware_cache.validate_bundle(bundle, identity)
            self.assertEqual(manifest["timing_status"], "passed")

            for path in hardware_cache.artifact_paths(workspace).values():
                path.unlink()
            hardware_cache.restore_bundle(bundle, workspace, identity)
            restored = hardware_cache.artifact_paths(workspace)
            self.assertEqual(restored["system_top.bit"].read_bytes(), b"fpga-bitstream")
            self.assertEqual(restored["fsbl.elf"].read_bytes(), zynq_elf())

    def test_bundle_rejects_a_tampered_fsbl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            bundle = root / "bundle"
            identity = self.identity()
            self.create_artifacts(workspace)
            hardware_cache.pack_bundle(workspace, bundle, identity)
            (bundle / "fsbl.elf").write_bytes(b"tampered")
            with self.assertRaises(hardware_cache.HardwareCacheError):
                hardware_cache.validate_bundle(bundle, identity)

    def test_metadata_records_fpga_and_fsbl_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / "build-metadata.json"
            metadata.write_text(json.dumps({"board": "e310"}), encoding="utf-8")
            identity = self.identity()
            hardware_cache.annotate_metadata(metadata, identity)
            value = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(value["hardware_build"]["input_sha256"], identity["input_sha256"])
            self.assertEqual(value["hardware_build"]["fsbl_version"], "2023.2")


if __name__ == "__main__":
    unittest.main()
