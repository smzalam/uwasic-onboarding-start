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
    input wire [7:0] en_reg_out_7_0;
    input wire [7:0] en_reg_out_15_8;
    input wire [7:0] en_reg_pwm_7_0;
    input wire [7:0] en_reg_pwm_15_8;
    input wire [7:0] pwm_duty_cycle;
);

wire instruction_bit;
wire [7:0] address;
wire [7:0] data;
reg nCS_reg, nCS_sync, sCLK_reg, sCLK_sync, COPI_reg, COPI_sync;

always @(posedge clk or negedge rst_n)
begin
    if (!rst_n)
    begin
        nCS_reg <= 1;
        sCLK_reg <= 0;
        COPI_reg <= 0;
    end else begin
        nCS_reg <= nCS;
        sCLK_reg <= sCLK;
        COPI_reg <= COPI;
        nCS_sync <= nCS_reg;
        sCLK_sync <= sCLK_reg;
        COPI_sync <= COPI_reg;

        if (nCS_sync == 0)
        begin
            if (sCLK_sync == 0)
            begin
                instruction_bit <= COPI_sync;
            end
        end
        else
        begin
            instruction_bit <= 0;
        end
    end
end

always @(posedge clk or negedge rst_n)
begin
    if (!rst_n)
    begin
        nCS_sync <= 0;
        sCLK_sync <= 0;
        COPI_sync <= 1;
    end
    else begin
        nCS_sync <= nCS_reg;
        sCLK_sync <= sCLK_reg;
        COPI_sync <= COPI_reg;
    end 
end
endmodule   

