/*
 * Copyright (c) 2025 Syed Alam
 * SPDX-License-Identifier: Apache-2.0
 */

module spi_peripheral (
    input wire clk,
    input wire rst_n,
    input wire sCLK,
    input wire nCS,
    input wire COPI,
    output reg [7:0] en_reg_out_7_0,
    output reg [7:0] en_reg_out_15_8,
    output reg [7:0] en_reg_pwm_7_0,
    output reg [7:0] en_reg_pwm_15_8,
    output reg [7:0] pwm_duty_cycle
);

reg instruction_bit;
reg [6:0] address;
reg [7:0] data;
reg [5:0] bit_counter;
reg nCS_reg, nCS_sync, nCS_prev, sCLK_reg, sCLK_sync, sCLK_prev, COPI_reg, COPI_sync;
reg transaction_complete, transaction_processed;

always @(posedge clk or negedge rst_n)
begin
    if (!rst_n)
    begin
        nCS_reg <= 1;
        sCLK_reg <= 0;
        COPI_reg <= 0;
        nCS_sync <= 1;
        sCLK_sync <= 0;
        COPI_sync <= 0;
        nCS_prev <= 1;
        sCLK_prev <= 0;
        instruction_bit <= 0;
        address <= 0;
        data <= 0;
        transaction_complete <= 0;
        bit_counter <= 0;
    end else begin
        nCS_reg <= nCS;
        sCLK_reg <= sCLK;
        COPI_reg <= COPI;
        nCS_sync <= nCS_reg;
        sCLK_sync <= sCLK_reg;
        COPI_sync <= COPI_reg;
        nCS_prev <= nCS_sync;
        sCLK_prev <= sCLK_sync;

        // start of transaction: clear capture state
        if (nCS_prev == 1 && nCS_sync == 0)
        begin
            bit_counter <= 0;
            instruction_bit <= 0;
            address <= 0;
            data <= 0;
        end

        // sample on SCLK rising edge while nCS low
        if (nCS_sync == 0 && sCLK_prev == 0 && sCLK_sync == 1)
        begin
            if (bit_counter == 0)
            begin
                instruction_bit <= COPI_sync;
            end else if (bit_counter >= 1 && bit_counter < 8)
            begin
                address <= {address[5:0], COPI_sync};
            end else if (bit_counter >= 8 && bit_counter < 16)
            begin
                data <= {data[6:0], COPI_sync};
            end
            if (bit_counter < 16)
                bit_counter <= bit_counter + 1;
        end

        // end of transaction: commit only if exactly 16 bits captured
        if (nCS_prev == 0 && nCS_sync == 1)
        begin
            if (bit_counter == 16)
                transaction_complete <= 1;
            bit_counter <= 0; // clear on CS rise (done or abort)
        end

        // clear completion when processed
        if (transaction_processed == 1)
        begin
            transaction_complete <= 0;
        end
    end
end

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        en_reg_out_15_8 <= 0;
        en_reg_out_7_0 <= 0;
        en_reg_pwm_15_8 <= 0;
        en_reg_pwm_7_0 <= 0;
        pwm_duty_cycle <= 0;
        transaction_processed <= 0;
    end else if (transaction_complete && !transaction_processed) begin
        if (instruction_bit == 1'b1) begin
            if (address <= 7'h04) begin
                case (address[4:0])
                    5'h00: en_reg_out_7_0        <= data;
                    5'h01: en_reg_out_15_8       <= data;
                    5'h02: en_reg_pwm_7_0        <= data;
                    5'h03: en_reg_pwm_15_8       <= data;
                    5'h04: pwm_duty_cycle        <= data;
                    default: ;
                endcase
            end
        end
        transaction_processed <= 1'b1;
    end else if (transaction_complete == 0 && transaction_processed == 1) begin
        transaction_processed <= 0;
    end
end
endmodule