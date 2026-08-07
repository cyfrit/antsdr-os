#!/bin/sh
# SPDX-License-Identifier: MIT
# Show the dynamic status banner for interactive login shells.

case "$-" in
    *i*) /usr/sbin/antsdr-motd ;;
esac
