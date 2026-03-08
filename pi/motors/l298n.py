# =============================================================================
# motors/l298n.py — L298N Dual H-Bridge Motor Controller
# =============================================================================
# Controls two independent motor channels (left track / right track).
# Direction is toggled by setting IN1/IN2 and IN3/IN4 HIGH/LOW pairs.
# ENA/ENB are held permanently HIGH (no PWM speed control required).
#
# Truth table (per channel):
#   INx=HIGH, INy=LOW  -> forward
#   INx=LOW,  INy=HIGH -> backward
#   INx=LOW,  INy=LOW  -> coast/stop
#   INx=HIGH, INy=HIGH -> brake (avoid — can damage driver)
# =============================================================================

import sys
import logging

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    logger.warning("RPi.GPIO not available — running in simulation mode")

# Import pin constants
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gpio_config import (
    MOTOR_LEFT_IN1, MOTOR_LEFT_IN2, MOTOR_LEFT_ENA,
    MOTOR_RIGHT_IN3, MOTOR_RIGHT_IN4, MOTOR_RIGHT_ENB,
    ALL_MOTOR_PINS,
)


class MotorController:
    """
    Controls a tracked (tank-drive) robot via L298N.

    Movement logic:
      - Forward  : both tracks spin forward
      - Backward : both tracks spin backward
      - Left     : left track backward, right track forward  (pivot left)
      - Right    : left track forward,  right track backward (pivot right)
      - Stop     : all outputs LOW
    """

    def __init__(self):
        self._current_direction = "stop"
        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            for pin in ALL_MOTOR_PINS:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
            # Enable both channels permanently
            GPIO.output(MOTOR_LEFT_ENA, GPIO.HIGH)
            GPIO.output(MOTOR_RIGHT_ENB, GPIO.HIGH)
            logger.info("MotorController initialized — GPIO ready")
        else:
            logger.info("MotorController initialized — SIMULATION MODE")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set(self, l_in1, l_in2, r_in3, r_in4):
        """Write direction bits to both motor channels."""
        if not GPIO_AVAILABLE:
            logger.debug(
                f"[SIM] L_IN1={l_in1} L_IN2={l_in2} "
                f"R_IN3={r_in3} R_IN4={r_in4}"
            )
            return
        GPIO.output(MOTOR_LEFT_IN1,  GPIO.HIGH if l_in1 else GPIO.LOW)
        GPIO.output(MOTOR_LEFT_IN2,  GPIO.HIGH if l_in2 else GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN3, GPIO.HIGH if r_in3 else GPIO.LOW)
        GPIO.output(MOTOR_RIGHT_IN4, GPIO.HIGH if r_in4 else GPIO.LOW)

    # ------------------------------------------------------------------
    # Public direction API
    # ------------------------------------------------------------------

    def forward(self):
        self._current_direction = "forward"
        self._set(True, False, True, False)
        logger.info("Motors: FORWARD")

    def backward(self):
        self._current_direction = "backward"
        self._set(False, True, False, True)
        logger.info("Motors: BACKWARD")

    def left(self):
        """Tank-turn left: left track backward, right track forward."""
        self._current_direction = "left"
        self._set(False, True, True, False)
        logger.info("Motors: LEFT (tank pivot)")

    def right(self):
        """Tank-turn right: left track forward, right track backward."""
        self._current_direction = "right"
        self._set(True, False, False, True)
        logger.info("Motors: RIGHT (tank pivot)")

    def stop(self):
        self._current_direction = "stop"
        self._set(False, False, False, False)
        logger.info("Motors: STOP")

    @property
    def direction(self):
        return self._current_direction

    def cleanup(self):
        """Release GPIO resources — call on application shutdown."""
        self.stop()
        if GPIO_AVAILABLE:
            GPIO.cleanup()
            logger.info("GPIO cleaned up")
