// ***************************************************************************
// Copyright (C) 2014-2024 Analog Devices, Inc. All rights reserved.
//
// SPDX-License-Identifier: GPL-2.0-or-later OR LicenseRef-ADI-BSD
// ***************************************************************************

`timescale 1ns/100ps

module system_top (
  inout   [14:0]  ddr_addr,
  inout   [ 2:0]  ddr_ba,
  inout           ddr_cas_n,
  inout           ddr_ck_n,
  inout           ddr_ck_p,
  inout           ddr_cke,
  inout           ddr_cs_n,
  inout   [ 3:0]  ddr_dm,
  inout   [31:0]  ddr_dq,
  inout   [ 3:0]  ddr_dqs_n,
  inout   [ 3:0]  ddr_dqs_p,
  inout           ddr_odt,
  inout           ddr_ras_n,
  inout           ddr_reset_n,
  inout           ddr_we_n,

  inout           fixed_io_ddr_vrn,
  inout           fixed_io_ddr_vrp,
  inout   [53:0]  fixed_io_mio,
  inout           fixed_io_ps_clk,
  inout           fixed_io_ps_porb,
  inout           fixed_io_ps_srstb,

  input           rx_clk_in,
  input           rx_frame_in,
  input   [11:0]  rx_data_in,
  output          tx_clk_out,
  output          tx_frame_out,
  output  [11:0]  tx_data_out,

  output          enable,
  output          txnrx,

  inout           gpio_resetb,
  inout           gpio_en_agc,
  inout   [ 3:0]  gpio_ctl,
  inout   [ 7:0]  gpio_status,

  output          spi_csn,
  output          spi_clk,
  output          spi_mosi,
  input           spi_miso,

  input           CLK_40MHz_FPGA,
  input           PPS_IN,
  input           CLKIN_10MHz,
  output          CLKIN_10MHz_REQ,
  output          CLK_40M_DAC_nSYNC,
  output          CLK_40M_DAC_SCLK,
  output          CLK_40M_DAC_DIN,

  output          VCRX1_H,
  output          VCRX1_L,
  output          VCTX1_H,
  output          VCTX1_L,
  output          VCRX2_H,
  output          VCRX2_L,
  output          VCTX2_H,
  output          VCTX2_L
);

  wire    [63:0]  gpio_i;
  wire    [63:0]  gpio_o;
  wire    [63:0]  gpio_t;

  ad_iobuf #(
    .DATA_WIDTH (14)
  ) i_ad936x_iobuf (
    .dio_t (gpio_t[13:0]),
    .dio_i (gpio_o[13:0]),
    .dio_o (gpio_i[13:0]),
    .dio_p ({gpio_resetb, gpio_en_agc, gpio_ctl, gpio_status})
  );

  // Output-only EMIO lines use readback so Linux observes their driven value.
  assign gpio_i[63:14] = gpio_o[63:14];

  assign VCRX1_H = gpio_o[32];
  assign VCRX1_L = gpio_o[33];
  assign VCTX1_H = gpio_o[34];
  assign VCTX1_L = gpio_o[35];
  assign VCRX2_H = gpio_o[36];
  assign VCRX2_L = gpio_o[37];
  assign VCTX2_H = gpio_o[38];
  assign VCTX2_L = gpio_o[39];

  assign CLKIN_10MHz_REQ = 1'b1;

  system_wrapper i_system_wrapper (
    .CLKIN_10MHz (CLKIN_10MHz),
    .CLK_40MHz_FPGA (CLK_40MHz_FPGA),
    .CLK_40M_DAC_DIN (CLK_40M_DAC_DIN),
    .CLK_40M_DAC_SCLK (CLK_40M_DAC_SCLK),
    .CLK_40M_DAC_nSYNC (CLK_40M_DAC_nSYNC),
    .PPS_IN (PPS_IN),
    .ddr_addr (ddr_addr),
    .ddr_ba (ddr_ba),
    .ddr_cas_n (ddr_cas_n),
    .ddr_ck_n (ddr_ck_n),
    .ddr_ck_p (ddr_ck_p),
    .ddr_cke (ddr_cke),
    .ddr_cs_n (ddr_cs_n),
    .ddr_dm (ddr_dm),
    .ddr_dq (ddr_dq),
    .ddr_dqs_n (ddr_dqs_n),
    .ddr_dqs_p (ddr_dqs_p),
    .ddr_odt (ddr_odt),
    .ddr_ras_n (ddr_ras_n),
    .ddr_reset_n (ddr_reset_n),
    .ddr_we_n (ddr_we_n),
    .enable (enable),
    .fixed_io_ddr_vrn (fixed_io_ddr_vrn),
    .fixed_io_ddr_vrp (fixed_io_ddr_vrp),
    .fixed_io_mio (fixed_io_mio),
    .fixed_io_ps_clk (fixed_io_ps_clk),
    .fixed_io_ps_porb (fixed_io_ps_porb),
    .fixed_io_ps_srstb (fixed_io_ps_srstb),
    .gpio_i (gpio_i),
    .gpio_o (gpio_o),
    .gpio_t (gpio_t),
    .rx_clk_in (rx_clk_in),
    .rx_data_in (rx_data_in),
    .rx_frame_in (rx_frame_in),
    .spi0_clk_i (1'b0),
    .spi0_clk_o (spi_clk),
    .spi0_csn_0_o (spi_csn),
    .spi0_csn_1_o (),
    .spi0_csn_2_o (),
    .spi0_csn_i (1'b1),
    .spi0_sdi_i (spi_miso),
    .spi0_sdo_i (1'b0),
    .spi0_sdo_o (spi_mosi),
    .tdd_ext_sync (1'b0),
    .txdata_o (),
    .tx_clk_out (tx_clk_out),
    .tx_data_out (tx_data_out),
    .tx_frame_out (tx_frame_out),
    .txnrx (txnrx),
    .up_enable (gpio_o[15]),
    .up_txnrx (gpio_o[16])
  );

endmodule
