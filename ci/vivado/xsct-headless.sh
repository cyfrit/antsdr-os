#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run XSCT with a private X server on headless build hosts.

set -euo pipefail

for command in Xvfb xauth xlsclients xsct xvfb-run; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'required XSCT host command is missing: %s\n' "$command" >&2
    exit 127
  fi
done

xvfb_log="${RUNNER_TEMP:-/tmp}/xsct-xvfb.log"
status=0
xvfb-run \
  --auto-servernum \
  --error-file="$xvfb_log" \
  --server-args='-screen 0 1280x1024x24 -nolisten tcp' \
  xsct "$@" || status=$?
if (( status != 0 )); then
  if [[ -s "$xvfb_log" ]]; then
    cat "$xvfb_log" >&2
  fi
  exit "$status"
fi
