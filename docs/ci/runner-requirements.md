<!-- SPDX-License-Identifier: MIT -->
# ANTSDR OS CI runner requirements

The normal pull-request jobs use GitHub-hosted Ubuntu runners. They install
the small validation tool set (`cpp` and `device-tree-compiler`) at job start;
no local developer toolchain is required.

The E310 build workflow is intentionally isolated from pull requests. Its
self-hosted runner must have these labels:

```text
self-hosted, linux, x64, vivado-2023.2, isolated
```

It must provide:

- AMD Vivado 2023.2 at `/opt/Xilinx/Vivado/2023.2/settings64.sh`;
- Vitis/XSCT 2023.2 and `bootgen` from that installation;
- network access to the pinned ADI repositories and package mirrors;
- a clean disposable workspace under `$RUNNER_TEMP` for every job.

The runner must not be attached to an SDR. Build jobs only create artifacts;
they never program QSPI, SD, USB recovery, or RF hardware. The separate
`hardware-e310.yml` job is manual and read-only, and requires the labels
`self-hosted, e310-revc, isolated`.
