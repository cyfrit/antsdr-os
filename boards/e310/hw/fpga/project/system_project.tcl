###############################################################################
## Copyright (C) 2014-2024 Analog Devices, Inc. All rights reserved.
### SPDX-License-Identifier: LicenseRef-ADI-BSD
###############################################################################

source ../../scripts/adi_env.tcl
source $ad_hdl_dir/projects/scripts/adi_project_xilinx.tcl
source $ad_hdl_dir/projects/scripts/adi_board.tcl

adi_project_create e310 0 {} "xc7z020clg400-2"
adi_project_files e310 [list \
  "system_top.v" \
  "system_constr.xdc" \
  "$ad_hdl_dir/library/common/ad_iobuf.v"]

# The board XDC owns the E310 pin and clock constraints. Vivado's generated
# PS7 constraints overlap that ownership and are disabled in the vendor E310
# and ADI Pluto projects for the same reason.
set_property is_enabled false [get_files *system_sys_ps7_0.xdc]

adi_project_run e310
source $ad_hdl_dir/library/axi_ad9361/axi_ad9361_delay.tcl
