#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# TEMPORARY DEBUG: remove with the matching workflow block after cache validation.

set -u

label="${1:-unspecified}"
workspace="${GITHUB_WORKSPACE:-$(pwd)}"
toolchains="$workspace/.toolchains"

printf 'TEMPORARY DEBUG: %s\n' "$label"
date --utc --iso-8601=seconds
df -h / "$workspace" || true
df -i / "$workspace" || true
findmnt -T / || true
findmnt -T "$workspace" || true
free -h || true

if [ -d "$toolchains" ]; then
  du -sh "$toolchains"/* 2>/dev/null || true
  du -sh "$toolchains/Xilinx"/* 2>/dev/null || true
  du -sh "$toolchains/Xilinx"/.[!.]* 2>/dev/null || true
fi

if [ -d "$toolchains/cache/parts" ]; then
  ls -lh "$toolchains/cache/parts" || true
fi
