import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BoardContractTest(unittest.TestCase):
    def test_all_board_contracts(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "validate_boards.py")],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
