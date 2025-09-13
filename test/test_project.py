# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, with_timeout
from cocotb.result import SimTimeoutError
from cocotb.triggers import ClockCycles
from cocotb.types import Logic
from cocotb.types import LogicArray
from cocotb.utils import get_sim_time

async def await_half_sclk(dut):
    """Wait for the SCLK signal to go high or low."""
    start_time = cocotb.utils.get_sim_time(units="ns")
    while True:
        await ClockCycles(dut.clk, 1)
        # Wait for half of the SCLK period (10 us)
        if (start_time + 100*100*0.5) < cocotb.utils.get_sim_time(units="ns"):
            break
    return

def ui_in_logicarray(ncs, bit, sclk):
    """Setup the ui_in value as a LogicArray."""
    return LogicArray(f"00000{ncs}{bit}{sclk}")

async def send_spi_transaction(dut, r_w, address, data):
    """
    Send an SPI transaction with format:
    - 1 bit for Read/Write
    - 7 bits for address
    - 8 bits for data
    
    Parameters:
    - r_w: boolean, True for write, False for read
    - address: int, 7-bit address (0-127)
    - data: LogicArray or int, 8-bit data
    """
    # Convert data to int if it's a LogicArray
    if isinstance(data, LogicArray):
        data_int = int(data)
    else:
        data_int = data
    # Validate inputs
    if address < 0 or address > 127:
        raise ValueError("Address must be 7-bit (0-127)")
    if data_int < 0 or data_int > 255:
        raise ValueError("Data must be 8-bit (0-255)")
    # Combine RW and address into first byte
    first_byte = (int(r_w) << 7) | address
    # Start transaction - pull CS low
    sclk = 0
    ncs = 0
    bit = 0
    # Set initial state with CS low
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    await ClockCycles(dut.clk, 1)
    # Send first byte (RW + Address)
    for i in range(8):
        bit = (first_byte >> (7-i)) & 0x1
        # SCLK low, set COPI
        sclk = 0
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
        # SCLK high, keep COPI
        sclk = 1
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
    # Send second byte (Data)
    for i in range(8):
        bit = (data_int >> (7-i)) & 0x1
        # SCLK low, set COPI
        sclk = 0
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
        # SCLK high, keep COPI
        sclk = 1
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
    # End transaction - return CS high
    sclk = 0
    ncs = 1
    bit = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    await ClockCycles(dut.clk, 600)
    return ui_in_logicarray(ncs, bit, sclk)

async def measure_period(sig, n_cycles=8, units="us"):
    """
    Measure period of a signal by capturing n_cycles rising edges.
    Assert that each measured period corresponds to ~3 kHz.
    
    sig      : cocotb handle (e.g., dut.uo_out[0])
    n_cycles : number of cycles to check
    units    : time units ("ns", "us", "ms")

    Returns: list of measured frequencies (in kHz)
    """
    timestamps = []
    freqs = []

    # Wait for first rising edge to align
    await RisingEdge(sig)
    for _ in range(n_cycles):
        await RisingEdge(sig)
        timestamps.append(get_sim_time(units=units))

    # Compute diffs and assert each
    diffs = [t2 - t1 for t1, t2 in zip(timestamps, timestamps[1:])]
    for d in diffs:
        if units == "us":
            freq_khz = 1_000.0 / d
        elif units == "ns":
            freq_khz = 1e6 / d
        elif units == "ms":
            freq_khz = 1.0 / d
        else:   
            raise ValueError("Unsupported units")

        # Assert each instance is ~3 kHz
        assert abs(freq_khz - 3.0) / 3.0 < 0.01, f"Expected ~3 kHz, got {freq_khz:.2f} kHz"
        freqs.append(freq_khz)

    return freqs

async def measure_duty(sig, pwm_period_us=333.33, units="us"):
    """
    Returns duty cycle in percent, robust to 0% and 100%.
    """
    # Try to see a rising edge within one PWM period
    try:
        await with_timeout(RisingEdge(sig), timeout_time=pwm_period_us, timeout_unit=units)
    except SimTimeoutError:
        # No rising edge for a whole period => ~0%
        return 0.0

    t_start = get_sim_time(units=units)

    # Try to see a falling edge within one PWM period
    try:
        await with_timeout(FallingEdge(sig), timeout_time=pwm_period_us, timeout_unit=units)
    except SimTimeoutError:
        # Stayed high for a whole period => ~100%
        return 100.0

    t_fall = get_sim_time(units=units)

    # Next rising edge to complete the period
    await RisingEdge(sig)
    t_end = get_sim_time(units=units)

    high_time = t_fall - t_start
    period    = t_end - t_start
    return 0.0 if period <= 0 else (high_time / period) * 100.0

