// Copyright 2015 Ettus Research, a National Instruments Company
// Copyright 2021-2024 MicroPhase Inc.
// Copyright 2026 Cyfrit <i@cli.tf>
//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Derived from the Ettus Research B205 reference PLL. The E310 extensions add
// reference classification, a manual DAC mode, and LTC2630 output support.

`timescale 1ns/100ps

module e310_ref_pll #(
  parameter [15:0] HOLDOVER_DAC = 16'd42580
) (
  input             reset,
  input             sample_clock,
  input             reference_clock,
  input             external_reference,
  input             manual_mode,
  input      [15:0] manual_dac,
  output reg        locked,
  output reg        reference_is_10m,
  output reg        reference_is_pps,
  output     [15:0] active_dac,
  output            dac_sclk,
  output            dac_mosi,
  output            dac_sync_n
);

  localparam integer SAMPLE_CLOCK_HZ = 200000000;
  localparam integer REFERENCE_CLOCK_HZ = 40000000;
  localparam integer PFD_10M_HZ = 10;
  localparam integer PFD_PPS_HZ = 1;

  localparam integer REF_10M_PERIOD = SAMPLE_CLOCK_HZ / 10000000;
  localparam integer REF_PPS_PERIOD = SAMPLE_CLOCK_HZ;
  localparam integer REF_10M_MIN = REF_10M_PERIOD - 1;
  localparam integer REF_10M_MAX = REF_10M_PERIOD + 1;
  localparam integer REF_PPS_MARGIN = SAMPLE_CLOCK_HZ / 5000;
  localparam integer REF_PPS_MIN = REF_PPS_PERIOD - REF_PPS_MARGIN;
  localparam integer REF_PPS_MAX = REF_PPS_PERIOD + REF_PPS_MARGIN;

  localparam integer RDIV_10M = 10000000 / PFD_10M_HZ;
  localparam integer RDIV_PPS = 1;
  localparam integer NDIV_10M = (REFERENCE_CLOCK_HZ / 2) / PFD_10M_HZ;
  localparam integer NDIV_PPS = REFERENCE_CLOCK_HZ / 2;
  localparam integer PFD_PERIOD_10M = SAMPLE_CLOCK_HZ / PFD_10M_HZ;
  localparam integer PFD_PERIOD_PPS = SAMPLE_CLOCK_HZ;
  localparam integer LOCK_MARGIN_10M = PFD_PERIOD_10M / 1000000;
  localparam integer LOCK_MARGIN_PPS = PFD_PERIOD_PPS / 1000000;

  reg reference_clock_div2;
  (* ASYNC_REG = "TRUE" *) reg [3:0] external_reference_sync;
  (* ASYNC_REG = "TRUE" *) reg [3:0] reference_clock_sync;

  wire external_reference_rising = external_reference_sync[3:2] == 2'b01;
  wire reference_clock_rising = reference_clock_sync[3:2] == 2'b01;

  always @(posedge reference_clock or posedge reset) begin
    if (reset)
      reference_clock_div2 <= 1'b0;
    else
      reference_clock_div2 <= !reference_clock_div2;
  end

  always @(posedge sample_clock) begin
    if (reset) begin
      external_reference_sync <= 4'd0;
      reference_clock_sync <= 4'd0;
    end else begin
      external_reference_sync <= {external_reference_sync[2:0], external_reference};
      reference_clock_sync <= {reference_clock_sync[2:0], reference_clock_div2};
    end
  end

  reg        reference_seen;
  reg [31:0] reference_period_count;

  always @(posedge sample_clock) begin
    if (reset) begin
      reference_seen <= 1'b0;
      reference_period_count <= 32'd0;
      reference_is_10m <= 1'b0;
      reference_is_pps <= 1'b0;
    end else if (external_reference_rising) begin
      if (reference_seen) begin
        reference_is_10m <=
          reference_period_count >= REF_10M_MIN &&
          reference_period_count <= REF_10M_MAX;
        reference_is_pps <=
          reference_period_count >= REF_PPS_MIN &&
          reference_period_count <= REF_PPS_MAX;
      end
      reference_seen <= 1'b1;
      reference_period_count <= 32'd1;
    end else if (reference_seen) begin
      if (reference_period_count > REF_PPS_MAX) begin
        reference_seen <= 1'b0;
        reference_period_count <= 32'd0;
        reference_is_10m <= 1'b0;
        reference_is_pps <= 1'b0;
      end else begin
        reference_period_count <= reference_period_count + 1'b1;
      end
    end
  end

  wire valid_reference = reference_is_10m || reference_is_pps;
  wire [23:0] r_divider = reference_is_10m ? RDIV_10M : RDIV_PPS;
  wire [25:0] n_divider = reference_is_10m ? NDIV_10M : NDIV_PPS;

  reg [23:0] r_count;
  reg        r_rising;
  always @(posedge sample_clock) begin
    if (reset || !valid_reference) begin
      r_count <= 24'd0;
      r_rising <= 1'b0;
    end else begin
      r_rising <= 1'b0;
      if (external_reference_rising) begin
        if (r_count == r_divider - 1'b1) begin
          r_count <= 24'd0;
          r_rising <= 1'b1;
        end else begin
          r_count <= r_count + 1'b1;
        end
      end
    end
  end

  reg [25:0] n_count;
  reg        n_rising;
  always @(posedge sample_clock) begin
    if (reset || !valid_reference) begin
      n_count <= 26'd0;
      n_rising <= 1'b0;
    end else begin
      n_rising <= 1'b0;
      if (reference_clock_rising) begin
        if (n_count == n_divider - 1'b1) begin
          n_count <= 26'd0;
          n_rising <= 1'b1;
        end else begin
          n_count <= n_count + 1'b1;
        end
      end
    end
  end

  wire signed [28:0] expected_period =
    reference_is_10m ? PFD_PERIOD_10M : PFD_PERIOD_PPS;
  reg signed [28:0] measured_period;
  reg signed [28:0] frequency_error;

  always @(posedge sample_clock) begin
    if (reset || !valid_reference) begin
      measured_period <= 29'sd0;
      frequency_error <= 29'sd0;
    end else if (r_rising) begin
      measured_period <= 29'sd1;
      frequency_error <= expected_period - measured_period;
    end else begin
      measured_period <= measured_period + 1'b1;
    end
  end

  reg signed [28:0] lead_count;
  reg               lead_count_enable;
  reg signed [28:0] lead;

  always @(posedge sample_clock) begin
    if (reset || !valid_reference) begin
      lead_count <= 29'sd0;
      lead_count_enable <= 1'b0;
      lead <= 29'sd0;
    end else if (n_rising) begin
      lead_count <= 29'sd0;
      lead_count_enable <= 1'b1;
      if (r_rising)
        lead <= 29'sd0;
    end else if (r_rising) begin
      if (lead_count_enable)
        lead <= lead_count - 1'b1;
      else
        lead <= 29'sd1;
      lead_count_enable <= 1'b0;
    end else if (lead_count_enable) begin
      lead_count <= lead_count - 1'b1;
    end
  end

  localparam [3:0] MEASURE = 4'd0;
  localparam [3:0] CAPTURE = 4'd1;
  localparam [3:0] CAPTURE_LAG = 4'd2;
  localparam [3:0] CAPTURE_LEAD = 4'd3;
  localparam [3:0] CALCULATE_ERROR = 4'd4;
  localparam [3:0] CALCULATE_10M_GAIN = 4'd5;
  localparam [3:0] CALCULATE_ADJUSTMENT = 4'd6;
  localparam [3:0] CALCULATE_OUTPUT = 4'd7;
  localparam [3:0] APPLY_OUTPUT = 4'd8;

  wire signed [28:0] lock_margin =
    reference_is_10m ? LOCK_MARGIN_10M : LOCK_MARGIN_PPS;
  wire signed [28:0] lag = lead + expected_period;
  reg signed [28:0] phase_error;
  reg signed [28:0] combined_error;
  reg signed [28:0] gain_shift;
  reg signed [28:0] adjustment;
  reg signed [28:0] dac_sum;
  reg        [15:0] automatic_dac;
  reg        [ 2:0] lock_history;
  reg        [ 3:0] state;

  always @(posedge sample_clock) begin
    if (reset || !valid_reference) begin
      state <= MEASURE;
      automatic_dac <= HOLDOVER_DAC;
      phase_error <= 29'sd0;
      combined_error <= 29'sd0;
      gain_shift <= 29'sd0;
      adjustment <= 29'sd0;
      dac_sum <= 29'sd0;
      lock_history <= 3'd0;
    end else begin
      case (state)
        MEASURE: begin
          if (r_rising)
            state <= CAPTURE;
        end
        CAPTURE: begin
          state <= lag < -lead ? CAPTURE_LAG : CAPTURE_LEAD;
        end
        CAPTURE_LAG: begin
          phase_error <= lag;
          lock_history <= {lock_history[1:0], lag <= lock_margin};
          state <= CALCULATE_ERROR;
        end
        CAPTURE_LEAD: begin
          phase_error <= lead;
          lock_history <= {lock_history[1:0], -lead <= lock_margin};
          state <= CALCULATE_ERROR;
        end
        CALCULATE_ERROR: begin
          combined_error <= phase_error + frequency_error;
          state <= reference_is_10m ? CALCULATE_10M_GAIN : CALCULATE_ADJUSTMENT;
        end
        CALCULATE_10M_GAIN: begin
          gain_shift <=
            combined_error < -7 || combined_error > 7 ? 7 :
            combined_error < 0 ? -combined_error : combined_error;
          state <= CALCULATE_ADJUSTMENT;
        end
        CALCULATE_ADJUSTMENT: begin
          adjustment <= reference_is_10m ?
            combined_error <<< gain_shift :
            (combined_error <<< 4) - combined_error;
          state <= CALCULATE_OUTPUT;
        end
        CALCULATE_OUTPUT: begin
          dac_sum <= {13'd0, automatic_dac} + adjustment;
          state <= APPLY_OUTPUT;
        end
        APPLY_OUTPUT: begin
          if (dac_sum < 0)
            automatic_dac <= 16'd0;
          else if (dac_sum > 65535)
            automatic_dac <= 16'hffff;
          else
            automatic_dac <= dac_sum[15:0];
          state <= MEASURE;
        end
        default: state <= MEASURE;
      endcase
    end
  end

  always @(posedge sample_clock) begin
    if (reset || !valid_reference)
      locked <= 1'b0;
    else
      locked <= &lock_history;
  end

  assign active_dac = manual_mode ? manual_dac : automatic_dac;

  ltc2630_spi i_dac (
    .clk (sample_clock),
    .reset (reset),
    .value (active_dac),
    .sclk (dac_sclk),
    .mosi (dac_mosi),
    .sync_n (dac_sync_n)
  );

endmodule
