# SPDX-License-Identifier: MIT
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDROOT = ROOT / "boards" / "e310" / "hw" / "buildroot"
DEFCONFIG = BUILDROOT / "configs" / "zynq_antsdr_e310_defconfig"
RUNTIME = BUILDROOT / "board" / "e310" / "runtime"
POSIX_SHELL = next(
    (
        candidate
        for candidate in (
            shutil.which("sh"),
            r"C:\\Program Files\\Git\\bin\\bash.exe",
            r"C:\\Program Files\\Git\\usr\\bin\\sh.exe",
        )
        if candidate and Path(candidate).is_file()
    ),
    None,
)


class BuildrootOverlayTest(unittest.TestCase):
    def test_overlay_materializes_on_pinned_buildroot(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "prepare_component.py"),
                "e310",
                "buildroot",
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_defconfig_declares_the_runtime_contract(self) -> None:
        config = DEFCONFIG.read_text(encoding="utf-8")
        required = {
            'BR2_TARGET_GENERIC_ROOT_PASSWD="antsdr"',
            'BR2_TARGET_GENERIC_GETTY_PORT="ttyPS0"',
            'BR2_ROOTFS_POST_BUILD_SCRIPT="board/e310/post-build.sh"',
            'BR2_PACKAGE_BUSYBOX_CONFIG_FRAGMENT_FILES="board/e310/busybox.fragment"',
            "BR2_PACKAGE_LIBIIO_IIOD=y",
            "BR2_PACKAGE_LIBIIO_IIOD_USBD=y",
            "BR2_PACKAGE_DROPBEAR=y",
            "BR2_PACKAGE_WPA_SUPPLICANT=y",
            "BR2_PACKAGE_HOST_GENIMAGE=y",
        }
        self.assertFalse(required - set(config.splitlines()))
        self.assertNotIn('BR2_TARGET_GENERIC_ROOT_PASSWD="analog"', config)

    @unittest.skipUnless(POSIX_SHELL, "a POSIX shell is required")
    def test_runtime_scripts_are_posix_shell_syntax(self) -> None:
        scripts = sorted(path for path in RUNTIME.rglob("*") if path.is_file())
        scripts.append(BUILDROOT / "board" / "e310" / "post-build.sh")
        for script in scripts:
            result = subprocess.run(
                [str(POSIX_SHELL), "-n", str(script)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, f"{script}: {result.stderr}")

    @unittest.skipUnless(POSIX_SHELL, "a POSIX shell is required")
    def test_config_import_persists_only_validated_runtime_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            target = temporary / "target"
            defaults = target / "etc" / "antsdr"
            defaults.mkdir(parents=True)
            shutil.copy2(BUILDROOT / "board" / "e310" / "defaults.conf", defaults)
            (target / "run" / "antsdr").mkdir(parents=True)
            environment = temporary / "environment"
            environment.write_text("qspiboot run qspiboot\n", encoding="utf-8")
            commands = temporary / "bin"
            commands.mkdir()

            fw_printenv = commands / "fw_printenv"
            fw_printenv.write_text(
                "#!/bin/sh\n"
                "[ -f \"$TEST_ENV\" ] || exit 1\n"
                "if [ \"$1\" = -n ]; then key=$2; else key=$1; fi\n"
                "awk -v key=\"$key\" '$1 == key { $1=\"\"; sub(/^ /, \"\"); print; found=1 } END { exit found ? 0 : 1 }' \"$TEST_ENV\"\n",
                encoding="utf-8",
            )
            fw_setenv = commands / "fw_setenv"
            fw_setenv.write_text(
                "#!/bin/sh\n"
                "[ \"$1\" = -s ] || exit 2\n"
                "cp \"$2\" \"$TEST_ENV\"\n",
                encoding="utf-8",
            )
            os.chmod(fw_printenv, 0o755)
            os.chmod(fw_setenv, 0o755)

            config = temporary / "config.txt"
            config.write_text(
                "[USB_ETHERNET]\n"
                "hostname = lab-e310\n"
                "ipaddr = 10.31.0.1\n"
                "ipaddr_host = 10.31.0.10\n"
                "netmask = 255.255.255.0\n"
                "usb_ethernet_mode = rndis\n"
                "[NETWORK]\n"
                "mode = static\n"
                "ipaddr_eth = 192.168.10.2\n"
                "netmask_eth = 255.255.255.0\n"
                "eth_gateway = 192.168.10.1\n"
                "[WLAN]\n"
                "ssid_wlan = lab\n"
                "pwd_wlan = secret passphrase\n"
                "[SYSTEM]\n"
                "xo_correction = 40000000\n"
                "udc_handle_suspend = 0\n"
                "[ACTIONS]\n"
                "diagnostic_report = 1\n"
                "dfu = 1\n",
                encoding="utf-8",
            )
            runtime_env = os.environ | {
                "ANTSDR_ROOT_PREFIX": str(target),
                "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                "TEST_ENV": str(environment),
            }
            script = RUNTIME / "sbin" / "antsdr-config"
            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "import", str(config)],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            persisted = dict(
                line.split(" ", 1)
                for line in environment.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(persisted["ipaddr"], "10.31.0.1")
            self.assertEqual(persisted["ipaddr_eth"], "192.168.10.2")
            self.assertEqual(persisted["network_mode"], "static")
            self.assertEqual(persisted["ipaddr_wlan"], "")
            self.assertNotIn("dfu", persisted)
            self.assertNotIn("rf_model", persisted)
            self.assertNotIn("diagnostic_report", persisted)

            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "action", str(config), "diagnostic_report"],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "1\n")

            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "diagnostic"],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("[WLAN]", result.stdout)
            self.assertNotIn("pwd_wlan", result.stdout)
            self.assertNotIn("secret passphrase", result.stdout)

            before = environment.read_text(encoding="utf-8")
            config.write_text(
                "[USB_ETHERNET]\nusb_ethernet_mode = rndis; reboot\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "import", str(config)],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(environment.read_text(encoding="utf-8"), before)

            config.write_text(
                "[USB_ETHERNET]\nnetmask = 255.0.255.0\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "import", str(config)],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(environment.read_text(encoding="utf-8"), before)

            config.write_text(
                "[WLAN]\npwd_wlan = short\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "import", str(config)],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(environment.read_text(encoding="utf-8"), before)

            config.write_text(
                "[ACTIONS]\ndiagnostic_report = 2\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "import", str(config)],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("diagnostic_report must be 0 or 1", result.stderr)
            self.assertEqual(environment.read_text(encoding="utf-8"), before)

            environment.write_text("", encoding="utf-8")
            config.write_text(
                "[USB_ETHERNET]\nhostname = lab-e310\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(POSIX_SHELL), str(script), "import", str(config)],
                cwd=ROOT,
                env=runtime_env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unrecognized U-Boot environment", result.stderr)
            self.assertEqual(environment.read_text(encoding="utf-8"), "")

    def test_diagnostic_report_is_bounded_and_redacted(self) -> None:
        report = (RUNTIME / "sbin" / "antsdr-diagnostic").read_text(encoding="utf-8")
        volume = (RUNTIME / "init.d" / "S40antsdr-config-volume").read_text(encoding="utf-8")
        config = (RUNTIME / "sbin" / "antsdr-config").read_text(encoding="utf-8")

        self.assertIn("/usr/sbin/antsdr-config diagnostic", report)
        self.assertIn("diagnostic_report.txt", volume)
        self.assertIn("diagnostic_report", config)
        for forbidden in ("fw_printenv", "pwd_wlan", "shadow", "authorized_keys", "dropbear", "/var/log", "dmesg"):
            self.assertNotIn(forbidden, report)

    def test_runtime_services_have_owned_and_idempotent_lifecycle(self) -> None:
        gadget = (RUNTIME / "init.d" / "S20antsdr-gadget").read_text(encoding="utf-8")
        network = (RUNTIME / "init.d" / "S30antsdr-network").read_text(encoding="utf-8")
        suspend = (RUNTIME / "sbin" / "antsdr-udc-suspend").read_text(encoding="utf-8")

        for function in ("rndis.0", "ncm.usb0", "ecm.usb0"):
            self.assertIn(function, gadget)
        self.assertIn('start-stop-daemon -K -q -p "$IIOD_PID" -x /usr/sbin/iiod', gadget)
        self.assertNotIn("killall", network)
        self.assertIn('HTTPD_PID=/run/antsdr/httpd.pid', network)
        self.assertIn('UDHCPD_PID=/run/antsdr/udhcpd.pid', network)
        self.assertIn('WPA_PID=/run/antsdr/wpa_supplicant.pid', network)
        self.assertIn("wpa_passphrase", network)
        self.assertIn("trap restore_mode EXIT", suspend)

    def test_runtime_excludes_unsafe_vendor_update_paths(self) -> None:
        runtime = "\n".join(
            path.read_text(encoding="utf-8")
            for path in RUNTIME.rglob("*")
            if path.is_file()
        ).lower()
        self.assertNotIn("md5", runtime)
        self.assertNotIn("update_from_github", runtime)
        self.assertNotIn("wget", runtime)
        self.assertNotIn("http://", runtime)
        self.assertNotIn("dd if=", runtime)
        self.assertNotIn("uenvcmd", runtime)


if __name__ == "__main__":
    unittest.main()
