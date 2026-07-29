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
