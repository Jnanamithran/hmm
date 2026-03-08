# ROVER — Tracked Robot Control System

## System Overview

```
[USB Camera] --> [Raspberry Pi 3B+] --> Wi-Fi --> [Laptop AI Backend] --> [React Frontend]
                 Flask MJPEG server              YOLOv8 inference        Browser UI
                 GPIO motor control              Annotated stream
```

## Quick Start

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

## GPIO Wiring (L298N -> Pi BCM)

| Signal | GPIO | Pin |
|--------|------|-----|
| L_IN1  |  17  |  11 |
| L_IN2  |  27  |  13 |
| L_ENA  |  22  |  15 |
| R_IN3  |  23  |  16 |
| R_IN4  |  24  |  18 |
| R_ENB  |  25  |  22 |

## Troubleshooting

- **No video**: Run `ls /dev/video*` on Pi. Change `device_index` in `usb_camera.py` if needed.
- **Motor not moving**: Check `gpio_config.py` pin numbers match your physical wiring.
- **CORS errors**: Make sure `flask-cors` is installed on both Pi and laptop.
- **High latency**: Reduce JPEG quality in `usb_camera.py` (try 55).
- **YOLOv8 slow**: It auto-downloads on first run. If laptop has NVIDIA GPU, `pip install torch torchvision` first.
