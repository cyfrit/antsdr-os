# SPDX-License-Identifier: MIT
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import compare_reproducibility  # noqa: E402
import generate_sbom  # noqa: E402
import package_release  # noqa: E402
import release_metadata  # noqa: E402
import verify_release  # noqa: E402
import write_checksums  # noqa: E402
from board_data import load_board, load_profiles  # noqa: E402


class ReleaseToolsTest(unittest.TestCase):
    CURRENT_VERSION = str(release_metadata.load_metadata()["product"]["version"])

    def _fixture(self, root: Path) -> Path:
        board = load_board("e310")
        profiles = load_profiles("e310")
        release = root / "release"
        release.mkdir()
        fit = release / "common" / "antsdr-e310.itb"
        fit.parent.mkdir(parents=True)
        fit.write_bytes(b"fit-image")
        (fit.parent / "BOOT.BIN").write_bytes(b"boot")
        firmware = board["build"]["firmware"]
        profile_records = []
        for profile in profiles:
            profile_id = profile["id"]
            profile_dir = release / "profiles" / profile_id
            profile_dir.mkdir(parents=True)
            (profile_dir / "uEnv.txt").write_text("rf_model=ad9361\nrf_topology=1r1t\n")
            boot = profile_dir / "qspi-boot.bin"
            boot.write_bytes(b"boot")
            with boot.open("r+b") as stream:
                stream.truncate(0x400000)
            environment = profile_dir / "qspi-extra-env.bin"
            environment.write_bytes(b"env")
            with environment.open("r+b") as stream:
                stream.truncate(0x1000)
            (profile_dir / "firmware-update.conf").write_text("version=1\n")
            profile_records.append(
                {
                    "id": profile_id,
                    "selection": profile["selection"],
                    "profile_directory": profile_dir.relative_to(release).as_posix(),
                    "fit_configuration": profile["artifacts"]["fit_configuration"],
                    "qspi_environment": environment.relative_to(release).as_posix(),
                    "qspi_boot_payload": boot.relative_to(release).as_posix(),
                    "qspi_firmware_payload": fit.relative_to(release).as_posix(),
                    "qspi_extra_environment_payload": environment.relative_to(release).as_posix(),
                }
            )
        files = {}
        for path in sorted(item for item in release.rglob("*") if item.is_file()):
            files[path.relative_to(release).as_posix()] = {
                "sha256": verify_release.sha256(path),
                "size_bytes": path.stat().st_size,
            }
        manifest = {
            "schema_version": 1,
            "board": "e310",
            "fit": {"filename": "antsdr-e310.itb", "signed": True, "hash": "sha256"},
            "qspi": {
                "boot_partition": "qspi-fsbl-uboot",
                "boot_offset": 0,
                "boot_size_bytes": 0x400000,
                "partition": "qspi-linux",
                "offset": 0x500000,
                "max_size_bytes": 0x1B00000,
                "artifact": "common/antsdr-e310.itb",
                "profile_environment_offset": 0x3FF000,
                "profile_environment_size_bytes": 0x1000,
            },
            "profiles": profile_records,
            "files": files,
        }
        (release / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        (release / "build-metadata.json").write_text(
            json.dumps(
                {
                    "board": "e310",
                    "os_name": "ANTSDR OS",
                    "os_version": self.CURRENT_VERSION,
                    "hardware_revision": "revc",
                    "adi_baseline": "v0.39",
                    "source_date_epoch": "0",
                }
            ),
            encoding="utf-8",
        )
        return release

    def test_release_inventory_and_supply_chain_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = self._fixture(root)
            verify_release.verify(release, "e310")
            sbom = generate_sbom.generate(release)
            self.assertEqual(sbom["spdxVersion"], "SPDX-2.3")
            self.assertGreater(len(sbom["files"]), 10)
            checksum = write_checksums.write_checksums(release)
            self.assertTrue(checksum.is_file())
            packages = package_release.package(release, root / "packages")
            self.assertEqual(len(packages), 4)
            self.assertEqual(
                {path.name for path in packages},
                {
                    f"antsdr-e310-revc-os-{self.CURRENT_VERSION}-adi-v0.39-ad9361-1r1t.zip",
                    f"antsdr-e310-revc-os-{self.CURRENT_VERSION}-adi-v0.39-ad9361-2r2t.zip",
                    f"antsdr-e310-revc-os-{self.CURRENT_VERSION}-adi-v0.39-ad9363-1r1t.zip",
                    f"antsdr-e310-revc-os-{self.CURRENT_VERSION}-adi-v0.39-ad9363-2r2t.zip",
                },
            )
            self.assertEqual(compare_reproducibility.compare(release, release), 0)
            shutil.copytree(release, root / "copy")
            (root / "copy" / "common" / "antsdr-e310.itb").write_bytes(b"changed")
            self.assertEqual(compare_reproducibility.compare(release, root / "copy"), 1)

    def test_packaging_rejects_a_version_outside_the_release_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = self._fixture(root)
            metadata_path = release / "build-metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["os_version"] = "999.0"
            metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
            with self.assertRaises(package_release.PackageError):
                package_release.package(release, root / "packages")


if __name__ == "__main__":
    unittest.main()
