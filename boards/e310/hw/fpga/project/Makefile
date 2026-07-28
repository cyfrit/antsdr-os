####################################################################################
## Copyright (C) 2018-2024 Analog Devices, Inc. All rights reserved.
### SPDX short identifier: BSD-1-Clause
####################################################################################

PROJECT_NAME := e310

M_DEPS += ../common/xilinx/adi_fir_filter_constr.xdc
M_DEPS += ../common/xilinx/adi_fir_filter_bd.tcl
M_DEPS += ../../library/util_cdc/sync_bits.v
M_DEPS += ../../library/common/util_pulse_gen.v
M_DEPS += ../../library/common/ad_iobuf.v
M_DEPS += ../../library/common/ad_bus_mux.v
M_DEPS += ../../library/axi_tdd/scripts/axi_tdd.tcl
M_DEPS += ../../library/axi_ad9361/axi_ad9361_delay.tcl

LIB_DEPS += axi_ad9361
LIB_DEPS += axi_dmac
LIB_DEPS += axi_e310_vcxo_ctrl
LIB_DEPS += axi_tdd
LIB_DEPS += util_pack/util_cpack2
LIB_DEPS += util_pack/util_upack2

include ../scripts/project-xilinx.mk
