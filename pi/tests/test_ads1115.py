import time
import board
import busio

import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

# Create I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Create ADS1115 ADC
ads = ADS.ADS1115(i2c)

# MQ-4 connected to A0  → channel 0
chan = AnalogIn(ads, 0)

print("Reading MQ-4 on ADS1115 A0...\n")

while True:
    print(f"Raw: {chan.value:6d}   Voltage: {chan.voltage:.3f} V")
    time.sleep(1)