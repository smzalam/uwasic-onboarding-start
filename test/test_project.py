# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, with_timeout, Timer
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

async def _wait_edge_poll(sig, rising=True, step_ns=10):
    """Poll 'sig' until a rising (default) or falling edge is observed."""
    prev = int(sig.value)
    while True:
        await Timer(step_ns, units="ns")
        cur = int(sig.value)
        if rising and prev == 0 and cur == 1:
            return
        if (not rising) and prev == 1 and cur == 0:
            return
        prev = cur
        
async def measure_period(sig, n_cycles=8):
    """
    Measure period by capturing n rising edges on 'sig' (bit-select safe).
    Returns a list of measured frequencies in kHz and asserts ~3 kHz each.
    """
    timestamps = []
    freqs = []

    # Align to next rising edge
    await _wait_edge_poll(sig, rising=True)

    # Capture n rising edges
    for _ in range(n_cycles):
        await _wait_edge_poll(sig, rising=True)
        timestamps.append(get_sim_time(units="us"))

    # Compute deltas and per-cycle frequency
    diffs = [t2 - t1 for t1, t2 in zip(timestamps, timestamps[1:])] 
    for d in diffs:
        freq_khz = 1_000.0 / d
        assert abs(freq_khz - 3.0) / 3.0 < 0.01, f"Expected ~3 kHz, got {freq_khz:.2f} kHz"
        freqs.append(freq_khz)

    return freqs

async def measure_duty(sig, pwm_period_us=333.33, units="us"):
    """
    Duty cycle (%) by polling; robust to 0% and 100%, including initial-high.
    """
    step_ns = 10 

    now = get_sim_time(units=units)
    deadline = now + pwm_period_us

    prev = int(sig.value)
    if prev == 1:
        t_start = now
    else:
        # Find a rising edge within one period; if none, it's ~0%
        while get_sim_time(units=units) < deadline:
            await Timer(step_ns, units="ns")
            cur = int(sig.value)
            if prev == 0 and cur == 1:
                t_start = get_sim_time(units=units)
                break
            prev = cur
        else:
            return 0.0  # stayed low for a whole period

    # Try to find a falling edge within one PWM period after t_start
    fall_deadline = t_start + pwm_period_us
    prev = int(sig.value)
    while get_sim_time(units=units) < fall_deadline:
        await Timer(step_ns, units="ns")
        cur = int(sig.value)
        if prev == 1 and cur == 0:
            t_fall = get_sim_time(units=units)
            # Next rising edge to close the period
            prev2 = cur
            while True:
                await Timer(step_ns, units="ns")
                cur2 = int(sig.value)
                if prev2 == 0 and cur2 == 1:
                    t_end = get_sim_time(units=units)
                    high_time = t_fall - t_start
                    period = t_end - t_start
                    return 0.0 if period <= 0 else (high_time / period) * 100.0
                prev2 = cur2
        prev = cur

    # Never saw a falling edge ⇒ stayed high ≈ 100%
    return 100.0

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
    
    freqs = await measure_period(dut.uo_out[0], n_cycles=10)
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
        duty_cycle = await measure_duty(dut.uo_out[0], pwm_period_us=333.33)
        dut._log.info(f"Measured duty cycle: {duty_cycle:.2f}%")
        assert 0.0 <= duty_cycle <= 1.0, f"Expected ~0%, got {duty_cycle:.2f}%"
    
    dut._log.info("Enable PWM of 100% duty cycle, Write transaction, address 0x04, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0xFF)
    await ClockCycles(dut.clk, 1000)

    for i in range(10):
        duty_cycle = await measure_duty(dut.uo_out[0], pwm_period_us=333.33)
        dut._log.info(f"Measured duty cycle: {duty_cycle:.2f}%")
        assert 99.0 <= duty_cycle <= 100.0, f"Expected 100%, got {duty_cycle:.2f}%"

    dut._log.info("Enable PWM of 50% duty cycle, Write transaction, address 0x04, data 0x80")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x80)
    await ClockCycles(dut.clk, 1000)
    
    for i in range(10):
        duty_cycle = await measure_duty(dut.uo_out[0], pwm_period_us=333.33)
        dut._log.info(f"Measured duty cycle: {duty_cycle:.2f}%")
        assert 49.0 <= duty_cycle <= 51.0, f"Expected 50%, got {duty_cycle:.2f}%"

    # Write your test here
    dut._log.info("PWM Duty Cycle test completed successfully")
