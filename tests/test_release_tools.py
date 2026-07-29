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
import verify_release  # noqa: E402
import write_checksums  # noqa: E402
from board_data import load_board, load_profiles  # noqa: E402


class ReleaseToolsTest(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        board = load_board("e310")
        profiles = load_profiles("e310")
        release = root / "release"
        release.mkdir()
        fit = release / "qspi" / "antsdr-e310.itb"
        fit.parent.mkdir(parents=True)
        fit.write_bytes(b"fit-image")
        firmware = board["build"]["firmware"]
        profile_records = []
        for profile in profiles:
            profile_id = profile["id"]
            sd = release / "sd" / profile_id
            sd.mkdir(parents=True)
            (sd / firmware["boot_image"]).write_bytes(b"boot")
            (sd / firmware["fit_image"]).write_bytes(b"fit")
            qspi = release / "qspi" / "profiles" / profile_id
            qspi.mkdir(parents=True)
            boot = qspi / "boot.dfu"
            boot.write_bytes(b"boot")
            with boot.open("r+b") as stream:
                stream.truncate(0x100000)
            environment = qspi / "extra-env.bin"
            environment.write_bytes(b"env")
            with environment.open("r+b") as stream:
                stream.truncate(0x1000)
            (qspi / "firmware.dfu").write_bytes(b"firmware")
            (qspi / "uboot-extra-env.dfu").write_bytes(b"env")
            profile_records.append(
                {
                    "id": profile_id,
                    "selection": profile["selection"],
                    "sd_directory": sd.relative_to(release).as_posix(),
                    "fit_configuration": profile["artifacts"]["fit_configuration"],
                    "qspi_environment": environment.relative_to(release).as_posix(),
                    "qspi_boot_payload": boot.relative_to(release).as_posix(),
                    "qspi_firmware_payload": (qspi / "firmware.dfu").relative_to(release).as_posix(),
                    "qspi_extra_environment_payload": (qspi / "uboot-extra-env.dfu").relative_to(release).as_posix(),
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
            "fit": {"filename": "antsdr-e310.itb", "signed": False, "hash": "sha256"},
            "qspi": {
                "boot_partition": "qspi-fsbl-uboot",
                "boot_offset": 0,
                "boot_size_bytes": 0x100000,
                "partition": "qspi-linux",
                "offset": 0x200000,
                "max_size_bytes": 0x1E00000,
                "artifact": "qspi/antsdr-e310.itb",
                "profile_environment_offset": 0xFF000,
                "profile_environment_size_bytes": 0x1000,
            },
            "profiles": profile_records,
            "files": files,
        }
        (release / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        (release / "build-metadata.json").write_text(
            json.dumps({"board": "e310", "os_name": "ANTSDR OS", "source_date_epoch": "0"}),
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
            self.assertEqual(compare_reproducibility.compare(release, release), 0)
            shutil.copytree(release, root / "copy")
            (root / "copy" / "qspi" / "antsdr-e310.itb").write_bytes(b"changed")
            self.assertEqual(compare_reproducibility.compare(release, root / "copy"), 1)


if __name__ == "__main__":
    unittest.main()
