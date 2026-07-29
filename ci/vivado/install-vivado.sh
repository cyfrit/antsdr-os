#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Install the pinned AMD toolchain into the expanded CI workspace.

set -euo pipefail

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    printf 'required environment variable %s is not set\n' "$name" >&2
    exit 2
  fi
}

read_secret() {
  local mapping_name="$1"
  local secret_name="${!mapping_name:-}"
  if [[ ! "$secret_name" =~ ^[A-Z_][A-Z0-9_]*$ ]]; then
    printf 'invalid secret variable mapping %s\n' "$mapping_name" >&2
    exit 2
  fi
  require_env "$secret_name"
  printf '%s' "${!secret_name}"
}

require_fingerprint() {
  local expected="$1"
  if ! gpg --batch --with-colons --fingerprint --list-keys | awk -F: -v expected="$expected" '
    $1 == "fpr" && $10 == expected { found = 1 }
    END { exit(found ? 0 : 1) }
  '; then
    printf 'expected signing fingerprint %s was not imported\n' "$expected" >&2
    exit 1
  fi
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly WEB_INSTALLER_CONFIG="$repo_root/ci/vivado/web-installer.env"
if [[ ! -r "$WEB_INSTALLER_CONFIG" ]]; then
  printf 'missing Web Installer configuration: %s\n' "$WEB_INSTALLER_CONFIG" >&2
  exit 2
fi
# shellcheck disable=SC1090
source "$WEB_INSTALLER_CONFIG"

for variable in \
  GITHUB_WORKSPACE \
  GITHUB_ENV \
  VIVADO_VERSION \
  R2_S3_API_URL_ENV \
  R2_BUCKET_ENV \
  R2_INSTALLER_KEY_ENV \
  R2_ACCESS_KEY_ID_ENV \
  R2_SECRET_ACCESS_KEY_ENV \
  AMD_USERNAME_ENV \
  AMD_PASSWORD_ENV \
  VIVADO_SIGNING_KEY_URL \
  VIVADO_SIGNING_KEY_SHA256 \
  VIVADO_SIGNING_PRIMARY_FINGERPRINT \
  VIVADO_SIGNING_SUBKEY_FINGERPRINT \
  VIVADO_INSTALLER_SIGNATURE_BASE64; do
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

work_root="$GITHUB_WORKSPACE/.ci-vivado-installer"
installer="$work_root/FPGAs_AdaptiveSoCs_Unified_${VIVADO_VERSION}_1013_2256_Lin64.bin"
signature="$installer.sig"
client="$work_root/client"
gnupg_home="$work_root/gnupg"
config="$work_root/install_config.txt"
signing_key="$work_root/xilinx-master-signing-key.asc"

rm -rf "$work_root"
mkdir -p "$client" "$gnupg_home" "$install_root"
chmod 700 "$gnupg_home"

r2_access_key_id="$(read_secret R2_ACCESS_KEY_ID_ENV)"
r2_secret_access_key="$(read_secret R2_SECRET_ACCESS_KEY_ENV)"
r2_s3_api_url="$(read_secret R2_S3_API_URL_ENV)"
r2_bucket="$(read_secret R2_BUCKET_ENV)"
r2_installer_key="$(read_secret R2_INSTALLER_KEY_ENV)"
case "$r2_s3_api_url" in
  https://*) ;;
  *)
    printf 'R2 S3 API URL must use HTTPS\n' >&2
    exit 2
    ;;
esac

# The secret URL is a bucket root. AWS CLI accepts the account endpoint and
# bucket separately, so derive the former only at runtime.
r2_s3_api_url="${r2_s3_api_url%/}"
case "$r2_s3_api_url" in
  */"$r2_bucket") r2_s3_endpoint="${r2_s3_api_url%/$r2_bucket}" ;;
  *)
    printf 'R2 S3 API URL does not end with its configured bucket\n' >&2
    exit 2
    ;;
esac

export AWS_ACCESS_KEY_ID="$r2_access_key_id"
export AWS_SECRET_ACCESS_KEY="$r2_secret_access_key"
export AWS_DEFAULT_REGION=auto
export AWS_EC2_METADATA_DISABLED=true
export AWS_PAGER=

aws s3api get-object \
  --endpoint-url "$r2_s3_endpoint" \
  --region auto \
  --bucket "$r2_bucket" \
  --key "$r2_installer_key" \
  "$installer" >/dev/null

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION AWS_EC2_METADATA_DISABLED AWS_PAGER
unset r2_access_key_id r2_secret_access_key r2_s3_api_url r2_s3_endpoint r2_bucket r2_installer_key

printf '%s' "$VIVADO_INSTALLER_SIGNATURE_BASE64" | base64 --decode > "$signature"
curl --fail --location --retry 3 --retry-all-errors --output "$signing_key" "$VIVADO_SIGNING_KEY_URL"
printf '%s  %s\n' "$VIVADO_SIGNING_KEY_SHA256" "$signing_key" | sha256sum --check --status

export GNUPGHOME="$gnupg_home"
gpg --batch --import "$signing_key"
require_fingerprint "$VIVADO_SIGNING_PRIMARY_FINGERPRINT"
require_fingerprint "$VIVADO_SIGNING_SUBKEY_FINGERPRINT"
if ! gpg --batch --status-fd 1 --verify "$signature" "$installer" > "$work_root/gpg-status" 2> "$work_root/gpg-verify.log"; then
  cat "$work_root/gpg-verify.log" >&2
  exit 1
fi
grep -F "[GNUPG:] VALIDSIG $VIVADO_SIGNING_SUBKEY_FINGERPRINT " "$work_root/gpg-status" >/dev/null

chmod +x "$installer"
"$installer" --keep --noexec --target "$client"

# AMD's web installer stores a seven-day authentication token below HOME.
# Generate it per workflow from repository secrets instead of persisting one.
original_home="$HOME"
export HOME="$work_root/home"
export client
mkdir -p "$HOME"
export AMD_USERNAME="$(read_secret AMD_USERNAME_ENV)"
export AMD_PASSWORD="$(read_secret AMD_PASSWORD_ENV)"
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
unset AMD_USERNAME AMD_PASSWORD

sed "s|@DESTINATION@|$install_root|g" "$repo_root/ci/vivado/install_config.txt.in" > "$config"
"$client/xsetup" --agree XilinxEULA,3rdPartyEULA --batch Install --config "$config"

settings="$install_root/Vitis/$VIVADO_VERSION/settings64.sh"
test -r "$settings"
export HOME="$original_home"
rm -rf "$work_root"
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
