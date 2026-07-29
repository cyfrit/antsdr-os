# SPDX-License-Identifier: MIT
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_workflows  # noqa: E402


class WorkflowPolicyTest(unittest.TestCase):
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
