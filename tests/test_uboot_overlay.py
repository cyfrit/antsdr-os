# SPDX-License-Identifier: MIT
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "boards" / "e310"
UBOOT = BOARD / "hw" / "uboot"
DTS = UBOOT / "dts" / "zynq-antsdr-e310.dts"
DEFCONFIG = UBOOT / "configs" / "zynq_antsdr_e310_defconfig"
HEADER = UBOOT / "include" / "configs" / "zynq_antsdr_e310.h"
UENV_COMMAND = UBOOT / "cmd" / "antsdr_uenv.c"
UPSTREAM = ROOT / "upstream" / "adi-plutosdr-fw" / "u-boot-xlnx"


class UbootOverlayTest(unittest.TestCase):
    def test_overlay_materializes_on_pinned_uboot(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "prepare_component.py"),
                "e310",
                "u_boot",
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_defconfig_enables_fit_and_storage_support(self) -> None:
        config = DEFCONFIG.read_text(encoding="utf-8")
        required = {
            'CONFIG_SYS_CONFIG_NAME="zynq_antsdr_e310"',
            'CONFIG_DEFAULT_DEVICE_TREE="zynq-antsdr-e310"',
            "CONFIG_FIT=y",
            "CONFIG_FIT_SIGNATURE=y",
            "CONFIG_CMD_MMC=y",
            "CONFIG_CMD_SF=y",
            "CONFIG_CMD_USB=y",
            "CONFIG_CMD_DFU=y",
            "CONFIG_ZYNQ_SDHCI=y",
            "CONFIG_ZYNQ_QSPI=y",
            "CONFIG_SPI_FLASH_BAR=y",
            "CONFIG_SPI_FLASH_STMICRO=y",
            "CONFIG_USB_GADGET=y",
            "CONFIG_CI_UDC=y",
            "CONFIG_USB_GADGET_DOWNLOAD=y",
            "CONFIG_G_DNL_VENDOR_NUM=0x0456",
            "CONFIG_G_DNL_PRODUCT_NUM=0xb674",
            "CONFIG_DFU_SF=y",
            "CONFIG_CMD_IMPORTENV=y",
            "CONFIG_CMD_ANTSDR_UENV=y",
            "CONFIG_ANTSDR_UENV_COMPAT=y",
        }
        self.assertFalse(required - set(config.splitlines()))

        forbidden = {
            "CONFIG_CMD_NET=y",
            "CONFIG_CMD_NFS=y",
            "CONFIG_CMD_DHCP=y",
            "CONFIG_CMD_TFTPPUT=y",
        }
        self.assertFalse(forbidden & set(config.splitlines()))

    def test_device_tree_matches_boot_contract(self) -> None:
        board = yaml.safe_load((BOARD / "board.yaml").read_text(encoding="utf-8"))
        dts = DTS.read_text(encoding="utf-8")
        boot = board["hardware"]["boot"]

        self.assertIn('model = "ANTSDR E310 Rev.C";', dts)
        self.assertIn('"microphase,antsdr-e310-revc"', dts)
        self.assertIn("reg = <0x0 0x40000000>;", dts)
        self.assertIn('compatible = "jedec,spi-nor", "spi-flash";', dts)
        self.assertNotIn("n25q256a11", dts)
        self.assertIn("&sdhci0 {", dts)
        self.assertIn("&uart1 {", dts)
        self.assertIn(
            'reset-gpios = <&gpio0 46 GPIO_ACTIVE_LOW>;',
            dts,
        )

        for partition in boot["qspi"]["partitions"]:
            offset = partition["offset"]
            size = partition["size"]
            self.assertIn(f'label = "{partition["name"]}";', dts)
            self.assertIn(f"reg = <{offset:#08x} {size:#08x}>;", dts)

    def test_environment_is_board_local_and_constrained(self) -> None:
        header = HEADER.read_text(encoding="utf-8")

        self.assertIn("#define CONFIG_EXTRA_ENV_SETTINGS", header)
        self.assertIn('#define CONFIG_BOOTCOMMAND "run boot_antsdr"', header)
        self.assertIn('"boot_antsdr=run $modeboot\\0"', header)
        self.assertNotIn('"boot_antsdr=run sdboot || run qspiboot\\0"', header)
        self.assertIn('"recovery=run load_qspi_extraenv; run qspiboot\\0"', header)
        self.assertIn("antsdr-e310.itb", header)
        self.assertNotIn("sdboot_legacy", header)
        self.assertNotIn("uramdisk.image.gz", header)
        self.assertNotIn("devicetree.dtb", header)
        self.assertNotIn("devicetree_image", header)
        self.assertNotIn('"kernel_image=', header)
        self.assertIn("select_rf_profile", header)
        self.assertIn(
            '"setenv fit_config config@e310-${rf_model}-${rf_topology}; "',
            header,
        )
        self.assertIn("validate_rf_model", header)
        self.assertIn("validate_rf_topology", header)
        self.assertNotIn('"rf_model=ad9363\\0"', header)
        self.assertNotIn('"rf_model=ad9361\\0"', header)
        self.assertNotIn('"rf_topology=1r1t\\0"', header)
        self.assertNotIn('"rf_topology=2r2t\\0"', header)
        self.assertIn("qspi_fit_offset=0x00200000", header)
        self.assertIn("qspi_fit_max_size=0x01e00000", header)
        self.assertIn("rootfstype=ramfs", header)
        self.assertIn("clk_ignore_unused", header)
        self.assertIn('"fdt_high=0x20000000\\0"', header)
        self.assertIn('"initrd_high=0x20000000\\0"', header)
        self.assertNotIn("maxcpus=1", header)

        self.assertIn('"bootenv=uEnv.txt\\0"', header)
        self.assertIn('"uenv_image=uEnv.txt\\0"', header)
        self.assertIn("select_bootenv", header)
        self.assertIn("setenv uenv_file ${bootenv};", header)
        self.assertIn("env import -t ${uenv_load_address} ${filesize};", header)
        self.assertIn('"run_uenvcmd=if test -n ${uenvcmd}; then run uenvcmd; fi\\0"', header)
        self.assertIn("CONFIG_ANTSDR_UENV_COMPAT", header)
        self.assertIn("antsdr_uenv ${uenv_load_address} ${filesize};", header)
        self.assertIn('"preboot=if test \\"${modeboot}\\" = sdboot; then "', header)
        self.assertIn("qspi_extraenv_offset=0x000ff000", header)
        self.assertIn("env import -c ${qspi_extraenv_load_address}", header)
        self.assertIn(
            '"dfu_alt_info=qspi-linux raw 0x00200000 0x01e00000\\0"',
            header,
        )
        self.assertIn('"dfu_recovery=if sf probe 0:0 50000000 0; then "', header)
        self.assertNotIn("qspi-fsbl-uboot raw", header)
        self.assertNotIn("qspi-uboot-env raw", header)
        self.assertNotIn("loaddfu=", header)
        self.assertNotIn("sf update", header)
        self.assertNotIn("env save", header)
        self.assertNotRegex(header, r"\\bfdt\\s+(?:set|rm)\\b")
        self.assertNotRegex(header, r"\\b(?:http|wget|tftp)\\b")
        self.assertNotIn("md5", header.lower())

    def test_boot_memory_regions_are_disjoint(self) -> None:
        board = yaml.safe_load((BOARD / "board.yaml").read_text(encoding="utf-8"))
        header = HEADER.read_text(encoding="utf-8")

        def environment_hex(name: str) -> int:
            match = re.search(rf'"{name}=(0x[0-9a-fA-F]+)\\0"', header)
            self.assertIsNotNone(match, name)
            return int(match.group(1), 16)

        fit_start = environment_hex("fit_load_address")
        fit_end = fit_start + environment_hex("qspi_fit_max_size")
        fpga_start = 0x0F000000
        memory_end = board["hardware"]["ddr"]["size_bytes"]

        self.assertLessEqual(fit_end, fpga_start)
        self.assertLess(fpga_start, memory_end)

    def test_locked_uenv_importer_has_a_narrow_variable_allowlist(self) -> None:
        command = UENV_COMMAND.read_text(encoding="utf-8")

        self.assertIn('\"rf_model\"', command)
        self.assertIn('\"rf_topology\"', command)
        self.assertIn("setenv(key_buffer, value_buffer)", command)
        self.assertNotIn('\"uenvcmd\"', command)
        self.assertNotIn("saveenv", command)

    @unittest.skipUnless(shutil.which("cpp") and shutil.which("dtc"), "cpp and dtc are required")
    def test_device_tree_compiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            preprocessed = Path(directory) / "zynq-antsdr-e310.dts"
            dtb = Path(directory) / "zynq-antsdr-e310.dtb"
            preprocess = subprocess.run(
                [
                    "cpp",
                    "-nostdinc",
                    "-undef",
                    "-D__DTS__",
                    "-x",
                    "assembler-with-cpp",
                    "-I",
                    str(UBOOT / "dts"),
                    "-I",
                    str(UPSTREAM / "arch" / "arm" / "dts"),
                    "-I",
                    str(UPSTREAM / "include"),
                    str(DTS),
                    str(preprocessed),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(preprocess.returncode, 0, preprocess.stderr)
            compile_dtb = subprocess.run(
                ["dtc", "-I", "dts", "-O", "dtb", "-o", str(dtb), str(preprocessed)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_dtb.returncode, 0, compile_dtb.stderr)
            self.assertGreater(dtb.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
