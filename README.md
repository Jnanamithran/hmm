# VIPER — Visual Inspection Platform for Infrastructure Evaluation and Repair

## System Overview

VIPER is an advanced robotic inspection system designed for infrastructure monitoring and crack detection. The system combines a tracked robot platform with AI-powered computer vision to autonomously detect and analyze structural damage.

```
[USB Camera] --> [Raspberry Pi 3B+] --> Wi-Fi --> [Laptop AI Backend] --> [React Frontend]
                 Flask MJPEG server              YOLOv8 inference        Browser UI
                 GPIO motor control              Annotated stream
```

## Key Features

- **Real-time Video Streaming**: MJPEG video feed from USB camera
- **AI-Powered Detection**: YOLOv8 model for crack detection and analysis
- **Remote Control**: Web-based interface for robot operation
- **Data Logging**: Firebase integration for session recording and analysis
- **Multi-Sensor Support**: Thermal imaging and gas detection capabilities

## Quick Start

### Prerequisites

- Raspberry Pi 3B+ or compatible
- USB camera (UVC compatible)
- L298N motor driver
- 4x DC motors with tracked chassis
- 2x 3.7V Li-ion batteries (7.4V total)
- Laptop/PC for backend and frontend

### Step 1 — Find your Pi's IP

```bash
# On the Pi:
hostname -I
```

### Step 2 — Configure Pi IP in laptop backend

Edit `laptop/backend/ai_server.py`:
```python
PI_IP = '192.168.1.XXX'   # Your Pi's actual IP
```

### Step 3 — Start Pi server

```bash
cd pi
pip3 install -r requirements.txt
python3 app.py
```

### Step 4 — Start laptop AI backend

```bash
cd laptop/backend
pip install -r requirements.txt
python ai_server.py
```

### Step 5 — Start React frontend

```bash
cd laptop/frontend
npm install
npm run dev
# Open http://localhost:3000
```

## Hardware Configuration

### GPIO Wiring (L298N -> Pi BCM)

| Signal | GPIO | Pin | Function |
|--------|------|-----|----------|
| L_IN1  |  17  |  11 | Left motor forward |
| L_IN2  |  27  |  13 | Left motor reverse |
| L_ENA  |  22  |  15 | Left motor speed control |
| R_IN3  |  23  |  16 | Right motor forward |
| R_IN4  |  24  |  18 | Right motor reverse |
| R_ENB  |  25  |  22 | Right motor speed control |

### Power Connections

- **L298N VIN**: Connect to 7.4V battery (motors)
- **L298N 5V**: Connect to Raspberry Pi 5V supply
- **GND**: Common ground between all components

## System Architecture

### Components

1. **Pi Robot Server** (`pi/`)
   - Motor control via GPIO
   - Video streaming via Flask
   - Sensor data collection

2. **AI Backend** (`laptop/backend/`)
   - YOLOv8 crack detection
   - Video processing and annotation
   - Firebase integration

3. **React Frontend** (`laptop/frontend/`)
   - Real-time video display
   - Remote control interface
   - Detection results visualization

### Data Flow

1. **Video Capture**: USB camera → OpenCV → MJPEG stream
2. **AI Processing**: Stream → YOLOv8 → Crack detection
3. **Control**: Web UI → Flask API → GPIO motor control
4. **Storage**: Detection results → Firebase database

## API Endpoints

### Pi Server (Port 5000)

- **GET** `/video_feed` - MJPEG video stream
- **POST** `/move/forward` - Move forward
- **POST** `/move/backward` - Move backward
- **POST** `/move/left` - Turn left
- **POST** `/move/right` - Turn right
- **POST** `/move/stop` - Stop all motors
- **GET** `/health` - Health check

### AI Backend (Port 5001)

- **GET** `/video_feed` - Annotated video stream
- **GET** `/detections` - Latest detection results
- **POST** `/start_session` - Begin recording session
- **POST** `/end_session` - End recording session

## Troubleshooting

### Common Issues

**No video stream:**
- Run `ls /dev/video*` on Pi to check camera detection
- Change `device_index` in `pi/camera/usb_camera.py` if needed
- Ensure camera is UVC compatible

**Motor not responding:**
- Verify GPIO pin numbers in `pi/gpio_config.py`
- Check physical wiring connections
- Ensure proper power supply (7.4V for motors)

**CORS errors:**
- Install `flask-cors` on both Pi and laptop
- Verify frontend and backend are on same network

**High latency:**
- Reduce JPEG quality in `pi/camera/usb_camera.py` (try 55)
- Check Wi-Fi signal strength
- Consider wired Ethernet connection

**YOLOv8 slow performance:**
- Model auto-downloads on first run
- For NVIDIA GPU: `pip install torch torchvision`
- Consider using smaller model variant

### Debug Commands

```bash
# Check camera availability
ls /dev/video*

# Test GPIO pins
python3 -c "import RPi.GPIO as GPIO; print('GPIO available')"

# Check network connectivity
hostname -I

# Monitor system resources
htop
```

## Development

### Adding New Features

1. **Pi Server**: Add new endpoints in `pi/app.py`
2. **AI Backend**: Extend detection logic in `laptop/backend/detector/`
3. **Frontend**: Create new components in `laptop/frontend/src/components/`

### Testing

```bash
# Test Pi server
curl http://[PI_IP]:5000/health

# Test motor control
curl -X POST http://[PI_IP]:5000/move/forward

# Test video stream
ffplay http://[PI_IP]:5000/video_feed
```

## Safety Notes

- Always ensure proper power isolation when working with motors
- Use appropriate fuses for motor power circuits
- Keep camera lens clean for optimal video quality
- Monitor battery voltage to prevent over-discharge
- Operate in well-ventilated areas when using gas sensors

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## Support

For technical issues and support:
- Check the troubleshooting section above
- Review the individual component README files
- Submit issues to the GitHub repository