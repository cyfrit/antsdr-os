#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Pack and restore the AMD toolchain as bounded cache segments.

set -euo pipefail

readonly PART_LIMIT=4
readonly PART_SIZE="${ANTSDR_CACHE_PART_SIZE:-7G}"

usage() {
  printf 'usage: %s pack|restore TOOLCHAIN_ROOT CACHE_ROOT [GENERATION]\n' "$0" >&2
  exit 2
}

manifest_value() {
  local key="$1"
  local manifest="$2"
  sed -n "s/^${key}=//p" "$manifest"
}

validate_toolchain() {
  local root="$1"
  test -r "$root/Vitis/2023.2/settings64.sh"
  test -x "$root/Vitis/2023.2/bin/xsct"
  test -x "$root/Vivado/2023.2/bin/vivado"
  test -x "$root/Vivado/2023.2/bin/bootgen"
}

pack_toolchain() {
  local toolchain_root="$1"
  local cache_root="$2"
  local generation="$3"
  local parts_root="$cache_root/parts"
  local manifest_root="$cache_root/manifest"
  local manifest="$manifest_root/toolchain.env"
  local archive_digest
  local count
  local index
  local part
  local part_digest

  [[ "$generation" =~ ^[0-9]+$ ]] || {
    printf 'cache generation must be numeric\n' >&2
    exit 2
  }
  validate_toolchain "$toolchain_root"

  rm -rf "$cache_root"
  mkdir -p "$parts_root" "$manifest_root"

  tar \
    --sparse \
    -C "$toolchain_root" \
    -cf - . | \
    zstd --quiet -T0 -3 | \
    split --bytes="$PART_SIZE" --numeric-suffixes=0 --suffix-length=2 - "$parts_root/part-"

  count="$(find "$parts_root" -maxdepth 1 -type f -name 'part-[0-9][0-9]' | wc -l)"
  if (( count < 1 || count > PART_LIMIT )); then
    printf 'compressed toolchain requires %d parts; supported range is 1..%d\n' "$count" "$PART_LIMIT" >&2
    exit 1
  fi

  archive_digest="$(cat "$parts_root"/part-* | sha256sum | awk '{print $1}')"
  {
    printf 'schema=1\n'
    printf 'generation=%s\n' "$generation"
    printf 'parts=%s\n' "$count"
    printf 'archive_sha256=%s\n' "$archive_digest"
    for ((index = 0; index < PART_LIMIT; index++)); do
      printf -v part '%s/part-%02d' "$parts_root" "$index"
      if (( index < count )); then
        part_digest="$(sha256sum "$part" | awk '{print $1}')"
        printf 'part_%02d_sha256=%s\n' "$index" "$part_digest"
      else
        : > "$part"
        printf 'part_%02d_sha256=empty\n' "$index"
      fi
    done
  } > "$manifest"
}

restore_toolchain() {
  local toolchain_root="$1"
  local cache_root="$2"
  local parts_root="$cache_root/parts"
  local manifest="$cache_root/manifest/toolchain.env"
  local archive_digest
  local expected
  local generation
  local count
  local schema
  local index
  local part
  local -a selected_parts=()

  test -r "$manifest" || return 1
  schema="$(manifest_value schema "$manifest")"
  generation="$(manifest_value generation "$manifest")"
  count="$(manifest_value parts "$manifest")"
  expected="$(manifest_value archive_sha256 "$manifest")"

  [[ "$schema" == 1 ]]
  [[ "$generation" =~ ^[0-9]+$ ]]
  [[ "$count" =~ ^[1-4]$ ]]
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]]

  for ((index = 0; index < count; index++)); do
    printf -v part '%s/part-%02d' "$parts_root" "$index"
    test -f "$part"
    expected="$(manifest_value "part_$(printf '%02d' "$index")_sha256" "$manifest")"
    [[ "$expected" =~ ^[0-9a-f]{64}$ ]]
    printf '%s  %s\n' "$expected" "$part" | sha256sum --check --status
    selected_parts+=("$part")
  done

  expected="$(manifest_value archive_sha256 "$manifest")"
  archive_digest="$(cat "${selected_parts[@]}" | sha256sum | awk '{print $1}')"
  [[ "$archive_digest" == "$expected" ]]

  rm -rf "$toolchain_root"
  mkdir -p "$toolchain_root"
  cat "${selected_parts[@]}" | zstd --quiet --decompress | tar -xf - -C "$toolchain_root"
  validate_toolchain "$toolchain_root"
}

(( $# >= 3 )) || usage
readonly mode="$1"
readonly toolchain_root="$2"
readonly cache_root="$3"

case "$mode" in
  pack)
    (( $# == 4 )) || usage
    pack_toolchain "$toolchain_root" "$cache_root" "$4"
    ;;
  restore)
    (( $# == 3 )) || usage
    restore_toolchain "$toolchain_root" "$cache_root"
    ;;
  *)
    usage
    ;;
esac
