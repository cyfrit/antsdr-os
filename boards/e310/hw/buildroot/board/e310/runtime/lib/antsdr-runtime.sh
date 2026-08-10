#!/bin/sh
# SPDX-License-Identifier: MIT
# Shared side-effect-free discovery helpers for AntSDR OS runtime services.

ANTSDR_BOARD_CONF=${ANTSDR_BOARD_CONF:-/etc/antsdr/board.conf}
if [ -r "$ANTSDR_BOARD_CONF" ]; then
    # shellcheck disable=SC1090
    . "$ANTSDR_BOARD_CONF"
fi

antsdr_is_mounted() {
    grep -qs " $1 " /proc/mounts
}

antsdr_find_iio_device() {
    for candidate in /sys/bus/iio/devices/iio:device*; do
        [ -r "$candidate/name" ] || continue
        candidate_name=$(cat "$candidate/name")
        for expected_name do
            if [ "$candidate_name" = "$expected_name" ]; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done
    done
    return 1
}

antsdr_sha256_file() {
    sha256sum "$1" | awk '{print $1}'
}

antsdr_pid_matches() {
    pid_file=$1
    executable=$2
    [ -r "$pid_file" ] || return 1
    pid=$(cat "$pid_file")
    [ -n "$pid" ] || return 1
    [ "$(readlink "/proc/$pid/exe" 2>/dev/null || true)" = "$executable" ]
}

antsdr_persist_layout_status() {
    [ -n "${PERSIST_MTD_BLOCK_DEVICE:-}" ] &&
    [ -n "${PERSIST_MTD_DEVICE:-}" ] &&
    [ -n "${PERSIST_MTD_SYSFS:-}" ] &&
    [ -n "${PERSIST_MTD_LABEL:-}" ] &&
    [ -n "${PERSIST_MTD_SIZE_BYTES:-}" ] || {
        printf '%s\n' 'persistent storage is not defined for this hardware'
        return 1
    }
    [ -b "$PERSIST_MTD_BLOCK_DEVICE" ] || {
        printf '%s is unavailable\n' "$PERSIST_MTD_BLOCK_DEVICE"
        return 1
    }
    [ -r "$PERSIST_MTD_SYSFS/name" ] || {
        printf '%s metadata is unavailable\n' "$PERSIST_MTD_NAME"
        return 1
    }
    name=$(cat "$PERSIST_MTD_SYSFS/name")
    [ "$name" = "$PERSIST_MTD_LABEL" ] || {
        printf '%s is %s, expected %s\n' "$PERSIST_MTD_NAME" "$name" "$PERSIST_MTD_LABEL"
        return 1
    }
    size=$(cat "$PERSIST_MTD_SYSFS/size" 2>/dev/null || true)
    [ "$size" = "$PERSIST_MTD_SIZE_BYTES" ] || {
        printf '%s size is %s, expected %s\n' \
            "$PERSIST_MTD_LABEL" "${size:-unknown}" "$PERSIST_MTD_SIZE_BYTES"
        return 1
    }
}

antsdr_persist_media_status() {
    if ! reason=$(antsdr_persist_layout_status); then
        printf '%s\n' "$reason"
        return 1
    fi
    signature=$(od -An -N2 -tx1 "$PERSIST_MTD_DEVICE" 2>/dev/null | tr -d ' \n')
    case "$signature" in
        8519|ffff) return 0 ;;
        *)
            printf '%s has an invalid JFFS2 header (%s)\n' \
                "$PERSIST_MTD_LABEL" "${signature:-unreadable}"
            return 1
            ;;
    esac
}
