# Pi Robot Server

## Hardware Requirements
- Raspberry Pi 3B+
- USB camera (UVC compatible)
- L298N motor driver
- 2x 3.7V Li-ion batteries (7.4V total)
- 4x DC motors (2 per tracked side)

## GPIO Wiring (BCM numbering)

| L298N Pin | Pi GPIO | Pi Physical Pin |
|-----------|---------|-----------------|
| IN1       | GPIO 17 | Pin 11          |
| IN2       | GPIO 27 | Pin 13          |
| ENA       | GPIO 22 | Pin 15          |
| IN3       | GPIO 23 | Pin 16          |
| IN4       | GPIO 24 | Pin 18          |
| ENB       | GPIO 25 | Pin 22          |
| GND       | GND     | Pin 6           |
| 5V (logic)| 5V      | Pin 2           |

**IMPORTANT**: L298N VIN (motor power) connects to 7.4V battery directly.

## Installation

```bash
sudo apt update
sudo apt install python3-pip python3-opencv -y
pip3 install -r requirements.txt
```

## Run

```bash
python3 app.py
```

Server starts on port 5000.

## Endpoints

| Endpoint           | Method | Description              |
|--------------------|--------|--------------------------|
| /video_feed        | GET    | MJPEG stream             |
| /move/forward      | POST   | Move forward             |
| /move/backward     | POST   | Move backward            |
| /move/left         | POST   | Turn left (tank pivot)   |
| /move/right        | POST   | Turn right (tank pivot)  |
| /move/stop         | POST   | Stop all motors          |
| /health            | GET    | Health check             |

## Find Pi IP address

```bash
hostname -I
```
