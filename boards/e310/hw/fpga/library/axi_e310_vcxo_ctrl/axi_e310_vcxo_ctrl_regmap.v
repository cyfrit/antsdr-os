// SPDX-License-Identifier: MIT
// Copyright (C) 2026 Cyfrit <i@cli.tf>

`timescale 1ns/100ps

module axi_e310_vcxo_ctrl_regmap (
  input             up_rstn,
  input             up_clk,
  input             up_wreq,
  input      [13:0] up_waddr,
  input      [31:0] up_wdata,
  output reg        up_wack,
  input             up_rreq,
  input      [13:0] up_raddr,
  output reg [31:0] up_rdata,
  output reg        up_rack,

  output reg        manual_mode,
  output reg [15:0] manual_dac,
  output reg [ 1:0] reference_select,
  input      [15:0] active_dac,
  input      [ 2:0] reference_status
);

  localparam [31:0] CORE_VERSION = 32'h00010000;

  localparam [3:0] REG_CONTROL   = 4'h0;
  localparam [3:0] REG_MANUAL    = 4'h1;
  localparam [3:0] REG_ACTIVE    = 4'h2;
  localparam [3:0] REG_REFERENCE = 4'h3;
  localparam [3:0] REG_STATUS    = 4'h4;
  localparam [3:0] REG_VERSION   = 4'h5;

  always @(posedge up_clk) begin
    if (!up_rstn) begin
      up_wack <= 1'b0;
      manual_mode <= 1'b0;
      manual_dac <= 16'd0;
      reference_select <= 2'b00;
    end else begin
      up_wack <= up_wreq;
      if (up_wreq) begin
        case (up_waddr[3:0])
          REG_CONTROL: manual_mode <= up_wdata[0];
          REG_MANUAL: manual_dac <= up_wdata[15:0];
          REG_REFERENCE: reference_select <= up_wdata[1:0];
          default: begin
            manual_mode <= manual_mode;
            manual_dac <= manual_dac;
            reference_select <= reference_select;
          end
        endcase
      end
    end
  end

  always @(posedge up_clk) begin
    if (!up_rstn) begin
      up_rack <= 1'b0;
      up_rdata <= 32'd0;
    end else begin
      up_rack <= up_rreq;
      if (up_rreq) begin
        case (up_raddr[3:0])
          REG_CONTROL: up_rdata <= {31'd0, manual_mode};
          REG_MANUAL: up_rdata <= {16'd0, manual_dac};
          REG_ACTIVE: up_rdata <= {16'd0, active_dac};
          REG_REFERENCE: up_rdata <= {30'd0, reference_select};
          REG_STATUS: up_rdata <= {29'd0, reference_status};
          REG_VERSION: up_rdata <= CORE_VERSION;
          default: up_rdata <= 32'd0;
        endcase
      end
    end
  end

endmodule
