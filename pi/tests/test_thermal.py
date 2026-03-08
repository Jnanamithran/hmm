#!/usr/bin/env python3
"""
pi/tests/test_thermal.py  —  MLX90640 Diagnostic Test
=====================================================
Run this ON THE PI to diagnose why the thermal sensor isn't working.

Usage:
    cd pi/
    source venv/bin/activate
    python tests/test_thermal.py

What it tests:
    Step 1  I2C bus enabled + device visible on bus
    Step 2  adafruit_mlx90640 library importable
    Step 3  Sensor address found (default 0x33)
    Step 4  Can read one complete frame (768 floats)
    Step 5  Temperature values sanity check (should be 15-50C indoors)
    Step 6  Saves a colorized thermal JPEG so you can verify visually
"""

import sys
import subprocess
import os

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"
WARN = "\033[93m[WARN]\033[0m"

print("\n" + "="*60)
print("  MLX90640 THERMAL SENSOR DIAGNOSTIC")
print("="*60)

# ── Step 1: Check I2C is enabled ──────────────────────────────────────────────
print(f"\n{INFO} Step 1: Checking I2C bus ...")
try:
    result = subprocess.run(["i2cdetect", "-l"], capture_output=True, text=True)
    if result.returncode == 0 and "i2c" in result.stdout:
        print(f"{PASS} I2C bus found: {result.stdout.strip()}")
    else:
        print(f"{FAIL} I2C not enabled or i2c-tools not installed")
        print("       FIX: sudo raspi-config -> Interface Options -> I2C -> Enable")
        print("            sudo apt install -y i2c-tools")
        sys.exit(1)
except FileNotFoundError:
    print(f"{WARN} i2cdetect not found — install: sudo apt install -y i2c-tools")

# ── Step 2: Scan for MLX90640 on I2C bus ─────────────────────────────────────
print(f"\n{INFO} Step 2: Scanning I2C bus for MLX90640 (addr 0x33) ...")
try:
    result = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True)
    print(result.stdout)
    if "33" in result.stdout:
        print(f"{PASS} MLX90640 found at address 0x33 on bus 1")
    else:
        print(f"{FAIL} MLX90640 NOT found on I2C bus 1")
        print("       Check wiring:")
        print("         MLX90640 VCC -> Pi 3.3V (Pin 1)")
        print("         MLX90640 GND -> Pi GND  (Pin 6)")
        print("         MLX90640 SDA -> Pi GPIO2 (Pin 3)")
        print("         MLX90640 SCL -> Pi GPIO3 (Pin 5)")
        print("       Also check: /boot/config.txt has 'dtparam=i2c_arm=on'")
        sys.exit(1)
except FileNotFoundError:
    print(f"{FAIL} i2cdetect not installed: sudo apt install -y i2c-tools")
    sys.exit(1)

# ── Step 3: Import adafruit library ───────────────────────────────────────────
print(f"\n{INFO} Step 3: Importing adafruit_mlx90640 ...")
try:
    import board
    import busio
    import adafruit_mlx90640
    print(f"{PASS} Libraries imported successfully")
except ImportError as e:
    print(f"{FAIL} Import error: {e}")
    print("       FIX: pip install adafruit-blinka adafruit-circuitpython-mlx90640")
    sys.exit(1)

# ── Step 4: Initialize sensor ─────────────────────────────────────────────────
print(f"\n{INFO} Step 4: Initializing MLX90640 ...")
try:
    i2c = busio.I2C(board.SCL, board.SDA, frequency=400_000)
    sensor = adafruit_mlx90640.MLX90640(i2c)
    sensor.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_4_HZ
    print(f"{PASS} Sensor initialized at 4 Hz refresh rate")
    print(f"{INFO} Serial number: {[hex(n) for n in sensor.serial_number]}")
except Exception as e:
    print(f"{FAIL} Sensor init failed: {e}")
    print("       Possible cause: I2C speed too low. Add to /boot/config.txt:")
    print("         dtparam=i2c_arm_baudrate=400000")
    print("       Then: sudo reboot")
    sys.exit(1)

# ── Step 5: Read one frame ────────────────────────────────────────────────────
print(f"\n{INFO} Step 5: Reading thermal frame (768 temperature values) ...")
import time
frame_buf = [0.0] * 768
max_attempts = 5
success = False

for attempt in range(1, max_attempts + 1):
    try:
        sensor.getFrame(frame_buf)
        success = True
        print(f"{PASS} Frame read successfully on attempt {attempt}")
        break
    except Exception as e:
        print(f"{WARN} Attempt {attempt}/{max_attempts}: {e}")
        time.sleep(0.5)

if not success:
    print(f"{FAIL} Could not read frame after {max_attempts} attempts")
    print("       This sometimes happens if sensor just powered on.")
    print("       Try again in a few seconds — MLX90640 needs a warmup period.")
    sys.exit(1)

# ── Step 6: Sanity check temperatures ────────────────────────────────────────
import numpy as np

arr    = np.array(frame_buf, dtype=np.float32).reshape(24, 32)
t_min  = float(arr.min())
t_max  = float(arr.max())
t_mean = float(arr.mean())

print(f"\n{INFO} Step 6: Temperature sanity check ...")
print(f"       Min:  {t_min:.1f} °C")
print(f"       Max:  {t_max:.1f} °C")
print(f"       Mean: {t_mean:.1f} °C")

if 10 <= t_mean <= 60:
    print(f"{PASS} Temperature range looks realistic for an indoor environment")
else:
    print(f"{WARN} Mean temp {t_mean:.1f}C is outside expected 10-60C range")
    print("       Sensor may not be warmed up yet (needs ~2 min), or wiring issue")

if t_max - t_min < 0.5:
    print(f"{WARN} Very small temperature range ({t_max-t_min:.2f}C) — sensor may be stuck")
else:
    print(f"{PASS} Temperature spread {t_max-t_min:.1f}C looks healthy")

# ── Step 7: Save a test image ─────────────────────────────────────────────────
print(f"\n{INFO} Step 7: Saving colorized thermal test image ...")
try:
    import cv2
    norm = ((arr - t_min) / max(t_max - t_min, 0.1) * 255).astype(np.uint8)
    colored  = cv2.applyColorMap(norm, cv2.COLORMAP_INFERNO)
    upscaled = cv2.resize(colored, (640, 480), interpolation=cv2.INTER_CUBIC)
    cv2.putText(upscaled, f"Min: {t_min:.1f}C  Max: {t_max:.1f}C  Mean: {t_mean:.1f}C",
                (10, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
    outpath = "/tmp/thermal_test.jpg"
    cv2.imwrite(outpath, upscaled)
    print(f"{PASS} Saved: {outpath}")
    print(f"       View with: display {outpath}  OR  scp to your laptop")
except ImportError:
    print(f"{WARN} opencv not installed — skipping image save")
    print("       pip install opencv-python-headless")

# ── Step 8: Live reading for 5 seconds ────────────────────────────────────────
print(f"\n{INFO} Step 8: Live 5-second reading test ...")
for i in range(5):
    try:
        sensor.getFrame(frame_buf)
        arr   = np.array(frame_buf)
        print(f"       Frame {i+1}: min={arr.min():.1f}C  max={arr.max():.1f}C  mean={arr.mean():.1f}C")
    except Exception as e:
        print(f"       Frame {i+1}: ERROR — {e}")
    time.sleep(0.3)

print(f"\n{'='*60}")
print(f"  {PASS} MLX90640 IS WORKING CORRECTLY")
print(f"  The sensor will stream at 4 Hz through /thermal_feed")
print(f"{'='*60}\n")
