# =============================================================================
# gpio_config.py — L298N Motor Driver Pin Configuration (BCM Numbering)
# =============================================================================
# Physical wiring reference:
#
#   L298N    ->  Raspberry Pi 3B+ (BCM)   ->  Physical Pin
#   -------------------------------------------------------
#   IN1      ->  GPIO 17                  ->  Pin 11
#   IN2      ->  GPIO 27                  ->  Pin 13
#   IN3      ->  GPIO 23                  ->  Pin 16
#   IN4      ->  GPIO 24                  ->  Pin 18
#   GND      ->  Pi GND                   ->  Pin 6
#   5V logic ->  Pi 5V                    ->  Pin 2
#
# NOTE:
#   ENA and ENB jumper caps are INSTALLED on the L298N board.
#   Both motor channels are permanently enabled — no GPIO needed for ENA/ENB.
#   Do NOT connect or configure ENA/ENB pins.
#
#   L298N VIN (motor power) -> battery pack directly (6-12V).
#   Do NOT feed battery voltage into Pi's 5V rail.
# =============================================================================

# Left-side motors (OUT1 + OUT2)
MOTOR_LEFT_IN1 = 17   # Forward  signal for left motor
MOTOR_LEFT_IN2 = 27   # Backward signal for left motor

# Right-side motors (OUT3 + OUT4)
MOTOR_RIGHT_IN3 = 23  # Forward  signal for right motor
MOTOR_RIGHT_IN4 = 24  # Backward signal for right motor

# All direction pins as a flat list (ENA/ENB excluded — jumpers handle enable)
ALL_MOTOR_PINS = [
    MOTOR_LEFT_IN1,
    MOTOR_LEFT_IN2,
    MOTOR_RIGHT_IN3,
    MOTOR_RIGHT_IN4,
]