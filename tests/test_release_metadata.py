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
        self.assertEqual(payload["os_name"], "ANTSDR OS")
        self.assertEqual(payload["os_version"], "7.42")
        self.assertEqual(payload["board_stream"], "e310-revc")
        self.assertEqual(payload["adi_baseline"], "v0.39")
        self.assertEqual(payload["source_date_epoch"], "123")
        self.assertIn("-os-7.42-", payload["artifact_stem"])
        self.assertEqual(payload["release_tag"], "e310-revc-os-7.42")

    def test_release_tag_is_strictly_board_scoped(self) -> None:
        metadata = release_metadata.load_metadata()
        stream = metadata["supported_boards"][0]["stream"]
        version = metadata["product"]["version"]
        self.assertEqual(release_metadata.validate_tag(f"{stream}-os-{version}"), (stream, version))
        with self.assertRaises(release_metadata.ReleaseMetadataError):
            release_metadata.validate_tag(f"unsupported-os-{version}")
        with self.assertRaises(release_metadata.ReleaseMetadataError):
            release_metadata.validate_tag(f"{stream}-os-{version}.1")


if __name__ == "__main__":
    unittest.main()
