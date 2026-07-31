/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * ANTSDR E310 Rev.C configuration.
 *
 * Copyright (C) 2026 Cyfrit <i@cli.tf>
 */

#ifndef __CONFIG_ZYNQ_ANTSDR_E310_H
#define __CONFIG_ZYNQ_ANTSDR_E310_H

#ifdef CONFIG_ANTSDR_UENV_COMPAT
#define ANTSDR_UENV_IMPORT \
	"env import -t ${uenv_load_address} ${filesize}; "
#define ANTSDR_UENV_POSTLOAD "run run_uenvcmd; "
#define ANTSDR_UENV_COMPAT_ENV \
	"run_uenvcmd=if test -n ${uenvcmd}; then run uenvcmd; fi\0"

#else
#define ANTSDR_UENV_IMPORT \
	"antsdr_uenv ${uenv_load_address} ${filesize}; "
#define ANTSDR_UENV_POSTLOAD ""
#define ANTSDR_UENV_COMPAT_ENV
#endif

/*
 * This board intentionally owns its environment rather than inheriting the
 * Pluto-specific runtime DT mutations from zynq-common.h. It retains the
 * conventional SD-card uEnv.txt interface for user-managed boot settings.
 */
#define CONFIG_EXTRA_ENV_SETTINGS \
	"fit_image=antsdr-e310.itb\0" \
	"fit_load_address=0x02080000\0" \
	"bootargs=console=ttyPS0,115200 root=/dev/ram0 rw rootfstype=ramfs earlyprintk clk_ignore_unused\0" \
	"fdt_high=0x20000000\0" \
	"initrd_high=0x20000000\0" \
	"bootenv=uEnv.txt\0" \
	"uenv_image=uEnv.txt\0" \
	"uenv_file=uEnv.txt\0" \
	"uenv_load_address=0x02000000\0" \
	"qspi_boot_payload=boot.dfu\0" \
	"qspi_firmware_payload=firmware.dfu\0" \
	"qspi_extraenv_payload=uboot-extra-env.dfu\0" \
	"qspi_boot_load_address=0x01000000\0" \
	"qspi_firmware_load_address=0x02080000\0" \
	"qspi_extraenv_load_address=0x0207e000\0" \
	"qspi_extraenv_offset=0x003ff000\0" \
	"qspi_extraenv_size=0x00001000\0" \
	"qspi_fit_offset=0x00500000\0" \
	"qspi_fit_max_size=0x01b00000\0" \
	"qspi_exact_size=0\0" \
	/* Keep this in sync with board.yaml: BOOT.BIN carries FSBL, bitstream and
	 * U-Boot, so the vendor's inherited 1 MiB boot region is not usable. */ \
	"dfu_alt_info=boot.dfu raw 0x00000000 0x00400000\\;" \
		"firmware.dfu raw 0x00500000 0x01b00000\\;" \
		"uboot-extra-env.dfu raw 0x003ff000 0x00001000\\;" \
		"uboot-env.dfu raw 0x00400000 0x00020000\\;" \
		"spare.dfu raw 0x00420000 0x000e0000\0" \
	"select_bootenv=if test -n ${bootenv}; then " \
		"setenv uenv_file ${bootenv}; " \
		"else setenv uenv_file ${uenv_image}; fi\0" \
	"load_uenv=run select_bootenv; " \
		"if test -e mmc 0 /${uenv_file}; then " \
		"if fatload mmc 0 ${uenv_load_address} ${uenv_file}; then " \
			ANTSDR_UENV_IMPORT \
		"fi; " \
	"fi\0" \
	ANTSDR_UENV_COMPAT_ENV \
	"load_qspi_extraenv=if sf probe 0:0 50000000 0; then " \
		"if sf read ${qspi_extraenv_load_address} ${qspi_extraenv_offset} ${qspi_extraenv_size}; then " \
			"env import -c ${qspi_extraenv_load_address} ${qspi_extraenv_size} || true; " \
		"fi; " \
	"fi\0" \
	"preboot=if test \"${modeboot}\" = sdboot; then " \
		"run load_uenv; " ANTSDR_UENV_POSTLOAD \
		"else if test \"${modeboot}\" = qspiboot; then run load_qspi_extraenv; fi; fi\0" \
	"validate_rf_model=if test \"${rf_model}\" = ad9363; then true; " \
		"else if test \"${rf_model}\" = ad9361; then true; else false; fi; fi\0" \
	"validate_rf_topology=if test \"${rf_topology}\" = 1r1t; then true; " \
		"else if test \"${rf_topology}\" = 2r2t; then true; else false; fi; fi\0" \
	"select_rf_profile=if run validate_rf_model; then " \
		"if run validate_rf_topology; then " \
			"setenv fit_config config@e310-${rf_model}-${rf_topology}; " \
		"else echo Set rf_topology to 1r1t or 2r2t; false; fi; " \
		"else echo Set rf_model to ad9363 or ad9361; false; fi\0" \
	"sdboot=if mmc dev 0; then " \
		"if mmc rescan; then " \
			"if fatload mmc 0 ${fit_load_address} ${fit_image}; then " \
				"if run select_rf_profile; then bootm ${fit_load_address}#${fit_config}; fi; " \
			"fi; " \
		"fi; " \
	"fi; false\0" \
	"qspiboot=if sf probe 0:0 50000000 0; then " \
		"if sf read ${fit_load_address} ${qspi_fit_offset} ${qspi_fit_max_size}; then " \
			"if run select_rf_profile; then bootm ${fit_load_address}#${fit_config}; fi; " \
		"fi; " \
	"fi; false\0" \
	"boot_antsdr=run $modeboot\0" \
	"recovery=run load_qspi_extraenv; run qspiboot\0" \
	"qspi_flash_file=if fatload mmc 0 ${qspi_load_address} ${qspi_file}; then " \
		"if test \"${qspi_exact_size}\" = 1; then " \
			"if test ${filesize} -eq ${qspi_max_size}; then " \
				"sf update ${qspi_load_address} ${qspi_offset} ${filesize}; " \
			"else echo ${qspi_file} must fill its QSPI partition; false; fi; " \
		"else if test ${filesize} -le ${qspi_max_size}; then " \
			"sf update ${qspi_load_address} ${qspi_offset} ${filesize}; " \
		"else echo ${qspi_file} exceeds its QSPI partition; false; fi; fi; " \
	"else echo missing ${qspi_file} on SD; false; fi\0" \
	"qspi_provision=if mmc dev 0; then " \
		"if mmc rescan; then " \
			"if sf probe 0:0 50000000 0; then " \
				"setenv qspi_file ${qspi_firmware_payload}; " \
				"setenv qspi_load_address ${qspi_firmware_load_address}; " \
				"setenv qspi_offset 0x00500000; " \
				"setenv qspi_max_size 0x01b00000; " \
				"setenv qspi_exact_size 0; " \
				"if run qspi_flash_file; then " \
					"setenv qspi_file ${qspi_boot_payload}; " \
					"setenv qspi_load_address ${qspi_boot_load_address}; " \
					"setenv qspi_offset 0x00000000; " \
					"setenv qspi_max_size 0x00400000; " \
					"setenv qspi_exact_size 1; " \
					"if run qspi_flash_file; then run qspiboot; fi; " \
				"fi; " \
			"fi; " \
		"fi; " \
	"fi\0" \
	"dfu_recovery=if sf probe 0:0 50000000 0; then " \
		"dfu 0 sf 0:0:50000000:0; " \
	"fi\0"

#include <configs/zynq-common.h>

#undef CONFIG_BOOTCOMMAND
#define CONFIG_BOOTCOMMAND "run boot_antsdr"

#endif /* __CONFIG_ZYNQ_ANTSDR_E310_H */
