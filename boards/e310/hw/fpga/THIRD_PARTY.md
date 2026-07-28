<!-- SPDX-License-Identifier: MIT -->

# FPGA source provenance

The E310 project files are derived from the ADI HDL `pluto` project and retain
their ADI license headers. They are overlaid on ADI HDL commit
`065c8f186ef87ff049d279ed5859ee8d97d91808`.

ADI's `ADIBSD` identifier is represented as `LicenseRef-ADI-BSD`. It is a
source-available, non-OSI license because it restricts use to software running
on or directly connected to an Analog Devices component. Its pinned text is in
`LICENSES/LicenseRef-ADI-BSD.txt`; it must not be normalized to a standard BSD
identifier.

`e310_ref_pll.v` is based on the Ettus Research B205 reference PLL, with the
manual DAC and reference-status extensions found in the MicroPhase E310
implementation. It remains licensed as `LGPL-3.0-or-later` and carries its SPDX
identifier in the source file.

The E310 hardware facts were cross-checked against MicroPhase
`antsdr-fw-patch` commit `58b8018d596121c220f30e00749bafbe251744a6`.
The generated MicroPhase `component.xml`, its AXI template, unrelated E200/E316
projects, and obsolete Pluto GPIO remnants are not included.
