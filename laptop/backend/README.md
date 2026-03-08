# Laptop AI Backend

## Overview
- Pulls MJPEG stream from Pi
- Runs YOLOv8n inference
- Serves annotated stream + detection data to React frontend

## Installation

```bash
cd laptop/backend
pip install -r requirements.txt
```

## Configuration

Edit `ai_server.py` line:
```python
PI_IP = '192.168.1.100'   # Change to your Pi's IP
```

## Run

```bash
python ai_server.py
```

Server starts on port 8000.

## Endpoints

| Endpoint         | Method | Description                        |
|------------------|--------|------------------------------------|
| /stream          | GET    | Annotated MJPEG stream             |
| /detections      | GET    | JSON snapshot of detections        |
| /detections/sse  | GET    | SSE stream of detection updates    |
| /ai/toggle       | POST   | Toggle AI overlay on/off           |
| /ai/status       | GET    | Current AI status                  |
| /move/<dir>      | POST   | Proxy motor command to Pi          |
| /health          | GET    | Health + connection status         |
