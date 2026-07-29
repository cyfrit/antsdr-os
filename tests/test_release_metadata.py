# SPDX-License-Identifier: MIT
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import release_metadata  # noqa: E402


class ReleaseMetadataTest(unittest.TestCase):
    def test_public_version_is_debian_style(self) -> None:
        data = release_metadata.load_metadata()
        self.assertEqual(data["product"]["version"], "1.0")
        self.assertEqual(data["product"]["major"], 1)
        self.assertEqual(data["product"]["point"], 1)

    def test_build_metadata_separates_board_and_upstream_coordinates(self) -> None:
        payload = release_metadata.build_metadata(
            "e310",
            git_sha="0" * 40,
            source_date_epoch="123",
        )
        self.assertEqual(payload["os_name"], "ANTSDR OS")
        self.assertEqual(payload["os_version"], "1.0")
        self.assertEqual(payload["board_stream"], "e310-revc")
        self.assertEqual(payload["adi_baseline"], "v0.39")
        self.assertEqual(payload["source_date_epoch"], "123")
        self.assertTrue(payload["artifact_stem"].startswith("antsdr-e310-revc-os-1.0"))

    def test_release_tag_is_strictly_board_scoped(self) -> None:
        self.assertEqual(release_metadata.validate_tag("e310-revc-os-1.0"), ("e310-revc", "1.0"))
        with self.assertRaises(release_metadata.ReleaseMetadataError):
            release_metadata.validate_tag("e310-os-1.0")
        with self.assertRaises(release_metadata.ReleaseMetadataError):
            release_metadata.validate_tag("e310-revc-os-1.0.1")


if __name__ == "__main__":
    unittest.main()
