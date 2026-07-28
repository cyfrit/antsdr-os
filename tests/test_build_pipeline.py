# SPDX-License-Identifier: MIT
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "tools" / "e310_build.py"


class BuildPipelineTest(unittest.TestCase):
    def test_plan_is_read_only_and_covers_the_delivery_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "e310-workspace"
            result = subprocess.run(
                [sys.executable, str(PIPELINE), "plan", "--workspace", str(workspace)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(workspace.exists())
            self.assertIn("materialize buildroot", result.stdout)
            self.assertIn("build Buildroot rootfs", result.stdout)
            self.assertIn("build Linux kernel and DTBs", result.stdout)
            self.assertIn("build U-Boot and mkimage", result.stdout)
            self.assertIn("build FPGA project", result.stdout)
            self.assertIn("create FSBL and BOOT.BIN", result.stdout)
            self.assertIn("UIMAGE_LOADADDR=0x00008000", result.stdout)

    def test_pipeline_refuses_a_workspace_inside_the_repository(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PIPELINE), "plan", "--workspace", str(ROOT / "build" / "forbidden")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside this repository", result.stderr)


if __name__ == "__main__":
    unittest.main()
