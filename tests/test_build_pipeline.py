# SPDX-License-Identifier: MIT
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "tools" / "e310_build.py"
sys.path.insert(0, str(ROOT / "tools"))
import e310_build  # noqa: E402


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
            self.assertIn("select U-Boot uEnv mode", result.stdout)
            self.assertIn("build FPGA project", result.stdout)
            self.assertIn("create FSBL and BOOT.BIN", result.stdout)
            self.assertIn("assemble SD and QSPI delivery artifacts", result.stdout)
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

    def test_buildroot_toolchain_is_used_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            host_bin = workspace / "out" / "buildroot" / "host" / "bin"
            host_bin.mkdir(parents=True)
            environment = e310_build.build_environment(workspace)
            self.assertEqual(environment["PATH"].split(e310_build.os.pathsep)[0], str(host_bin))


if __name__ == "__main__":
    unittest.main()
