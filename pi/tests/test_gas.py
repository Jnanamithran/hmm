#!/usr/bin/env python3
"""
pi/tests/test_gas.py  —  MQ4 + ADS1115 Diagnostic
===================================================
Run ON THE PI:
    cd ~/pi && source venv/bin/activate && python tests/test_gas.py

Tests:
    Step 1  I2C bus enabled + i2cdetect finds ADS1115 at 0x48
    Step 2  adafruit_ads1x15 library importable
    Step 3  ADS1115 initializes and reads voltage on A0
    Step 4  Voltage sanity check
    Step 5  PPM estimation
    Step 6  Scan all 4 channels (A0–A3) to find which one your MQ4 is on
    Step 7  Live 10-second reading — hold lighter near sensor to test
"""

import sys, time, math, subprocess

G = "\033[92m[PASS]\033[0m"
F = "\033[91m[FAIL]\033[0m"
I = "\033[94m[INFO]\033[0m"
W = "\033[93m[WARN]\033[0m"

print("\n" + "="*62)
print("  MQ4 + ADS1115 GAS SENSOR DIAGNOSTIC")
print("="*62)

# ── Step 1: I2C scan for ADS1115 ──────────────────────────────────────────────
print(f"\n{I} Step 1: Scanning I2C bus for ADS1115 ...")
print("         (ADS1115 default address = 0x48)")
try:
    r = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True)
    print(r.stdout)
    found_addrs = []
    for addr in ["48", "49", "4a", "4b"]:
        if addr in r.stdout.lower():
            found_addrs.append(f"0x{addr}")
    if found_addrs:
        print(f"{G} ADS1115 found at: {', '.join(found_addrs)}")
        ads_addr = int(found_addrs[0], 16)
    else:
        print(f"{F} ADS1115 NOT found on I2C bus")
        print()
        print("  ┌─ ADS1115 WIRING ────────────────────────────────────┐")
        print("  │  ADS1115 VDD  →  Pi 3.3V  (Pin 1)                  │")
        print("  │  ADS1115 GND  →  Pi GND   (Pin 6)                  │")
        print("  │  ADS1115 SDA  →  Pi GPIO2 (Pin 3)                  │")
        print("  │  ADS1115 SCL  →  Pi GPIO3 (Pin 5)                  │")
        print("  │  ADS1115 ADDR →  Pi GND   (Pin 6)  → addr 0x48     │")
        print("  │                                                       │")
        print("  │  MQ4 VCC  →  Pi 5V   (Pin 2)  ← must be 5V         │")
        print("  │  MQ4 GND  →  Pi GND  (Pin 6)                       │")
        print("  │  MQ4 AO   →  ADS1115 A0                            │")
        print("  └─────────────────────────────────────────────────────┘")
        sys.exit(1)
except FileNotFoundError:
    print(f"{F} i2cdetect not found: sudo apt install -y i2c-tools")
    ads_addr = 0x48   # proceed anyway

# ── Step 2: Import library ────────────────────────────────────────────────────
print(f"\n{I} Step 2: Importing adafruit_ads1x15 ...")
try:
    import board, busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    print(f"{G} Libraries imported successfully")
except ImportError as e:
    print(f"{F} Import error: {e}")
    print("       FIX: pip install adafruit-blinka adafruit-circuitpython-ads1x15")
    sys.exit(1)

# ── Step 3: Initialize ADS1115 ────────────────────────────────────────────────
print(f"\n{I} Step 3: Initializing ADS1115 at 0x{ads_addr:02X} ...")
try:
    i2c = busio.I2C(board.SCL, board.SDA)
    ads = ADS.ADS1115(i2c, address=ads_addr)
    ads.gain = 1   # ±4.096V range — safe for MQ4 output
    print(f"{G} ADS1115 initialized (gain=1, range=±4.096V)")
except Exception as e:
    print(f"{F} ADS1115 init failed: {e}")
    sys.exit(1)

# ── Step 4: Scan all 4 channels ───────────────────────────────────────────────
print(f"\n{I} Step 4: Scanning all 4 ADS1115 channels (A0–A3) ...")
print("         (Your MQ4 AO should show a non-zero voltage)\n")

ch_consts = [ADS.P0, ADS.P1, ADS.P2, ADS.P3]
ch_readings = {}
live_channels = []
for n, p in enumerate(ch_consts):
    try:
        chan = AnalogIn(ads, p)
        v    = chan.voltage
        raw  = chan.value
        ch_readings[n] = (v, raw)
        bar  = "█" * int(v / 0.1)
        note = ""
        if v < 0.05:
            note = "  ← near 0 (not connected?)"
        elif v > 3.9:
            note = "  ← near max (check wiring)"
        else:
            note = "  ← ✓ SIGNAL"
            live_channels.append(n)
        print(f"  A{n}: {v:.4f} V  (raw={raw:6d})  {bar[:30]}{note}")
    except Exception as e:
        print(f"  A{n}: ERROR — {e}")
        ch_readings[n] = (0.0, 0)

