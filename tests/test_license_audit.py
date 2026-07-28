# SPDX-License-Identifier: MIT
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import license_audit  # noqa: E402


class LicenseExpressionTest(unittest.TestCase):
    def test_compound_expression(self) -> None:
        licenses, exceptions = license_audit.parse_expression(
            "GPL-2.0-or-later OR (MIT AND BSD-2-Clause)"
        )
        self.assertEqual(licenses, ["GPL-2.0-or-later", "MIT", "BSD-2-Clause"])
        self.assertEqual(exceptions, [])

    def test_rejects_incomplete_expression(self) -> None:
        with self.assertRaises(license_audit.ExpressionError):
            license_audit.parse_expression("MIT OR")

    def test_with_cannot_apply_to_group(self) -> None:
        with self.assertRaises(license_audit.ExpressionError):
            license_audit.parse_expression("(MIT OR BSD-2-Clause) WITH Test-exception")


class LicenseAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = license_audit.LicensePolicy(ROOT / "license-policy.yaml")
        cls.result = license_audit.LicenseAuditor(ROOT, cls.policy).scan()

    def test_repository_has_no_license_errors(self) -> None:
        self.assertEqual(self.result.errors(), [])

    def test_contributor_identity_has_no_placeholder(self) -> None:
        matches = []
        placeholder = "ANTSDR Firmware " + "contributors"
        for mode, relative in license_audit.git_entries(ROOT):
            if mode == "160000" or relative.startswith("LICENSES/"):
                continue
            path = ROOT / relative
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn(placeholder, text, relative)
            if "Cyfrit <i@cli.tf>" in text:
                matches.append(relative)
        self.assertGreaterEqual(len(matches), 10)

    def test_adi_license_ref_is_recognized(self) -> None:
        record = next(
            item
            for item in self.result.records
            if item.path == "boards/e310/hw/fpga/project/system_bd.tcl"
        )
        self.assertEqual(record.expression, "LicenseRef-ADI-BSD")
        self.assertEqual(record.source, "spdx-header")
        self.assertTrue(record.contains_non_osi)

    def test_legacy_alias_is_preserved_for_old_sources(self) -> None:
        self.assertEqual(
            self.policy.legacy_identifiers["ADIBSD"],
            "LicenseRef-ADI-BSD",
        )

    def test_inventory_is_machine_readable(self) -> None:
        payload = license_audit.result_payload(self.result, self.policy)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertGreater(payload["summary"]["files"], 0)

    def test_header_command_is_preview_only_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.py"
            path.write_text("print('example')\n", encoding="utf-8")
            preview = license_audit.add_header(path, "MIT", None, apply=False)
            self.assertTrue(preview.startswith("# SPDX-License-Identifier: MIT\n"))
            self.assertEqual(path.read_text(encoding="utf-8"), "print('example')\n")

    def test_patch_header_preserves_mail_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.patch"
            path.write_text("From: Example\nSubject: [PATCH] example\n\ndiff --git a/a b/a\n", encoding="utf-8")
            preview = license_audit.add_header(path, "GPL-2.0-only", None, apply=False)
            self.assertIn(
                "Subject: [PATCH] example\nSPDX-License-Identifier: GPL-2.0-only\n\n",
                preview,
            )


if __name__ == "__main__":
    unittest.main()
