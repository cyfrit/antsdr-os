// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Import only E310 RF profile selectors from a text uEnv file.
 *
 * Copyright (C) 2026 Cyfrit <i@cli.tf>
 */

#include <common.h>
#include <command.h>
#include <linux/types.h>

#define ANTSDR_UENV_MAX_SIZE (64 * 1024)
#define ANTSDR_UENV_MAX_VALUE_LENGTH 32

static int antsdr_uenv_key_allowed(const char *key, size_t key_length)
{
	if (key_length == sizeof("rf_model") - 1 &&
	    !strncmp(key, "rf_model", key_length))
		return 1;

	if (key_length == sizeof("rf_topology") - 1 &&
	    !strncmp(key, "rf_topology", key_length))
		return 1;

	return 0;
}

static void antsdr_uenv_trim(const char **start, const char **end)
{
	while (*start < *end && (**start == ' ' || **start == '\t'))
		(*start)++;

	while (*end > *start &&
	       ((*(*end - 1) == ' ') || (*(*end - 1) == '\t') ||
		(*(*end - 1) == '\r')))
		(*end)--;
}

static int antsdr_uenv_import(const char *data, size_t size)
{
	const char *cursor = data;
	const char *end = data + size;
	unsigned int imported = 0;

	while (cursor < end) {
		const char *line = cursor;
		const char *line_end;
		const char *equals = NULL;
		const char *key;
		const char *key_end;
		const char *value;
		const char *value_end;
		char key_buffer[sizeof("rf_topology")];
		char value_buffer[ANTSDR_UENV_MAX_VALUE_LENGTH];

		while (cursor < end && *cursor != '\n')
			cursor++;
		line_end = cursor;
		if (cursor < end)
			cursor++;

		antsdr_uenv_trim(&line, &line_end);
		if (line == line_end || *line == '#')
			continue;

		for (key_end = line; key_end < line_end; key_end++) {
			if (*key_end == '=') {
				equals = key_end;
				break;
			}
		}
		if (!equals)
			continue;

		key = line;
		key_end = equals;
		antsdr_uenv_trim(&key, &key_end);
		if (!antsdr_uenv_key_allowed(key, key_end - key))
			continue;
		memcpy(key_buffer, key, key_end - key);
		key_buffer[key_end - key] = '\0';

		value = equals + 1;
		value_end = line_end;
		antsdr_uenv_trim(&value, &value_end);
		if (value_end - value >= sizeof(value_buffer)) {
			printf("ANTSDR: rejected oversized %.*s value\n",
			       (int)(key_end - key), key);
			return CMD_RET_FAILURE;
		}

		memcpy(value_buffer, value, value_end - value);
		value_buffer[value_end - value] = '\0';
		if (setenv(key_buffer, value_buffer)) {
			printf("ANTSDR: cannot set %.*s\n",
			       (int)(key_end - key), key);
			return CMD_RET_FAILURE;
		}
		imported++;
	}

	printf("ANTSDR: imported %u locked uEnv value(s)\n", imported);
	return CMD_RET_SUCCESS;
}

static int do_antsdr_uenv(cmd_tbl_t *cmdtp, int flag, int argc,
			  char * const argv[])
{
	ulong address;
	ulong size;

	if (argc != 3)
		return CMD_RET_USAGE;

	address = simple_strtoul(argv[1], NULL, 16);
	size = simple_strtoul(argv[2], NULL, 16);
	if (!address || !size || size > ANTSDR_UENV_MAX_SIZE) {
		printf("ANTSDR: invalid uEnv buffer\n");
		return CMD_RET_FAILURE;
	}

	return antsdr_uenv_import((const char *)(uintptr_t)address, size);
}

U_BOOT_CMD(
	antsdr_uenv, 3, 0, do_antsdr_uenv,
	"import approved ANTSDR uEnv variables",
	"<address> <size>\n"
	"    - imports only rf_model and rf_topology"
);
