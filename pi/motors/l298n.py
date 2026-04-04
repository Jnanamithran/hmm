# =============================================================================
# motors/l298n.py — L298N Dual H-Bridge Motor Controller
# =============================================================================
# Controls two independent motor channels (left track / right track).
#
# IMPORTANT: ENA and ENB jumper caps are INSTALLED on the L298N board.
#   Both channels are permanently enabled — this code does NOT touch ENA/ENB.
#   Only the 4 direction pins (IN1, IN2, IN3, IN4) are used.
#
# WIRING:
#   IN1 → GPIO 17 (Pi Pin 11)  — Left  motor forward
#   IN2 → GPIO 27 (Pi Pin 13)  — Left  motor backward
#   IN3 → GPIO 23 (Pi Pin 16)  — Right motor forward
#   IN4 → GPIO 24 (Pi Pin 18)  — Right motor backward
#
# TRUTH TABLE (per channel):
#   INx=HIGH, INy=LOW  → forward
#   INx=LOW,  INy=HIGH → backward
#   INx=LOW,  INy=LOW  → coast / stop
#   INx=HIGH, INy=HIGH → NEVER DO THIS — can damage driver
#
# MOVEMENT LOGIC:
#   Forward  → left forward,  right forward
#   Backward → left backward, right backward
#   Left     → left forward,  right backward  (tank pivot)
#   Right    → left backward, right forward   (tank pivot)
#   Stop     → all pins LOW
# =============================================================================

import logging

log = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    _GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    _GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not available — running in simulation mode")

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gpio_config import (
    MOTOR_LEFT_IN1,
    MOTOR_LEFT_IN2,
    MOTOR_RIGHT_IN3,
    MOTOR_RIGHT_IN4,
    ALL_MOTOR_PINS,
)


class MotorController:
    """
    Tank-drive motor controller for L298N with jumpers on ENA/ENB.
    Controls 4 DC motors (2 per side) using only direction pins.
    """

    def __init__(self):
        self._direction = "stop"

        if _GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            for pin in ALL_MOTOR_PINS:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)

            log.info(
                "MotorController ready — IN1=%d IN2=%d IN3=%d IN4=%d",
                MOTOR_LEFT_IN1, MOTOR_LEFT_IN2,
                MOTOR_RIGHT_IN3, MOTOR_RIGHT_IN4,
            )
        else:
            log.info("MotorController ready — SIMULATION MODE")

    def _set(self, l_in1: bool, l_in2: bool, r_in3: bool, r_in4: bool):
        if not _GPIO_AVAILABLE:
            log.debug("[SIM] IN1=%s IN2=%s IN3=%s IN4=%s", l_in1, l_in2, r_in3, r_in4)
            return
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.HIGH if l_in1 else GPIO.LOW)
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.HIGH if l_in2 else GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN3, GPIO.HIGH if r_in3 else GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN4, GPIO.HIGH if r_in4 else GPIO.LOW)

    def forward(self):
        """W — both motors forward."""
        self._direction = "forward"
        self._set(True, False, True, False)
        log.info("Motors: FORWARD")

    def backward(self):
        """S — both motors backward."""
        self._direction = "backward"
        self._set(False, True, False, True)
        log.info("Motors: BACKWARD")

    def left(self):
        """A — tank pivot left: left forward, right backward."""
        self._direction = "left"
        self._set(True, False, False, True)
        log.info("Motors: LEFT (tank pivot)")

    def right(self):
        """D — tank pivot right: left backward, right forward."""
        self._direction = "right"
        self._set(False, True, True, False)
        log.info("Motors: RIGHT (tank pivot)")

    def stop(self):
        """Space — all motors stop."""
        self._direction = "stop"
        self._set(False, False, False, False)
        log.info("Motors: STOP")

    @property
    def direction(self) -> str:
        return self._direction

    def cleanup(self):
        """Release GPIO resources on shutdown."""
        self.stop()
        if _GPIO_AVAILABLE:
            GPIO.cleanup()
            log.info("GPIO cleaned up")