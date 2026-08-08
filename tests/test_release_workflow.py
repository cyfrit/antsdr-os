# SPDX-License-Identifier: MIT
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_workflows  # noqa: E402


class ReleaseWorkflowTest(unittest.TestCase):
    def test_release_preflight_blocks_the_build_job(self) -> None:
        workflow = validate_workflows.load_workflow(ROOT / ".github" / "workflows" / "release.yml")
        jobs = workflow["jobs"]
        self.assertEqual(jobs["build"]["needs"], "preflight")
        commands = [
            step.get("run", "")
            for step in jobs["preflight"]["steps"]
            if isinstance(step, dict)
        ]
        self.assertTrue(
            any("release_metadata.py check --tag" in command for command in commands),
            "release preflight must validate the tag against antsdr-os.yaml",
        )

    def test_reusable_build_validates_version_before_expensive_host_setup(self) -> None:
        workflow = yaml.safe_load(
            (ROOT / ".github" / "workflows" / "build-e310.yml").read_text(encoding="utf-8")
        )
        steps = workflow["jobs"]["build"]["steps"]
        names = [step.get("name", "") for step in steps]
        version = names.index("Resolve version and source identity")
        host = names.index("Prepare hosted build host")
        toolchain = names.index("Restore AMD FPGA toolchain cache")
        self.assertLess(version, host)
        self.assertLess(version, toolchain)


if __name__ == "__main__":
    unittest.main()
