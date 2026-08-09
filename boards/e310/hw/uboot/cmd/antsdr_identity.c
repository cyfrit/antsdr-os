// SPDX-License-Identifier: GPL-2.0-or-later
/* Derive stable board identity from the Winbond SPI NOR unique ID. */

#include <common.h>
#include <command.h>
#include <errno.h>
#include <net.h>
#include <spi.h>
#include <u-boot/sha256.h>

#define ANTSDR_QSPI_BUS 0
#define ANTSDR_QSPI_CHIP_SELECT 0
#define ANTSDR_QSPI_ID_SPEED_HZ 10000000
#define ANTSDR_WINBOND_MANUFACTURER_ID 0xef
#define ANTSDR_READ_JEDEC_ID 0x9f
#define ANTSDR_READ_UNIQUE_ID 0x4b
#define ANTSDR_UNIQUE_ID_SIZE 8

static int antsdr_spi_read(struct spi_slave *spi, const u8 *command,
			   size_t command_length, u8 *data, size_t data_length)
{
	int ret;

	ret = spi_xfer(spi, command_length * 8, command, NULL,
		       SPI_XFER_BEGIN);
	if (ret)
		return ret;

	return spi_xfer(spi, data_length * 8, NULL, data, SPI_XFER_END);
}

static int antsdr_read_unique_id(u8 uid[ANTSDR_UNIQUE_ID_SIZE])
{
	const u8 read_id = ANTSDR_READ_JEDEC_ID;
	const u8 read_uid[] = { ANTSDR_READ_UNIQUE_ID, 0, 0, 0, 0 };
	struct spi_slave *spi;
	u8 jedec_id[3];
	int ret;

	spi = spi_setup_slave(ANTSDR_QSPI_BUS, ANTSDR_QSPI_CHIP_SELECT,
			      ANTSDR_QSPI_ID_SPEED_HZ, SPI_MODE_0);
	if (!spi)
		return -ENODEV;

	ret = spi_claim_bus(spi);
	if (ret)
		goto out;

	ret = antsdr_spi_read(spi, &read_id, sizeof(read_id),
			      jedec_id, sizeof(jedec_id));
	if (!ret && jedec_id[0] != ANTSDR_WINBOND_MANUFACTURER_ID)
		ret = -ENODEV;
	if (!ret)
		ret = antsdr_spi_read(spi, read_uid, sizeof(read_uid), uid,
				      ANTSDR_UNIQUE_ID_SIZE);

	spi_release_bus(spi);
out:
	spi_free_slave(spi);
	return ret;
}

static int antsdr_uid_valid(const u8 uid[ANTSDR_UNIQUE_ID_SIZE])
{
	bool all_zero = true;
	bool all_ff = true;
	unsigned int index;

	for (index = 0; index < ANTSDR_UNIQUE_ID_SIZE; index++) {
		all_zero &= uid[index] == 0;
		all_ff &= uid[index] == 0xff;
	}

	return !all_zero && !all_ff;
}

static int antsdr_mac_valid(const char *text)
{
	unsigned int octet[6];
	unsigned char address[6];
	char extra;
	unsigned int index;

	if (!text || sscanf(text, "%2x:%2x:%2x:%2x:%2x:%2x%c",
			    &octet[0], &octet[1], &octet[2], &octet[3],
			    &octet[4], &octet[5], &extra) != 6)
		return 0;

	for (index = 0; index < ARRAY_SIZE(octet); index++) {
		if (octet[index] > 0xff)
			return 0;
		address[index] = octet[index];
	}

	return is_valid_ethaddr(address);
}

static int antsdr_set_serial(const u8 uid[ANTSDR_UNIQUE_ID_SIZE])
{
	char serial[ANTSDR_UNIQUE_ID_SIZE * 2 + 1];
	unsigned int index;

	if (getenv("serial#") && *getenv("serial#"))
		return 0;

	for (index = 0; index < ANTSDR_UNIQUE_ID_SIZE; index++)
		sprintf(serial + index * 2, "%02x", uid[index]);

	return setenv("serial#", serial);
}

static int antsdr_set_mac(const u8 uid[ANTSDR_UNIQUE_ID_SIZE])
{
	static const u8 domain[] = "AntSDR E310 Ethernet MAC";
	u8 input[sizeof(domain) - 1 + ANTSDR_UNIQUE_ID_SIZE];
	u8 digest[SHA256_SUM_LEN];
	u8 address[6];
	char text[18];

	if (antsdr_mac_valid(getenv("ethaddr")))
		return 0;

	memcpy(input, domain, sizeof(domain) - 1);
	memcpy(input + sizeof(domain) - 1, uid, ANTSDR_UNIQUE_ID_SIZE);
	sha256_csum_wd(input, sizeof(input), digest, CHUNKSZ_SHA256);
	memcpy(address, digest, sizeof(address));
	address[0] = (address[0] & 0xfc) | 0x02;

	sprintf(text, "%02x:%02x:%02x:%02x:%02x:%02x",
		address[0], address[1], address[2],
		address[3], address[4], address[5]);
	return setenv("ethaddr", text);
}

static int do_antsdr_identity(cmd_tbl_t *cmdtp, int flag, int argc,
			      char * const argv[])
{
	u8 uid[ANTSDR_UNIQUE_ID_SIZE];
	int ret;

	if (argc != 1)
		return CMD_RET_USAGE;
	if (getenv("serial#") && *getenv("serial#") &&
	    antsdr_mac_valid(getenv("ethaddr")))
		return CMD_RET_SUCCESS;

	ret = antsdr_read_unique_id(uid);
	if (ret || !antsdr_uid_valid(uid)) {
		printf("AntSDR: SPI NOR hardware identity unavailable\n");
		return CMD_RET_SUCCESS;
	}

	if (antsdr_set_serial(uid) || antsdr_set_mac(uid)) {
		printf("AntSDR: cannot publish hardware identity\n");
		return CMD_RET_FAILURE;
	}

	return CMD_RET_SUCCESS;
}

U_BOOT_CMD(
	antsdr_identity, 1, 0, do_antsdr_identity,
	"publish stable AntSDR hardware identity",
	"\n"
	"    - derives serial# and ethaddr from the SPI NOR unique ID"
);
