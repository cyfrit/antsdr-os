# SPDX-License-Identifier: MIT
import sys
import yaml
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_workflows  # noqa: E402


class WorkflowPolicyTest(unittest.TestCase):
    def test_release_notes_configuration_has_fallback_category(self) -> None:
        config = yaml.safe_load((ROOT / ".github" / "release.yml").read_text(encoding="utf-8"))
        changelog = config["changelog"]
        categories = changelog["categories"]
        self.assertTrue(categories)
        self.assertEqual(categories[-1]["title"], "Other Changes")
        self.assertIn("*", categories[-1]["labels"])
        self.assertIn("skip-changelog", changelog["exclude"]["labels"])

    def test_all_workflows_follow_supply_chain_policy(self) -> None:
        paths = validate_workflows.workflow_files(ROOT)
        self.assertTrue(paths)
        for path in paths:
            validate_workflows.validate_workflow(path)

    def test_actions_require_full_commit_sha(self) -> None:
        self.assertTrue(validate_workflows.SHA_ACTION.fullmatch("actions/checkout@" + "0" * 40))
        self.assertFalse(validate_workflows.SHA_ACTION.fullmatch("actions/checkout@v4"))


if __name__ == "__main__":
    unittest.main()
