# AntSDR OS

Community-maintained firmware for MicroPhase AntSDR software-defined radios.

## Supported Hardware

Current hardware support status:

| Device | Status |
| --- | --- |
| E200 | 🚧 Planned |
| E310 | ✅ Verified |
| E316 (E310v2) | 🚧 Planned |

## Installation

### Choose a Package

Download a profile archive from the
[latest AntSDR OS release](https://github.com/cyfrit/antsdr-os/releases/latest):

Choose the archive that matches the installed transceiver and required channel topology.
Verify it before extraction:

```sh
sha256sum --ignore-missing --check SHA256SUMS
```

Use one complete archive; do not combine files from different profiles.

### SD Card

1. Create a FAT32 partition on the SD card.
2. Extract the selected release archive to the root of the partition.
3. Power off the board, select SD boot mode, insert the card, and power it on.

The serial console uses `115200 8N1`. The default login for a fresh installation is
`root` with password `antsdr`.

### QSPI

First confirm that the selected archive boots successfully from SD. Keep the extracted
files on the SD card, interrupt U-Boot from the serial console, and run:

```text
run qspi_provision
```

> [!WARNING]
> QSPI provisioning replaces the QSPI boot image, selected RF profile, and FIT image.
> It also erases `qspi-nvmfs`, including saved configuration, credentials, and calibration.
> Do not remove power while the operation is in progress.

After provisioning completes successfully, the board boots the new image directly. Power
it off before changing the hardware boot mode to QSPI.

### Update an Existing QSPI Installation

1. Open the AntSDR OS USB configuration volume.
2. Extract one complete profile archive to the root of the volume.
3. Safely eject the volume and wait for it to reconnect.
4. Confirm that `FIRMWARE_UPDATE.TXT` reports success, then reboot the board.

The updater checks the package hashes and partition sizes before writing. A normal update
keeps `qspi-nvmfs`; only full `qspi_provision` resets it.

## Features

AntSDR OS is community-maintained and is not an official MicroPhase release. The table
compares its current features with
[MicroPhase firmware v0.39](https://github.com/MicroPhase/antsdr-fw-patch/tree/v0.39).

| Feature | AntSDR OS | MicroPhase firmware v0.39 |
| --- | --- | --- |
| RF configurations | Four named AD9361/AD9363 and 1R1T/2R2T profiles; SD and QSPI keep the same selection | The same RF configurations are available, but 2R2T requires manual U-Boot and `uEnv.txt` changes |
| SDR connectivity | IIO over USB and TCP, USB serial, USB storage, USB Ethernet, and physical Ethernet | Provides the core Pluto-style IIO, USB gadget, and Ethernet services |
| Network configuration | Separate USB and physical-Ethernet settings with validated DHCP/static values; RNDIS, NCM, and ECM are selectable | Provides the same network sections and USB modes, persisted by vendor scripts through the U-Boot environment |
| Device identity | Stable USB serial and network MAC addresses are derived from the board's QSPI UID | USB serial uses the QSPI UID; no stable physical-Ethernet MAC is defined by the board files |
| Persistent settings | Dedicated QSPI storage for configuration, credentials, SSH keys, calibration, and update state, with layout checks and explicit initialization | Persistent settings primarily use the U-Boot environment; no equivalent guarded storage workflow is documented |
| Firmware updates | USB-volume updates verify hashes and partition sizes; full QSPI provisioning is one explicit command | Supports FRM and multi-target DFU updates using separately generated images |
| Health and diagnostics | Login displays hardware, temperature, RF, service, and QSPI status; focused IIO and diagnostic reports are included | Displays service startup status; no equivalent health summary or diagnostic report is documented |
| Thermal monitoring | Reports SoC, RF, and Ethernet PHY temperatures and registers critical PHY protection | Exposes the PHY temperature through hwmon without an attached thermal zone |
| Boot verification | U-Boot verifies a signed FIT; releases include signed SHA-256 checksums and per-package manifests | FIT images use MD5 hashes without signature enforcement |
| Reproducible releases | Source revisions, tools, timestamps, and build identity are pinned so releases can be rebuilt consistently | Builds depend on the local Vivado installation, external toolchain, patched tree, and working-copy state |
| Hardware expansion | One OS release and package structure can contain independently validated board targets | E310, E200, and E310V2 are maintained as separate patch targets |
