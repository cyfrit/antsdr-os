# SPDX-License-Identifier: MIT
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CACHE_SCRIPT = ROOT / "ci" / "vivado" / "toolchain-cache.sh"
HAS_CACHE_TOOLS = os.name != "nt" and all(
    shutil.which(tool) for tool in ("bash", "split", "tar", "zstd")
)


@unittest.skipUnless(HAS_CACHE_TOOLS, "Linux cache tools are required")
class VivadoToolchainCacheTest(unittest.TestCase):
    def create_toolchain(self, root: Path) -> bytes:
        binaries = (
            root / "Vitis" / "2023.2" / "bin" / "xsct",
            root / "Vivado" / "2023.2" / "bin" / "vivado",
            root / "Vivado" / "2023.2" / "bin" / "bootgen",
        )
        for binary in binaries:
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            binary.chmod(0o755)

        settings = root / "Vitis" / "2023.2" / "settings64.sh"
        settings.write_text("export XILINX_VITIS=/cached\n", encoding="ascii")

        payload = os.urandom(2_500_000)
        shared = root / "shared" / "payload.bin"
        shared.parent.mkdir(parents=True)
        shared.write_bytes(payload)
        (root / "shared-link").symlink_to(Path("shared") / "payload.bin")
        return payload

    def run_cache(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["ANTSDR_CACHE_PART_SIZE"] = "1M"
        return subprocess.run(
            ["bash", str(CACHE_SCRIPT), *arguments],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_complete_install_root_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            toolchain = base / "Xilinx"
            cache = base / "cache"
            payload = self.create_toolchain(toolchain)

            packed = self.run_cache("pack", str(toolchain), str(cache), "123")
            self.assertEqual(packed.returncode, 0, packed.stderr)
            self.assertEqual(len(list((cache / "parts").glob("part-*"))), 4)

            shutil.rmtree(toolchain)
            restored = self.run_cache("restore", str(toolchain), str(cache))
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertEqual((toolchain / "shared" / "payload.bin").read_bytes(), payload)
            self.assertTrue((toolchain / "shared-link").is_symlink())
            mode = (toolchain / "Vivado" / "2023.2" / "bin" / "vivado").stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR)

    def test_corrupt_part_is_rejected_before_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            toolchain = base / "Xilinx"
            cache = base / "cache"
            self.create_toolchain(toolchain)
            packed = self.run_cache("pack", str(toolchain), str(cache), "456")
            self.assertEqual(packed.returncode, 0, packed.stderr)

            shutil.rmtree(toolchain)
            toolchain.mkdir()
            sentinel = toolchain / "sentinel"
            sentinel.write_text("keep", encoding="ascii")
            with (cache / "parts" / "part-00").open("ab") as part:
                part.write(b"corrupt")

            restored = self.run_cache("restore", str(toolchain), str(cache))
            self.assertNotEqual(restored.returncode, 0)
            self.assertEqual(sentinel.read_text(encoding="ascii"), "keep")


if __name__ == "__main__":
    unittest.main()
