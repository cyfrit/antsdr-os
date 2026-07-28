/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * ANTSDR E310 Rev.C configuration.
 *
 * Copyright (C) 2026 Cyfrit <i@cli.tf>
 */

#ifndef __CONFIG_ZYNQ_ANTSDR_E310_H
#define __CONFIG_ZYNQ_ANTSDR_E310_H

/*
 * This board intentionally owns its environment rather than inheriting the
 * Pluto-specific runtime DT mutations from zynq-common.h. It retains the
 * conventional SD-card uEnv.txt interface for user-managed boot settings.
 */
#define CONFIG_EXTRA_ENV_SETTINGS \
	"fit_image=antsdr-e310.itb\0" \
	"fit_load_address=0x02080000\0" \
	"kernel_image=uImage\0" \
	"kernel_load_address=0x00008000\0" \
	"ramdisk_image=uramdisk.image.gz\0" \
	"ramdisk_load_address=0x04000000\0" \
	"devicetree_image=devicetree.dtb\0" \
	"devicetree_load_address=0x02000000\0" \
	"uenv_image=uEnv.txt\0" \
	"uenv_load_address=0x02000000\0" \
	"qspi_extraenv_load_address=0x0207e000\0" \
	"qspi_extraenv_offset=0x000ff000\0" \
	"qspi_extraenv_size=0x00001000\0" \
	"qspi_fit_offset=0x00200000\0" \
	"qspi_fit_max_size=0x01e00000\0" \
	"dfu_alt_info=qspi-linux raw 0x00200000 0x01e00000\0" \
	"load_uenv=if test -e mmc 0 /${uenv_image}; then " \
		"if fatload mmc 0 ${uenv_load_address} ${uenv_image}; then " \
			"env import -t ${uenv_load_address} ${filesize}; " \
		"fi; " \
	"fi\0" \
	"run_uenvcmd=if test -n ${uenvcmd}; then run uenvcmd; fi\0" \
	"load_qspi_extraenv=if sf probe 0:0 50000000 0; then " \
		"if sf read ${qspi_extraenv_load_address} ${qspi_extraenv_offset} ${qspi_extraenv_size}; then " \
			"env import -c ${qspi_extraenv_load_address} ${qspi_extraenv_size} || true; " \
		"fi; " \
	"fi\0" \
	"preboot=if test \"${modeboot}\" = sdboot; then " \
		"run load_uenv; run run_uenvcmd; " \
		"else if test \"${modeboot}\" = qspiboot; then run load_qspi_extraenv; fi; fi\0" \
	"validate_rf_model=if test \"${rf_model}\" = ad9363; then true; " \
		"else if test \"${rf_model}\" = ad9361; then true; else false; fi; fi\0" \
	"validate_rf_topology=if test \"${rf_topology}\" = 1r1t; then true; " \
		"else if test \"${rf_topology}\" = 2r2t; then true; else false; fi; fi\0" \
	"select_rf_profile=if run validate_rf_model; then " \
		"if run validate_rf_topology; then " \
			"setenv fit_config config@e310-${rf_model}-${rf_topology}; " \
			"setenv devicetree_image zynq-antsdr-e310-${rf_model}-${rf_topology}.dtb; " \
		"else echo Set rf_topology to 1r1t or 2r2t; false; fi; " \
		"else echo Set rf_model to ad9363 or ad9361; false; fi\0" \
	"sdboot_legacy=if run select_rf_profile; then " \
		"if fatload mmc 0 ${kernel_load_address} ${kernel_image}; then " \
		"if fatload mmc 0 ${devicetree_load_address} ${devicetree_image}; then " \
			"if fatload mmc 0 ${ramdisk_load_address} ${ramdisk_image}; then " \
				"bootm ${kernel_load_address} ${ramdisk_load_address} ${devicetree_load_address}; " \
			"fi; " \
		"fi; " \
		"fi; " \
	"fi; false\0" \
	"sdboot=if mmc dev 0; then " \
		"if mmc rescan; then " \
			"if fatload mmc 0 ${fit_load_address} ${fit_image}; then " \
				"if run select_rf_profile; then bootm ${fit_load_address}#${fit_config}; fi; " \
			"else run sdboot_legacy; " \
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
	"dfu_recovery=if sf probe 0:0 50000000 0; then " \
		"dfu 0 sf 0:0:50000000:0; " \
	"fi\0"

#include <configs/zynq-common.h>

#undef CONFIG_BOOTCOMMAND
#define CONFIG_BOOTCOMMAND "run boot_antsdr"

#endif /* __CONFIG_ZYNQ_ANTSDR_E310_H */
