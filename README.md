# VIPER — Visual Inspection Platform for Infrastructure Evaluation and Repair
> **FINAL COMMIT VERSION** | This README is prepared for laptop reset. All exact versions & setup steps are documented fully.

---

## 🛑 PRE-LAPTOP RESET SETUP GUIDE
When you reset your laptop, follow this EXACT order. Do not skip steps.

---

## ✅ THINGS YOU NEED TO INSTALL FIRST
After Windows reset, install these before touching the project:

| Software | Version | Download Link | Verification Command |
|----------|---------|---------------|----------------------|
| Python | 3.11.x (⚠️ NOT 3.12+) | https://www.python.org/downloads/release/python-3118/ | `python --version` |
| Git | Latest | https://git-scm.com/download/win | `git --version` |
| Node.js | 20.x LTS | https://nodejs.org/en/download/ | `node --version` |
| Visual C++ Redistributable | 2015+ | https://aka.ms/vs/17/release/vc_redist.x64.exe | (Required for OpenCV) |

✅ **IMPORTANT**: When installing Python, CHECK THE BOX: `Add Python to PATH`

---

## 📦 FULL PROJECT SETUP
### Step 1 - Clone the repository
```cmd
cd s:\
mkdir Dev
cd Dev
git clone git@github.com:Jnanamithran/hmm.git VIPER-vx
cd VIPER-vx
```

---

### Step 2 - Virtual Environment Setup (NEVER INSTALL GLOBALLY)
✅ **This is the most important part you always forget**

#### On your Laptop:
```cmd
# Create virtual environment
python -m venv venv

# Activate venv (WINDOWS CMD EXACT COMMAND)
venv\Scripts\activate.bat

# ✅ You will see (venv) at the start of your prompt now. ALWAYS activate before working.

# Upgrade pip first
python -m pip install --upgrade pip==24.0
```

✅ **Remember**: Always run the activate command first in every new terminal.

---

### Step 3 - Install ALL Dependencies with EXACT VERSIONS

#### 🔹 Laptop AI Backend:
```cmd
# With venv activated:
cd laptop/backend
pip install -r requirements.txt
```

These will be installed:
| Package | Exact Version |
|---------|---------------|
| Flask | 3.0.3 |
| Flask-CORS | 4.0.1 |
| Ultralytics (YOLOv8) | Latest |
| OpenCV | 4.9.0 |
| Numpy | 1.26.4 |
| Requests | 2.31.0 |
| Firebase Admin | 6.5.0 |

#### 🔹 Laptop Frontend:
```cmd
cd ../frontend
npm install
```

#### 🔹 Raspberry Pi Setup:
```bash
# On Raspberry Pi:
cd pi
sudo apt update
sudo apt install python3-venv python3-opencv

python3 -m venv venv
source venv/bin/activate

pip3 install --upgrade pip
pip3 install -r requirements.txt
```

Pi exact requirements:
| Package | Version |
|---------|---------|
| Flask | 3.0.3 |
| Flask-CORS | 4.0.1 |
| OpenCV Headless | 4.9.0.80 |
| RPi.GPIO | 0.7.1 |
| Adafruit Blinka | 8.32.0 |
| MLX90640 Thermal | 1.2.13 |
| ADS1x15 ADC | 2.6.23 |

---

### Step 4 - Configure System
1. Find your Raspberry Pi IP:
```bash
# On Pi:
hostname -I
```

2. Edit `laptop/backend/ai_server.py`:
```python
PI_IP = '192.168.1.XXX'   # Paste your Pi IP here
```

---

### Step 5 - Start Everything In Order
✅ **Start in this EXACT order**:

1. **First: Pi Server**
```bash
# On Pi, venv activated:
cd pi
python app.py
```

2. **Second: Laptop AI Backend**
```cmd
# On laptop, venv activated:
cd laptop/backend
python ai_server.py
```

3. **Third: Frontend UI**
```cmd
cd laptop/frontend
npm run dev
```

✅ Open: `http://localhost:5173` in browser

---

## System Overview
VIPER is an advanced robotic inspection system designed for infrastructure monitoring and crack detection. The system combines a tracked robot platform with AI-powered computer vision to autonomously detect and analyze structural damage.

```
[USB Camera] --> [Raspberry Pi 3B+] --> Wi-Fi --> [Laptop AI Backend] --> [React Frontend]
                 Flask MJPEG server              YOLOv8 inference        Browser UI
                 GPIO motor control              Annotated stream
```

---

## Key Features
- **Real-time Video Streaming**: MJPEG video feed from USB camera
- **AI-Powered Detection**: YOLOv8 model for crack detection and analysis
- **Remote Control**: Web-based interface for robot operation
- **Data Logging**: Firebase integration for session recording and analysis
- **Multi-Sensor Support**: Thermal imaging and gas detection capabilities

---

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

---

## API Endpoints
### Pi Server (Port 5000)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/video_feed` | MJPEG video stream |
| POST | `/move/forward` | Move forward |
| POST | `/move/backward` | Move backward |
| POST | `/move/left` | Turn left |
| POST | `/move/right` | Turn right |
| POST | `/move/stop` | Stop all motors |
| GET | `/health` | Health check |

### AI Backend (Port 5001)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/video_feed` | Annotated video stream |
| GET | `/detections` | Latest detection results |
| POST | `/start_session` | Begin recording session |
| POST | `/end_session` | End recording session |

---

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

---

## 📝 REMINDERS FOR AFTER LAPTOP RESET
1. Always activate venv first before running any python commands
2. Never use `sudo pip install` on Pi
3. YOLOv8 will download 150MB model on first run
4. Firebase service account key is not in git, you have backup on Google Drive
5. Camera device index is usually 0 or 1

---

## Safety Notes
- Always ensure proper power isolation when working with motors
- Use appropriate fuses for motor power circuits
- Keep camera lens clean for optimal video quality
- Monitor battery voltage to prevent over-discharge
- Operate in well-ventilated areas when using gas sensors

---

## License
This project is licensed under the MIT License.

---

> **FINAL COMMIT** | This is the last commit of this project. All documentation complete.
> Project closed 04/05/2026