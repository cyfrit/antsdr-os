// SPDX-License-Identifier: MIT
// Copyright (C) 2026 Cyfrit <i@cli.tf>

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
  wire            vcxo_reset_async;
  wire            vcxo_reset;

  (* ASYNC_REG = "TRUE" *) reg [2:0] vcxo_reset_release;
  (* ASYNC_REG = "TRUE" *) reg [18:0] control_bus_meta;
  (* ASYNC_REG = "TRUE" *) reg [18:0] control_bus_sync;
  (* ASYNC_REG = "TRUE" *) reg [ 2:0] control_request_sync;
  (* ASYNC_REG = "TRUE" *) reg [ 2:0] control_ack_sync;
  reg     [18:0]  control_mailbox_axi;
  reg     [18:0]  control_queued_axi;
  reg             control_request_axi;
  reg             control_ack_200m;
  reg             control_dirty_axi;
  reg             manual_mode;
  reg     [15:0]  manual_dac;
  reg     [ 1:0]  reference_select;
  (* ASYNC_REG = "TRUE" *) reg [18:0] status_bus_meta;
  (* ASYNC_REG = "TRUE" *) reg [18:0] status_bus_sync;
  (* ASYNC_REG = "TRUE" *) reg [ 2:0] status_request_sync;
  (* ASYNC_REG = "TRUE" *) reg [ 2:0] status_ack_sync;
  reg     [18:0]  status_mailbox_200m;
  reg     [18:0]  status_queued_200m;
  reg             status_request_200m;
  reg             status_ack_axi;
  reg             status_dirty_200m;

  wire            selected_reference =
    reference_select == 2'd0 ? ref_10m_in :
    reference_select == 2'd1 ? pps_in : 1'b0;

  wire    [15:0]  active_dac;
  wire            reference_locked;
  wire            reference_is_10m;
  wire            reference_is_pps;
  wire            control_pending_axi =
    control_request_axi != control_ack_sync[2];
  wire            status_pending_200m =
    status_request_200m != status_ack_sync[2];
  wire    [18:0]  status_current_200m = {
    active_dac,
    reference_is_pps,
    reference_is_10m,
    reference_locked
  };
  wire            control_write_axi = up_wreq &&
    (up_waddr[3:0] == 4'h0 || up_waddr[3:0] == 4'h1 ||
     up_waddr[3:0] == 4'h3);
  wire    [18:0]  control_write_value_axi =
    up_waddr[3:0] == 4'h0 ?
      {reference_select_axi, manual_dac_axi, up_wdata[0]} :
    up_waddr[3:0] == 4'h1 ?
      {reference_select_axi, up_wdata[15:0], manual_mode_axi} :
      {up_wdata[1:0], manual_dac_axi, manual_mode_axi};

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

  // All 200 MHz state receives an asynchronous assertion but only leaves
  // reset after three local clock edges. No PS-domain reset release reaches
  // the VCXO or DAC logic directly.
  assign vcxo_reset_async = !clock_pll_locked || !s_axi_aresetn;
  always @(posedge clk_200m or posedge vcxo_reset_async) begin
    if (vcxo_reset_async)
      vcxo_reset_release <= 3'b111;
    else
      vcxo_reset_release <= {vcxo_reset_release[1:0], 1'b0};
  end
  assign vcxo_reset = vcxo_reset_release[2];

  // The request/acknowledge pair freezes the multi-bit mailbox until the
  // receiving domain has captured it. Writes while a transfer is in flight
  // are coalesced into one subsequent mailbox update.
  always @(posedge s_axi_aclk) begin
    if (!s_axi_aresetn) begin
      control_ack_sync <= 3'd0;
      control_mailbox_axi <= 19'd0;
      control_queued_axi <= 19'd0;
      control_request_axi <= 1'b0;
      control_dirty_axi <= 1'b0;
    end else begin
      control_ack_sync <= {control_ack_sync[1:0], control_ack_200m};
      if (control_write_axi) begin
        if (control_pending_axi) begin
          control_queued_axi <= control_write_value_axi;
          control_dirty_axi <= 1'b1;
        end else begin
          control_mailbox_axi <= control_write_value_axi;
          control_request_axi <= !control_request_axi;
          control_dirty_axi <= 1'b0;
        end
      end else if (!control_pending_axi && control_dirty_axi) begin
        control_mailbox_axi <= control_queued_axi;
        control_request_axi <= !control_request_axi;
        control_dirty_axi <= 1'b0;
      end
    end
  end

  always @(posedge clk_200m or posedge vcxo_reset) begin
    if (vcxo_reset) begin
      control_bus_meta <= 19'd0;
      control_bus_sync <= 19'd0;
      control_request_sync <= 3'd0;
      control_ack_200m <= 1'b0;
      manual_mode <= 1'b0;
      manual_dac <= 16'd0;
      reference_select <= 2'd0;
    end else begin
      control_bus_meta <= control_mailbox_axi;
      control_bus_sync <= control_bus_meta;
      control_request_sync <= {
        control_request_sync[1:0],
        control_request_axi
      };
      if (control_request_sync[2] != control_ack_200m) begin
        {
          reference_select,
          manual_dac,
          manual_mode
        } <= control_bus_sync;
        control_ack_200m <= control_request_sync[2];
      end
    end
  end

  // Return VCXO state through another frozen mailbox. This prevents software
  // from observing a word assembled from two different DAC updates.
  always @(posedge clk_200m or posedge vcxo_reset) begin
    if (vcxo_reset) begin
      status_ack_sync <= 3'd0;
      status_mailbox_200m <= 19'd0;
      status_queued_200m <= 19'd0;
      status_request_200m <= 1'b0;
      status_dirty_200m <= 1'b0;
    end else begin
      status_ack_sync <= {status_ack_sync[1:0], status_ack_axi};
      if (status_current_200m != status_mailbox_200m) begin
        if (status_pending_200m) begin
          status_queued_200m <= status_current_200m;
          status_dirty_200m <= 1'b1;
        end else begin
          status_mailbox_200m <= status_current_200m;
          status_request_200m <= !status_request_200m;
          status_dirty_200m <= 1'b0;
        end
      end else if (!status_pending_200m && status_dirty_200m) begin
        status_mailbox_200m <= status_queued_200m;
        status_request_200m <= !status_request_200m;
        status_dirty_200m <= 1'b0;
      end
    end
  end

  always @(posedge s_axi_aclk) begin
    if (!s_axi_aresetn) begin
      status_bus_meta <= 19'd0;
      status_bus_sync <= 19'd0;
      status_request_sync <= 3'd0;
      status_ack_axi <= 1'b0;
      active_dac_axi <= 16'd0;
      reference_status_axi <= 3'd0;
    end else begin
      status_bus_meta <= status_mailbox_200m;
      status_bus_sync <= status_bus_meta;
      status_request_sync <= {
        status_request_sync[1:0],
        status_request_200m
      };
      if (status_request_sync[2] != status_ack_axi) begin
        active_dac_axi <= status_bus_sync[18:3];
        reference_status_axi <= status_bus_sync[2:0];
        status_ack_axi <= status_request_sync[2];
      end
    end
  end

  e310_ref_pll #(
    .HOLDOVER_DAC (HOLDOVER_DAC)
  ) i_reference_pll (
    .reset (vcxo_reset),
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
