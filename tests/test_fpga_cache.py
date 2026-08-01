# SPDX-License-Identifier: MIT
import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fpga_cache  # noqa: E402
from board_data import load_board  # noqa: E402


class FpgaCacheTest(unittest.TestCase):
    def identity(self, inventory: dict[str, str] | None = None) -> dict[str, object]:
        board = load_board("e310")
        commit = board["upstream"]["components"]["hdl"]["commit"]
        return fpga_cache.build_identity(
            board,
            ["Vivado v2023.2 (64-bit)", "SW Build 4029153"],
            inventory or {"project/system_top.v": "a" * 64},
            commit,
        )

    def create_artifacts(self, workspace: Path, bitstream: bytes = b"fpga-bitstream") -> None:
        paths = fpga_cache.artifact_paths(workspace)
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        paths["system_top.bit"].write_bytes(bitstream)
        with zipfile.ZipFile(paths["system_top.xsa"], "w") as archive:
            archive.writestr("system_top.bit", bitstream)
            archive.writestr("ps7_init.tcl", "set ps7 1\n")
        paths["timing_impl.log"].write_text("All user specified timing constraints are met.\n", encoding="ascii")

    def test_input_content_changes_the_cache_key(self) -> None:
        first = self.identity({"project/system_top.v": "a" * 64})
        second = self.identity({"project/system_top.v": "b" * 64})
        self.assertNotEqual(first["cache_key"], second["cache_key"])

    def test_hardware_contract_changes_the_cache_key(self) -> None:
        board = load_board("e310")
        changed = copy.deepcopy(board)
        changed["hardware"]["clocks"][0]["frequency_hz"] += 1
        commit = board["upstream"]["components"]["hdl"]["commit"]
        version = ["Vivado v2023.2 (64-bit)", "SW Build 4029153"]
        inventory = {"project/system_top.v": "a" * 64}
        first = fpga_cache.build_identity(board, version, inventory, commit)
        second = fpga_cache.build_identity(changed, version, inventory, commit)
        self.assertNotEqual(first["cache_key"], second["cache_key"])

    def test_declared_vivado_version_must_match_the_tool(self) -> None:
        board = load_board("e310")
        commit = board["upstream"]["components"]["hdl"]["commit"]
        with self.assertRaises(fpga_cache.FpgaCacheError):
            fpga_cache.build_identity(
                board,
                ["Vivado v2024.1 (64-bit)"],
                {"project/system_top.v": "a" * 64},
                commit,
            )

    def test_bundle_round_trip_restores_xsa_bitstream_and_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            bundle = root / "bundle"
            identity = self.identity()
            self.create_artifacts(workspace)

            fpga_cache.pack_bundle(workspace, bundle, identity)
            manifest = fpga_cache.validate_bundle(bundle, identity)
            self.assertEqual(manifest["timing_status"], "passed")

            for path in fpga_cache.artifact_paths(workspace).values():
                path.unlink()
            fpga_cache.restore_bundle(bundle, workspace, identity)
            self.assertEqual(
                fpga_cache.artifact_paths(workspace)["system_top.bit"].read_bytes(),
                b"fpga-bitstream",
            )

    def test_bundle_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            bundle = root / "bundle"
            identity = self.identity()
            self.create_artifacts(workspace)
            fpga_cache.pack_bundle(workspace, bundle, identity)
            (bundle / "system_top.bit").write_bytes(b"tampered")
            with self.assertRaises(fpga_cache.FpgaCacheError):
                fpga_cache.validate_bundle(bundle, identity)

    def test_metadata_records_cache_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / "build-metadata.json"
            metadata.write_text(json.dumps({"board": "e310"}), encoding="utf-8")
            identity = self.identity()
            fpga_cache.annotate_metadata(metadata, identity)
            value = json.loads(metadata.read_text(encoding="utf-8"))
            self.assertEqual(value["fpga"]["input_sha256"], identity["input_sha256"])


if __name__ == "__main__":
    unittest.main()
