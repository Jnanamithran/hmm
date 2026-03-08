# =============================================================================
# gpio_config.py — L298N Motor Driver Pin Configuration (BCM Numbering)
# =============================================================================
# Physical wiring reference:
#
#   L298N    ->  Raspberry Pi 3B+ (BCM)   ->  Physical Pin
#   -------------------------------------------------------
#   IN1      ->  GPIO 17                  ->  Pin 11
#   IN2      ->  GPIO 27                  ->  Pin 13
#   ENA      ->  GPIO 22                  ->  Pin 15  (HIGH = always enabled)
#   IN3      ->  GPIO 23                  ->  Pin 16
#   IN4      ->  GPIO 24                  ->  Pin 18
#   ENB      ->  GPIO 25                  ->  Pin 22  (HIGH = always enabled)
#   GND      ->  Pi GND                   ->  Pin 6
#   5V logic ->  Pi 5V                    ->  Pin 2
#
# NOTE: L298N VIN (motor power) -> 7.4V battery pack directly.
#       Do NOT feed 7.4V into Pi's 5V rail.
# =============================================================================

# Left-side track motors
MOTOR_LEFT_IN1 = 17   # Forward signal for left motor
MOTOR_LEFT_IN2 = 27   # Backward signal for left motor
MOTOR_LEFT_ENA = 22   # Enable pin for left motor (set HIGH, no PWM)

# Right-side track motors
MOTOR_RIGHT_IN3 = 23  # Forward signal for right motor
MOTOR_RIGHT_IN4 = 24  # Backward signal for right motor
MOTOR_RIGHT_ENB = 25  # Enable pin for right motor (set HIGH, no PWM)

# All motor pins as a flat list
ALL_MOTOR_PINS = [
    MOTOR_LEFT_IN1, MOTOR_LEFT_IN2, MOTOR_LEFT_ENA,
    MOTOR_RIGHT_IN3, MOTOR_RIGHT_IN4, MOTOR_RIGHT_ENB,
]
