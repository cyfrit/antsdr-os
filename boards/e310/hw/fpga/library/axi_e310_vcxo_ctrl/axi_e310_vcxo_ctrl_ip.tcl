###############################################################################
## Copyright (C) 2026 Cyfrit <i@cli.tf>
### SPDX-License-Identifier: MIT
###############################################################################

source ../../scripts/adi_env.tcl
source $ad_hdl_dir/library/scripts/adi_ip_xilinx.tcl

adi_ip_create axi_e310_vcxo_ctrl
adi_ip_files axi_e310_vcxo_ctrl [list \
  "$ad_hdl_dir/library/common/up_axi.v" \
  "axi_e310_vcxo_ctrl_regmap.v" \
  "e310_ref_pll.v" \
  "ltc2630_spi.v" \
  "axi_e310_vcxo_ctrl.v"]

adi_ip_properties axi_e310_vcxo_ctrl

set core [ipx::current_core]
set_property display_name "ANTSDR E310 VCXO Control" $core
set_property description "E310 40 MHz VCXO discipline and LTC2630 control" $core
ipx::save_core $core
