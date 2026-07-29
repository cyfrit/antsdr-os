// SPDX-License-Identifier: MIT
// Copyright (C) 2026 Cyfrit <i@cli.tf>

`timescale 1ns/100ps

module ltc2630_spi #(
  parameter integer CLOCK_DIVIDER = 8
) (
  input             clk,
  input             reset,
  input      [15:0] value,
  output reg        sclk,
  output            mosi,
  output reg        sync_n
);

  localparam [1:0] IDLE = 2'd0;
  localparam [1:0] TRANSFER = 2'd1;
  localparam [1:0] FINISH = 2'd2;

  reg [ 1:0] state;
  reg [15:0] last_value;
  reg [15:0] transfer_value;
  reg        last_value_valid;
  reg [23:0] shift_register;
  reg [ 4:0] bit_count;
  reg [15:0] divider;

  assign mosi = shift_register[23];

  always @(posedge clk) begin
    if (reset) begin
      state <= IDLE;
      last_value <= 16'd0;
      transfer_value <= 16'd0;
      last_value_valid <= 1'b0;
      shift_register <= 24'd0;
      bit_count <= 5'd0;
      divider <= 16'd0;
      sclk <= 1'b0;
      sync_n <= 1'b1;
    end else begin
      case (state)
        IDLE: begin
          sclk <= 1'b0;
          sync_n <= 1'b1;
          divider <= 16'd0;
          if (!last_value_valid || value != last_value) begin
            // LTC2630 command 0x3: write and update DAC register.
            shift_register <= {8'h30, value};
            transfer_value <= value;
            bit_count <= 5'd0;
            sync_n <= 1'b0;
            state <= TRANSFER;
          end
        end

        TRANSFER: begin
          if (divider == CLOCK_DIVIDER - 1) begin
            divider <= 16'd0;
            if (!sclk) begin
              sclk <= 1'b1;
            end else begin
              sclk <= 1'b0;
              if (bit_count == 5'd23) begin
                state <= FINISH;
              end else begin
                bit_count <= bit_count + 1'b1;
                shift_register <= {shift_register[22:0], 1'b0};
              end
            end
          end else begin
            divider <= divider + 1'b1;
          end
        end

        FINISH: begin
          // Keep SYNC low for one 200 MHz cycle after the final falling edge.
          sync_n <= 1'b1;
          // Record the value actually shifted, not a value that changed mid-frame.
          last_value <= transfer_value;
          last_value_valid <= 1'b1;
          state <= IDLE;
        end

        default: state <= IDLE;
      endcase
    end
  end

endmodule
