# SPDX-License-Identifier: MIT
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_fit_profiles  # noqa: E402


class FitProfileVerificationTest(unittest.TestCase):
    def test_default_runner_filters_known_host_gzip_warning(self) -> None:
        original = verify_fit_profiles.subprocess.run
        calls = []

        class Result:
            returncode = 0
            stdout = "sha256+\n"
            stderr = "Unimplemented compression type 1\nSignature check OK\n"

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return Result()

        verify_fit_profiles.subprocess.run = fake_run
        try:
            verify_fit_profiles.default_runner(["fit_check_sign"])
        finally:
            verify_fit_profiles.subprocess.run = original
        self.assertEqual(calls[0][1]["capture_output"], True)
        self.assertEqual(calls[0][1]["text"], True)

    def test_each_profile_is_verified_with_a_disposable_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fit = temporary / "antsdr-e310.itb"
            control_dtb = temporary / "dt.dtb"
            verifier = temporary / "fit_check_sign"
            for path in (fit, control_dtb, verifier):
                path.write_bytes(b"fixture")

            commands: list[list[str]] = []

            def runner(command: list[str]) -> None:
                commands.append(command)

            configurations = verify_fit_profiles.verify_profiles(
                fit,
                control_dtb,
                verifier,
                "fdtput",
                "e310",
                runner=runner,
            )

        self.assertEqual(len(configurations), 4)
        self.assertEqual(len(commands), 8)
        for index, configuration in enumerate(configurations):
            set_default, verify = commands[index * 2 : index * 2 + 2]
            self.assertEqual(set_default[0:3], ["fdtput", "-p", "-t"])
            self.assertEqual(set_default[-3:], ["/configurations", "default", configuration])
            self.assertEqual(verify[0], str(verifier.resolve()))
            self.assertEqual(verify[-1], str(control_dtb.resolve()))


if __name__ == "__main__":
    unittest.main()
