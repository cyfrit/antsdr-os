#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Install the pinned AMD toolchain into the expanded CI workspace.

set -euo pipefail

readonly VIVADO_VERSION=2023.2
readonly AMD_SIGNING_FINGERPRINT=745F4D5B2402441F410FBD0D85D4B4BB1D692FDB
readonly AMD_SIGNING_KEY_URL=https://www.xilinx.com/support/download/2018-2-1/xilinx-master-signing-key.asc

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    printf 'required environment variable %s is not set\n' "$name" >&2
    exit 2
  fi
}

for variable in GITHUB_WORKSPACE GITHUB_ENV AMD_WEB_INSTALLER_URL AMD_WEB_INSTALLER_SIGNATURE_URL AMD_USERNAME AMD_PASSWORD; do
  require_env "$variable"
done

install_root="${XILINX_INSTALL_ROOT:-$GITHUB_WORKSPACE/.toolchains/Xilinx}"
case "$install_root" in
  "$GITHUB_WORKSPACE"/*) ;;
  *)
    printf 'XILINX_INSTALL_ROOT must be within GITHUB_WORKSPACE\n' >&2
    exit 2
    ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work_root="$GITHUB_WORKSPACE/.ci-vivado-installer"
installer="$work_root/FPGAs_AdaptiveSoCs_Unified_${VIVADO_VERSION}_1013_2256_Lin64.bin"
signature="$installer.sig"
client="$work_root/client"
gnupg_home="$work_root/gnupg"
config="$work_root/install_config.txt"

rm -rf "$work_root"
mkdir -p "$client" "$gnupg_home" "$install_root"
chmod 700 "$gnupg_home"

curl --fail --location --retry 3 --retry-all-errors --output "$installer" "$AMD_WEB_INSTALLER_URL"
curl --fail --location --retry 3 --retry-all-errors --output "$signature" "$AMD_WEB_INSTALLER_SIGNATURE_URL"
curl --fail --location --retry 3 --retry-all-errors --output "$work_root/xilinx-master-signing-key.asc" "$AMD_SIGNING_KEY_URL"

export GNUPGHOME="$gnupg_home"
gpg --batch --import "$work_root/xilinx-master-signing-key.asc"
actual_fingerprint="$(gpg --batch --with-colons --fingerprint 85D4B4BB1D692FDB | awk -F: '$1 == "fpr" { print $10; exit }')"
test "$actual_fingerprint" = "$AMD_SIGNING_FINGERPRINT"
gpg --batch --verify "$signature" "$installer"

chmod +x "$installer"
"$installer" --keep --noexec --target "$client"

# AMD's web installer stores a seven-day authentication token below HOME.
# Generate it per workflow from repository secrets instead of persisting one.
export HOME="$work_root/home"
export client
mkdir -p "$HOME"
expect <<'EOF'
set timeout 120
log_user 0
spawn "$env(client)/xsetup" -b AuthTokenGen
expect "E-mail Address:"
send -- "$env(AMD_USERNAME)\r"
expect "Password:"
send -- "$env(AMD_PASSWORD)\r"
expect eof
EOF

sed "s|@DESTINATION@|$install_root|g" "$repo_root/ci/vivado/install_config.txt.in" > "$config"
"$client/xsetup" --agree XilinxEULA,3rdPartyEULA --batch Install --config "$config"

settings="$install_root/Vitis/$VIVADO_VERSION/settings64.sh"
test -r "$settings"
# shellcheck disable=SC1090
source "$settings"
command -v vivado
command -v xsct
command -v bootgen
vivado -version | grep -F "$VIVADO_VERSION"

{
  printf 'VIVADO_SETTINGS=%s\n' "$settings"
  printf 'XILINX_INSTALL_ROOT=%s\n' "$install_root"
  printf 'ANTSDR_BUILD_ROOT=%s\n' "$GITHUB_WORKSPACE/.ci-build"
} >> "$GITHUB_ENV"
