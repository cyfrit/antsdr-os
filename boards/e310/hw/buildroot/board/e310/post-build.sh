#!/bin/sh
# SPDX-License-Identifier: MIT
# Install the E310 runtime policy after Buildroot has populated TARGET_DIR.

set -eu

. "$BR2_CONFIG"

BOARD_DIR=$(dirname "$0")
RUNTIME_DIR="$BOARD_DIR/runtime"
CONFIG_PAYLOAD="$BUILD_DIR/antsdr-e310-config-volume"
GENIMAGE_TMP="$BUILD_DIR/antsdr-e310-genimage"

install -d "$TARGET_DIR/etc/antsdr" "$TARGET_DIR/opt/antsdr" \
    "$TARGET_DIR/usr/lib/antsdr" "$TARGET_DIR/www" \
    "$TARGET_DIR/mnt/antsdr-persist"

install -m 0644 "$BOARD_DIR/board.conf" "$TARGET_DIR/etc/antsdr/board.conf"
install -m 0644 "$BOARD_DIR/defaults.conf" "$TARGET_DIR/etc/antsdr/defaults.conf"
install -m 0644 "$BOARD_DIR/fw_env.config" "$TARGET_DIR/etc/fw_env.config"
install -m 0644 "$BOARD_DIR/mdev.conf" "$TARGET_DIR/etc/mdev.conf"
install -m 0644 "$BOARD_DIR/index.html" "$TARGET_DIR/www/index.html"

for program in antsdr-config antsdr-diagnostic antsdr-persist antsdr-udc-suspend; do
    install -m 0755 "$RUNTIME_DIR/sbin/$program" "$TARGET_DIR/usr/sbin/$program"
done
for service in S15antsdr-persistence S20antsdr-gadget S30antsdr-network S40antsdr-config-volume; do
    install -m 0755 "$RUNTIME_DIR/init.d/$service" "$TARGET_DIR/etc/init.d/$service"
done
install -m 0755 "$RUNTIME_DIR/libexec/net-hotplug" "$TARGET_DIR/usr/lib/antsdr/net-hotplug"
install -m 0644 "$RUNTIME_DIR/lib/antsdr-runtime.sh" "$TARGET_DIR/usr/lib/antsdr/runtime.sh"

# FunctionFS is owned by S20antsdr-gadget, so do not start a second IIOD.
rm -f "$TARGET_DIR/etc/init.d/S99iiod"

grep -q '^ttyGS0::' "$TARGET_DIR/etc/inittab" || \
    sed -i '/GENERIC_SERIAL/a\
ttyGS0::respawn:/sbin/getty -L ttyGS0 0 vt100 # USB ACM console' "$TARGET_DIR/etc/inittab"

grep -q '^mtd2 /mnt/antsdr-persist ' "$TARGET_DIR/etc/fstab" || \
    printf 'mtd2 /mnt/antsdr-persist jffs2 rw,noatime 0 0\n' >> "$TARGET_DIR/etc/fstab"

cat > "$TARGET_DIR/etc/antsdr/release" <<EOF
firmware=development
board=e310
buildroot=${BR2_VERSION_FULL:-unknown}
EOF

rm -rf "$CONFIG_PAYLOAD" "$GENIMAGE_TMP"
mkdir -p "$CONFIG_PAYLOAD"
install -m 0644 "$BOARD_DIR/config.txt" "$CONFIG_PAYLOAD/config.txt"
install -m 0644 "$BOARD_DIR/INFO.html" "$CONFIG_PAYLOAD/INFO.html"

genimage \
    --rootpath "$TARGET_DIR" \
    --tmppath "$GENIMAGE_TMP" \
    --inputpath "$CONFIG_PAYLOAD" \
    --outputpath "$TARGET_DIR/opt/antsdr" \
    --config "$BOARD_DIR/genimage-config.cfg"
