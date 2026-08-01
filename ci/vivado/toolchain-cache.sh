#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Pack and restore the AMD toolchain as bounded cache segments.

set -euo pipefail

readonly PART_SIZE="${ANTSDR_CACHE_PART_SIZE:-7G}"
readonly PART_SUFFIX_LENGTH=6

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
  local -a parts=()

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
    split \
      --bytes="$PART_SIZE" \
      --numeric-suffixes=0 \
      --suffix-length="$PART_SUFFIX_LENGTH" \
      - "$parts_root/part-"

  shopt -s nullglob
  parts=("$parts_root"/part-*)
  shopt -u nullglob
  count="${#parts[@]}"
  (( count >= 1 ))

  archive_digest="$(cat "${parts[@]}" | sha256sum | awk '{print $1}')"
  {
    printf 'schema=2\n'
    printf 'generation=%s\n' "$generation"
    printf 'parts=%s\n' "$count"
    printf 'part_suffix_length=%s\n' "$PART_SUFFIX_LENGTH"
    printf 'archive_sha256=%s\n' "$archive_digest"
    for ((index = 0; index < count; index++)); do
      printf -v part '%s/part-%0*d' "$parts_root" "$PART_SUFFIX_LENGTH" "$index"
      part_digest="$(sha256sum "$part" | awk '{print $1}')"
      printf 'part_%0*d_sha256=%s\n' "$PART_SUFFIX_LENGTH" "$index" "$part_digest"
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
  local actual_count
  local index
  local part
  local suffix_length
  local -a selected_parts=()

  test -r "$manifest" || return 1
  schema="$(manifest_value schema "$manifest")"
  generation="$(manifest_value generation "$manifest")"
  count="$(manifest_value parts "$manifest")"
  suffix_length="$(manifest_value part_suffix_length "$manifest")"
  expected="$(manifest_value archive_sha256 "$manifest")"

  [[ "$schema" == 2 ]]
  [[ "$generation" =~ ^[0-9]+$ ]]
  [[ "$count" =~ ^[1-9][0-9]*$ ]]
  [[ "$suffix_length" =~ ^[1-9][0-9]*$ ]]
  (( suffix_length <= 12 ))
  (( ${#count} <= suffix_length ))
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]]
  shopt -s nullglob
  selected_parts=("$parts_root"/part-*)
  shopt -u nullglob
  actual_count="${#selected_parts[@]}"
  (( actual_count == count ))
  selected_parts=()

  for ((index = 0; index < count; index++)); do
    printf -v part '%s/part-%0*d' "$parts_root" "$suffix_length" "$index"
    test -f "$part"
    expected="$(manifest_value "part_$(printf '%0*d' "$suffix_length" "$index")_sha256" "$manifest")"
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
readonly input_toolchain_root="$2"
readonly input_cache_root="$3"

case "$mode" in
  pack)
    (( $# == 4 )) || usage
    pack_toolchain "$input_toolchain_root" "$input_cache_root" "$4"
    ;;
  restore)
    (( $# == 3 )) || usage
    restore_toolchain "$input_toolchain_root" "$input_cache_root"
    ;;
  *)
    usage
    ;;
esac