print()
if live_channels:
    print(f"{G} Signal detected on: {[f'A{c}' for c in live_channels]}")
    target_ch = live_channels[0]
    if target_ch != 0:
        print(f"{W} MQ4 AO is on A{target_ch} not A0!")
        print(f"   Either move wire to A0, or change sensors/mq4.py → channel={target_ch}")
else:
    print(f"{W} All channels near 0V")
    print("   Check: Is MQ4 VCC connected to Pi 5V (Pin 2)?")
    print("   Check: Is MQ4 AO connected to ADS1115 A0?")
    print("   Check: Has MQ4 warmed up? (heater gets warm to touch in ~60s)")
    target_ch = 0

# ── Step 5: PPM estimate ──────────────────────────────────────────────────────
MQ4_A=1012.7; MQ4_B=-2.786; MQ4_R0=10.0; MQ4_RL=10.0; MQ4_VCC=5.0

v_target, _ = ch_readings.get(target_ch, (0.0, 0))
print(f"\n{I} Step 5: PPM estimate on A{target_ch} (V={v_target:.4f}V) ...")

if v_target < 0.01:
    print(f"{W} Cannot compute PPM — voltage is 0")
    ppm = 0.0
else:
    rs = ((MQ4_VCC - v_target) / v_target) * MQ4_RL
    try:    ppm = max(0.0, MQ4_A * math.pow(rs / MQ4_R0, MQ4_B))
    except: ppm = 0.0
    print(f"   Rs = {rs:.2f} kΩ    Rs/R0 = {rs/MQ4_R0:.3f}")
    print(f"   Estimated CH4 PPM = {ppm:.1f}")

    if ppm < 10:
        print(f"{W} Very low PPM — MQ4 needs 24-48h full warmup for accurate readings")
        print("   After just powering on, wait at least 60 seconds before testing")
    elif ppm > 100000:
        print(f"{W} PPM very high — R0 needs calibration in clean air")
    else:
        print(f"{G} PPM reading looks plausible")

# ── Step 6: Live 10-second reading ────────────────────────────────────────────
print(f"\n{I} Step 6: Live 10-second reading on A{target_ch} ...")
print("   TIP: Hold an UNLIT lighter near the sensor → PPM should spike")
print("   The MQ4 element should be warm to the touch\n")

chan_live = AnalogIn(ads, ch_consts[target_ch])

def lvl(p):
    if p < 50:    return "SAFE   "
    if p < 1000:  return "LOW    "
    if p < 5000:  return "WARNING"
    return "DANGER "

samples = []
for i in range(20):
    try:
        v2  = chan_live.voltage
        raw2= chan_live.value
        if v2 < 0.01:
            p = 0.0
        else:
            rs2 = ((MQ4_VCC - v2) / v2) * MQ4_RL
            try:    p = max(0.0, MQ4_A * math.pow(rs2 / MQ4_R0, MQ4_B))
            except: p = 0.0
        samples.append(p)
        bar = "█" * min(25, int(p / 50))
        print(f"  [{i+1:2d}/20]  {v2:.4f}V  {lvl(p)}  {p:9.1f} PPM  {bar}")
    except Exception as e:
        print(f"  [{i+1:2d}/20]  ERROR: {e}")
    time.sleep(0.5)

if samples:
    span = max(samples) - min(samples)
    print(f"\n  Min={min(samples):.1f}  Max={max(samples):.1f}  Spread={span:.1f} PPM")
    if span > 20:
        print(f"{G} Sensor is responding to the environment!")
    elif max(samples) < 5:
        print(f"{W} No readings yet — MQ4 heater may not be warm")
        print("   Touch the metal mesh on MQ4: it should be warm/hot")
    else:
        print(f"{W} Small variation — try holding lighter near sensor")

print(f"\n{'='*62}")
print("  CALIBRATION GUIDE (for accurate PPM):")
print("  1. Power MQ4 on, leave running in clean air for 24-48h")
print("  2. Note the stable voltage in clean air: V_clean")
print("  3. R0 = ((5.0 - V_clean) / V_clean) * 10   [kΩ]")
print("  4. Edit pi/sensors/mq4.py  →  MQ4_R0 = <your value>")
print()
print("  CURRENT DEFAULT: MQ4_R0 = 10.0 kΩ")
if samples and max(samples) > 5:
    v_now = ch_readings[target_ch][0]
    if v_now > 0.01:
        r0_est = ((MQ4_VCC - v_now) / v_now) * MQ4_RL
        print(f"  CURRENT READING suggests R0 ≈ {r0_est:.2f} kΩ")
        print(f"  (Only valid if measured in clean air after full warmup)")
print(f"{'='*62}\n")