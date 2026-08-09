# SPDX-License-Identifier: MIT
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import release_metadata  # noqa: E402


class ReleaseMetadataTest(unittest.TestCase):
    def test_build_metadata_separates_board_and_upstream_coordinates(self) -> None:
        payload = release_metadata.build_metadata(
            "e310",
            git_sha="0" * 40,
            source_date_epoch="123",
            version="7.42",
        )
        self.assertEqual(payload["os_name"], "AntSDR OS")
        self.assertEqual(payload["os_version"], "7.42")
        self.assertEqual(payload["hardware_target"], "e310-revc")
        self.assertEqual(payload["adi_baseline"], "v0.39")
        self.assertEqual(payload["source_date_epoch"], "123")
        self.assertTrue(payload["artifact_stem"].startswith("antsdr-os-7.42-"))
        self.assertEqual(payload["release_tag"], "antsdr-os-7.42")

    def test_release_tag_is_strictly_os_scoped(self) -> None:
        metadata = release_metadata.load_metadata()
        version = metadata["product"]["version"]
        tag = f"antsdr-os-{version}"
        self.assertEqual(release_metadata.validate_tag(tag), version)


if __name__ == "__main__":
    unittest.main()
