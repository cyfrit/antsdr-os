#!/bin/sh
# SPDX-License-Identifier: MIT
# Shared side-effect-free discovery helpers for E310 runtime services.

antsdr_is_mounted() {
    grep -qs " $1 " /proc/mounts
}

antsdr_find_iio_device() {
    expected_name=$1
    for candidate in /sys/bus/iio/devices/iio:device*; do
        [ -r "$candidate/name" ] || continue
        if [ "$(cat "$candidate/name")" = "$expected_name" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
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
    [ -b /dev/mtdblock2 ] || {
        printf '%s\n' 'mtdblock2 is unavailable'
        return 1
    }
    [ -r /sys/class/mtd/mtd2/name ] || {
        printf '%s\n' 'mtd2 metadata is unavailable'
        return 1
    }
    name=$(cat /sys/class/mtd/mtd2/name)
    [ "$name" = qspi-nvmfs ] || {
        printf 'mtd2 is %s, expected qspi-nvmfs\n' "$name"
        return 1
    }
    size=$(cat /sys/class/mtd/mtd2/size 2>/dev/null || true)
    case "$size" in
        917504|0xe0000|0xE0000) ;;
        *)
            printf 'qspi-nvmfs size is %s, expected 917504\n' "${size:-unknown}"
            return 1
            ;;
    esac
}

antsdr_persist_media_status() {
    if ! reason=$(antsdr_persist_layout_status); then
        printf '%s\n' "$reason"
        return 1
    fi
    signature=$(od -An -N2 -tx1 /dev/mtd2 2>/dev/null | tr -d ' \n')
    case "$signature" in
        8519|ffff) return 0 ;;
        *)
            printf 'qspi-nvmfs has an invalid JFFS2 header (%s)\n' "${signature:-unreadable}"
            return 1
            ;;
    esac
}
