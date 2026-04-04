import RPi.GPIO as GPIO
import time

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)

ENA = 15
IN1 = 11
IN2 = 13
ENB = 12
IN3 = 16
IN4 = 18

pins = [ENA, IN1, IN2, ENB, IN3, IN4]

for p in pins:
    GPIO.setup(p, GPIO.OUT)

GPIO.output(ENA, True)
GPIO.output(ENB, True)

GPIO.output(IN1, True)
GPIO.output(IN2, False)

GPIO.output(IN3, True)
GPIO.output(IN4, False)

print("Motors running")
time.sleep(3)

GPIO.cleanup()