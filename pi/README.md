# VIPER Pi Robot Server

## Overview

The VIPER Pi Robot Server is the embedded control system that powers the robot's movement, camera streaming, and sensor data collection. Built on Raspberry Pi, this server provides a REST API for controlling the tracked robot platform and streaming live video from a USB camera.

## Hardware Requirements

- **Raspberry Pi 3B+** (or compatible model)
- **USB camera** (UVC compatible)
- **L298N motor driver** for motor control
- **Power system:**
  - 2x 3.7V Li-ion batteries (7.4V total for motors)
  - 5V logic power for Raspberry Pi
- **4x DC motors** (2 per tracked side for differential drive)

## GPIO Wiring Configuration (BCM numbering)

| L298N Pin | Pi GPIO | Pi Physical Pin | Function |
|-----------|---------|-----------------|----------|
| IN1       | GPIO 17 | Pin 11          | Left motor forward |
| IN2       | GPIO 27 | Pin 13          | Left motor reverse |
| ENA       | GPIO 22 | Pin 15          | Left motor speed control |
| IN3       | GPIO 23 | Pin 16          | Right motor forward |
| IN4       | GPIO 24 | Pin 18          | Right motor reverse |
| ENB       | GPIO 25 | Pin 22          | Right motor speed control |
| GND       | GND     | Pin 6           | Ground connection |
| 5V (logic)| 5V      | Pin 2           | Logic power |

**⚠️ Critical Power Connections:**
- L298N VIN (motor power) connects directly to 7.4V battery
- L298N 5V (logic) connects to Raspberry Pi 5V supply
- Ensure proper grounding between all components

## Installation

### System Dependencies
```bash
sudo apt update
sudo apt install python3-pip python3-opencv -y
```

### Python Dependencies
```bash
pip3 install -r requirements.txt
```

## Quick Start

1. **Start the server:**
   ```bash
   python3 app.py
   ```

2. **Find your Pi's IP address:**
   ```bash
   hostname -I
   ```

3. **Access the API:**
   Server runs on port 5000 by default
   Example: `http://[PI_IP]:5000/video_feed`

## API Endpoints

### Video Streaming
- **GET** `/video_feed` - MJPEG video stream from USB camera

### Motor Control
- **POST** `/move/forward` - Move robot forward
- **POST** `/move/backward` - Move robot backward  
- **POST** `/move/left` - Turn left (tank pivot turn)
- **POST** `/move/right` - Turn right (tank pivot turn)
- **POST** `/move/stop` - Stop all motors immediately

### System Health
- **GET** `/health` - Health check endpoint

## Motor Control Logic

The robot uses differential drive with two independent motor channels:
- **Left motors:** Controlled by IN1/IN2/ENA pins
- **Right motors:** Controlled by IN3/IN4/ENB pins

Movement patterns:
- **Forward:** Both channels forward
- **Backward:** Both channels reverse
- **Left turn:** Right channel forward, left channel reverse
- **Right turn:** Left channel forward, right channel reverse

## Camera Integration

The server uses OpenCV to capture video from a USB camera and streams it as MJPEG over HTTP. The camera feed is accessible via the `/video_feed` endpoint and can be viewed in any modern web browser.

## Troubleshooting

### Common Issues

1. **Camera not detected:**
   - Ensure USB camera is UVC compatible
   - Check camera connection and power
   - Verify camera works with other applications

2. **Motors not responding:**
   - Check GPIO wiring connections
   - Verify power supply voltage (7.4V for motors)
   - Ensure proper grounding between Pi and L298N

3. **Server won't start:**
   - Check Python dependencies are installed
   - Verify camera is accessible
   - Check for port conflicts on port 5000

### Debug Commands

```bash
# Check camera availability
ls /dev/video*

# Test GPIO pins
python3 -c "import RPi.GPIO as GPIO; print('GPIO available')"

# Check network connectivity
hostname -I
```

## Integration with VIPER System

This Pi server integrates with the larger VIPER system:
- **Frontend:** React application for remote control
- **Backend:** AI detection and analysis server
- **Database:** Firebase for data storage and authentication

The Pi server provides the real-time video feed and motor control that enables remote operation and AI-powered crack detection.

## Safety Notes

- Always ensure proper power isolation when working with motors
- Use appropriate fuses for motor power circuits
- Keep camera lens clean for optimal video quality
- Monitor battery voltage to prevent over-discharge