@cocotb.test()
async def test_spi(dut):
    dut._log.info("Start SPI test")

    # Set the clock period to 100 ns (10 MHz)
    clock = Clock(dut.clk, 100, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    ncs = 1
    bit = 0
    sclk = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    dut._log.info("Test project behavior")
    dut._log.info("Write transaction, address 0x00, data 0xF0")
    ui_in_val = await send_spi_transaction(dut, 1, 0x00, 0xF0)  # Write transaction
    assert dut.uo_out.value == 0xF0, f"Expected 0xF0, got {dut.uo_out.value}"
    await ClockCycles(dut.clk, 1000) 

    dut._log.info("Write transaction, address 0x01, data 0xCC")
    ui_in_val = await send_spi_transaction(dut, 1, 0x01, 0xCC)  # Write transaction
    assert dut.uio_out.value == 0xCC, f"Expected 0xCC, got {dut.uio_out.value}"
    await ClockCycles(dut.clk, 100)

    dut._log.info("Write transaction, address 0x30 (invalid), data 0xAA")
    ui_in_val = await send_spi_transaction(dut, 1, 0x30, 0xAA)
    await ClockCycles(dut.clk, 100)

    dut._log.info("Read transaction (invalid), address 0x00, data 0xBE")
    ui_in_val = await send_spi_transaction(dut, 0, 0x30, 0xBE)
    assert dut.uo_out.value == 0xF0, f"Expected 0xF0, got {dut.uo_out.value}"
    await ClockCycles(dut.clk, 100)
    
    dut._log.info("Read transaction (invalid), address 0x41 (invalid), data 0xEF")
    ui_in_val = await send_spi_transaction(dut, 0, 0x41, 0xEF)
    await ClockCycles(dut.clk, 100)

    dut._log.info("Write transaction, address 0x02, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x02, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 100)

    dut._log.info("Write transaction, address 0x04, data 0xCF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0xCF)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("Write transaction, address 0x04, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("Write transaction, address 0x04, data 0x00")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x00)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("Write transaction, address 0x04, data 0x01")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x01)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("SPI test completed successfully")

@cocotb.test()
async def test_pwm_freq(dut):
    dut._log.info("Start PWM Frequency test")
    
    # Set the clock period to 100 ns (10 MHz)
    clock = Clock(dut.clk, 100, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    ncs = 1
    bit = 0
    sclk = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    dut._log.info("Enable outputs, Write transaction, address 0x00, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x00, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 1000) 

    dut._log.info("Enable PWM, Write transaction, address 0x02, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x02, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 1000)
    
    dut._log.info("Enable PWM of 50% duty cycle, Write transaction, address 0x04, data 0x80")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x80)
    await ClockCycles(dut.clk, 1000)
    
    freqs = await measure_period(dut.uo_out[0], n_cycles=10, units="us")
    dut._log.info(f"Measured frequencies (kHz): {freqs}")
    dut._log.info("PWM Frequency test completed successfully")

@cocotb.test()
async def test_pwm_duty(dut):
    dut._log.info("Start PWM Duty Cycle test")
    
    # Set the clock period to 100 ns (10 MHz)
    clock = Clock(dut.clk, 100, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    ncs = 1
    bit = 0
    sclk = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    dut._log.info("Enable outputs, Write transaction, address 0x00, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x00, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 1000) 

    dut._log.info("Enable PWM, Write transaction, address 0x02, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x02, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 1000)
    
    dut._log.info("Enable PWM of 0% duty cycle, Write transaction, address 0x04, data 0x00")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x00)
    await ClockCycles(dut.clk, 1000)
    
    for i in range(10):
        duty_cycle = await measure_duty(dut.uo_out[0], pwm_period_us=333.33, units="us")
        dut._log.info(f"Measured duty cycle: {duty_cycle:.2f}%")
        assert 0.0 <= duty_cycle <= 1.0, f"Expected ~0%, got {duty_cycle:.2f}%"
    
    dut._log.info("Enable PWM of 100% duty cycle, Write transaction, address 0x04, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0xFF)
    await ClockCycles(dut.clk, 1000)

    for i in range(10):
        duty_cycle = await measure_duty(dut.uo_out[0], pwm_period_us=333.33, units="us")
        dut._log.info(f"Measured duty cycle: {duty_cycle:.2f}%")
        assert 99.0 <= duty_cycle <= 100.0, f"Expected 100%, got {duty_cycle:.2f}%"

    dut._log.info("Enable PWM of 50% duty cycle, Write transaction, address 0x04, data 0x80")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x80)
    await ClockCycles(dut.clk, 1000)
    
    for i in range(10):
        duty_cycle = await measure_duty(dut.uo_out[0], pwm_period_us=333.33, units="us")
        dut._log.info(f"Measured duty cycle: {duty_cycle:.2f}%")
        assert 49.0 <= duty_cycle <= 51.0, f"Expected 50%, got {duty_cycle:.2f}%"

    # Write your test here
    dut._log.info("PWM Duty Cycle test completed successfully")
