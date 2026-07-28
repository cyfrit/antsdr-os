// SPDX-License-Identifier: MIT
// Copyright (C) 2026 ANTSDR Firmware contributors

`timescale 1ns/100ps

module axi_e310_vcxo_ctrl #(
  parameter [15:0] HOLDOVER_DAC = 16'd42580
) (
  input             clk_40m_in,
  input             ref_10m_in,
  input             pps_in,
  output            dac_sclk,
  output            dac_mosi,
  output            dac_sync_n,
  output            ref_10m_locked,
  output            pps_locked,

  input             s_axi_aclk,
  input             s_axi_aresetn,
  input             s_axi_awvalid,
  input      [15:0] s_axi_awaddr,
  output            s_axi_awready,
  input             s_axi_wvalid,
  input      [31:0] s_axi_wdata,
  input      [ 3:0] s_axi_wstrb,
  output            s_axi_wready,
  output            s_axi_bvalid,
  output     [ 1:0] s_axi_bresp,
  input             s_axi_bready,
  input             s_axi_arvalid,
  input      [15:0] s_axi_araddr,
  output            s_axi_arready,
  output            s_axi_rvalid,
  output     [31:0] s_axi_rdata,
  output     [ 1:0] s_axi_rresp,
  input             s_axi_rready,
  input      [ 2:0] s_axi_awprot,
  input      [ 2:0] s_axi_arprot
);

  wire            up_wreq;
  wire    [13:0]  up_waddr;
  wire    [31:0]  up_wdata;
  wire            up_wack;
  wire            up_rreq;
  wire    [13:0]  up_raddr;
  wire    [31:0]  up_rdata;
  wire            up_rack;

  wire            manual_mode_axi;
  wire    [15:0]  manual_dac_axi;
  wire    [ 1:0]  reference_select_axi;
  reg     [15:0]  active_dac_axi;
  reg     [ 2:0]  reference_status_axi;

  wire            pll_feedback;
  wire            clk_200m_raw;
  wire            clk_40m_raw;
  wire            clk_200m;
  wire            clk_40m;
  wire            clock_pll_locked;

  (* ASYNC_REG = "TRUE" *) reg [1:0] manual_mode_sync;
  (* ASYNC_REG = "TRUE" *) reg [31:0] manual_dac_sync;
  (* ASYNC_REG = "TRUE" *) reg [3:0] reference_select_sync;
  (* ASYNC_REG = "TRUE" *) reg [31:0] active_dac_sync;
  (* ASYNC_REG = "TRUE" *) reg [5:0] reference_status_sync;

  wire            manual_mode = manual_mode_sync[1];
  wire    [15:0]  manual_dac = manual_dac_sync[31:16];
  wire    [ 1:0]  reference_select = reference_select_sync[3:2];
  wire            selected_reference =
    reference_select == 2'd0 ? ref_10m_in :
    reference_select == 2'd1 ? pps_in : 1'b0;

  wire    [15:0]  active_dac;
  wire            reference_locked;
  wire            reference_is_10m;
  wire            reference_is_pps;

  assign ref_10m_locked = reference_locked && reference_is_10m;
  assign pps_locked = reference_locked && reference_is_pps;

  PLLE2_ADV #(
    .BANDWIDTH ("OPTIMIZED"),
    .COMPENSATION ("INTERNAL"),
    .DIVCLK_DIVIDE (1),
    .CLKFBOUT_MULT (30),
    .CLKOUT0_DIVIDE (6),
    .CLKOUT1_DIVIDE (30),
    .CLKIN1_PERIOD (25.0)
  ) i_clock_pll (
    .CLKIN1 (clk_40m_in),
    .CLKIN2 (1'b0),
    .CLKINSEL (1'b1),
    .CLKFBIN (pll_feedback),
    .CLKFBOUT (pll_feedback),
    .CLKOUT0 (clk_200m_raw),
    .CLKOUT1 (clk_40m_raw),
    .CLKOUT2 (),
    .CLKOUT3 (),
    .CLKOUT4 (),
    .CLKOUT5 (),
    .LOCKED (clock_pll_locked),
    .PWRDWN (1'b0),
    .RST (1'b0),
    .DADDR (7'd0),
    .DCLK (1'b0),
    .DEN (1'b0),
    .DI (16'd0),
    .DO (),
    .DRDY (),
    .DWE (1'b0),
    .PSCLK (1'b0),
    .PSEN (1'b0),
    .PSINCDEC (1'b0),
    .PSDONE ()
  );

  BUFG i_clk_200m_bufg (.I (clk_200m_raw), .O (clk_200m));
  BUFG i_clk_40m_bufg (.I (clk_40m_raw), .O (clk_40m));

  always @(posedge clk_200m or negedge clock_pll_locked) begin
    if (!clock_pll_locked) begin
      manual_mode_sync <= 2'd0;
      manual_dac_sync <= 32'd0;
      reference_select_sync <= 4'd0;
    end else begin
      manual_mode_sync <= {manual_mode_sync[0], manual_mode_axi};
      manual_dac_sync <= {manual_dac_sync[15:0], manual_dac_axi};
      reference_select_sync <= {reference_select_sync[1:0], reference_select_axi};
    end
  end

  always @(posedge s_axi_aclk) begin
    if (!s_axi_aresetn) begin
      active_dac_sync <= 32'd0;
      reference_status_sync <= 6'd0;
      active_dac_axi <= 16'd0;
      reference_status_axi <= 3'd0;
    end else begin
      active_dac_sync <= {active_dac_sync[15:0], active_dac};
      reference_status_sync <= {
        reference_status_sync[2:0],
        reference_is_pps,
        reference_is_10m,
        reference_locked
      };
      active_dac_axi <= active_dac_sync[31:16];
      reference_status_axi <= reference_status_sync[5:3];
    end
  end

  e310_ref_pll #(
    .HOLDOVER_DAC (HOLDOVER_DAC)
  ) i_reference_pll (
    .reset (!clock_pll_locked),
    .sample_clock (clk_200m),
    .reference_clock (clk_40m),
    .external_reference (selected_reference),
    .manual_mode (manual_mode),
    .manual_dac (manual_dac),
    .locked (reference_locked),
    .reference_is_10m (reference_is_10m),
    .reference_is_pps (reference_is_pps),
    .active_dac (active_dac),
    .dac_sclk (dac_sclk),
    .dac_mosi (dac_mosi),
    .dac_sync_n (dac_sync_n)
  );

  axi_e310_vcxo_ctrl_regmap i_regmap (
    .up_rstn (s_axi_aresetn),
    .up_clk (s_axi_aclk),
    .up_wreq (up_wreq),
    .up_waddr (up_waddr),
    .up_wdata (up_wdata),
    .up_wack (up_wack),
    .up_rreq (up_rreq),
    .up_raddr (up_raddr),
    .up_rdata (up_rdata),
    .up_rack (up_rack),
    .manual_mode (manual_mode_axi),
    .manual_dac (manual_dac_axi),
    .reference_select (reference_select_axi),
    .active_dac (active_dac_axi),
    .reference_status (reference_status_axi)
  );

  up_axi #(
    .AXI_ADDRESS_WIDTH (16)
  ) i_up_axi (
    .up_rstn (s_axi_aresetn),
    .up_clk (s_axi_aclk),
    .up_axi_awvalid (s_axi_awvalid),
    .up_axi_awaddr (s_axi_awaddr),
    .up_axi_awready (s_axi_awready),
    .up_axi_wvalid (s_axi_wvalid),
    .up_axi_wdata (s_axi_wdata),
    .up_axi_wstrb (s_axi_wstrb),
    .up_axi_wready (s_axi_wready),
    .up_axi_bvalid (s_axi_bvalid),
    .up_axi_bresp (s_axi_bresp),
    .up_axi_bready (s_axi_bready),
    .up_axi_arvalid (s_axi_arvalid),
    .up_axi_araddr (s_axi_araddr),
    .up_axi_arready (s_axi_arready),
    .up_axi_rvalid (s_axi_rvalid),
    .up_axi_rresp (s_axi_rresp),
    .up_axi_rdata (s_axi_rdata),
    .up_axi_rready (s_axi_rready),
    .up_wreq (up_wreq),
    .up_waddr (up_waddr),
    .up_wdata (up_wdata),
    .up_wack (up_wack),
    .up_rreq (up_rreq),
    .up_raddr (up_raddr),
    .up_rdata (up_rdata),
    .up_rack (up_rack)
  );

endmodule
