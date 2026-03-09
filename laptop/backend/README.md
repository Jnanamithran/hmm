# VIPER AI Backend

## Overview

The VIPER AI Backend is the intelligent processing center of the robotic inspection system. It connects to the Pi robot server to receive live video streams, applies AI-powered crack detection using YOLOv8, and serves annotated video and detection data to the React frontend for real-time monitoring and analysis.

## Key Features

- **Real-time Video Processing**: Pulls MJPEG stream from Pi robot server
- **AI-Powered Detection**: YOLOv8 model for crack detection and analysis
- **Annotated Stream**: Overlays detection results on live video feed
- **Detection API**: Provides both snapshot and streaming detection data
- **Motor Control Proxy**: Forwards control commands to the robot
- **Health Monitoring**: System status and connection health checks

## System Architecture

```
[Pi Robot Server] --> [AI Backend] --> [React Frontend]
    MJPEG Stream      YOLOv8 Inference    Annotated Video
                      Detection Analysis    Detection Data
```

## Installation

### Prerequisites

- Python 3.8 or higher
- NVIDIA GPU (recommended for optimal performance)
- CUDA toolkit (if using GPU acceleration)

### Setup

```bash
cd laptop/backend
pip install -r requirements.txt
```

**For NVIDIA GPU users:**
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

## Configuration

### Basic Configuration

Edit `ai_server.py` line 12:
```python
PI_IP = '192.168.1.100'   # Change to your Pi's actual IP address
```

### Advanced Configuration

The backend supports several configuration options:

- **Model Selection**: Choose between different YOLOv8 model variants
- **Detection Threshold**: Adjust sensitivity for crack detection
- **Stream Quality**: Configure video processing parameters
- **GPU/CPU Mode**: Toggle between GPU acceleration and CPU-only processing

## Quick Start

### 1. Start the AI Backend

```bash
python ai_server.py
```

The server will start on port 8000 by default.

### 2. Verify Connection

Check that the backend can connect to the Pi:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "pi_connected": true,
  "ai_enabled": true,
  "model_loaded": true
}
```

### 3. Access the Stream

Open your browser and navigate to:
- **Annotated Video**: `http://localhost:8000/stream`
- **Detection Data**: `http://localhost:8000/detections`

## API Endpoints

### Video and Detection Endpoints

| Endpoint         | Method | Description                        | Response Format |
|------------------|--------|------------------------------------|-----------------|
| `/stream`        | GET    | Annotated MJPEG video stream       | MJPEG stream    |
| `/detections`    | GET    | JSON snapshot of current detections| JSON object     |
| `/detections/sse`| GET    | Server-Sent Events stream of detection updates | SSE stream |
| `/ai/toggle`     | POST   | Toggle AI overlay on/off           | JSON status     |
| `/ai/status`     | GET    | Current AI processing status       | JSON status     |

### Motor Control Endpoints

| Endpoint         | Method | Description                        | Response Format |
|------------------|--------|------------------------------------|-----------------|
| `/move/forward`  | POST   | Move robot forward                 | JSON status     |
| `/move/backward` | POST   | Move robot backward                | JSON status     |
| `/move/left`     | POST   | Turn robot left                    | JSON status     |
| `/move/right`    | POST   | Turn robot right                   | JSON status     |
| `/move/stop`     | POST   | Stop all motors                    | JSON status     |

### System Endpoints

| Endpoint         | Method | Description                        | Response Format |
|------------------|--------|------------------------------------|-----------------|
| `/health`        | GET    | System health and connection status| JSON status     |

## Detection Analysis

### Crack Detection

The AI backend uses a pre-trained YOLOv8 model to detect cracks in the video stream. The system provides:

- **Real-time Detection**: Live crack identification with bounding boxes
- **Confidence Scoring**: Probability scores for each detection
- **Size Analysis**: Crack dimensions and severity assessment
- **Historical Tracking**: Detection history for trend analysis

### Data Output

Detection results include:
```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "detections": [
    {
      "class": "crack",
      "confidence": 0.95,
      "bbox": [x1, y1, x2, y2],
      "severity": "high",
      "dimensions": {
        "width": 15.2,
        "length": 45.8
      }
    }
  ],
  "frame_id": 1234
}
```

## Performance Optimization

### GPU Acceleration

For optimal performance with NVIDIA GPUs:

1. Install CUDA-compatible PyTorch:
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
   ```

2. Verify GPU availability:
   ```python
   import torch
   print(f"CUDA available: {torch.cuda.is_available()}")
   print(f"GPU count: {torch.cuda.device_count()}")
   ```

### CPU Optimization

For CPU-only systems:

1. Use smaller model variants for faster inference
2. Adjust detection threshold to balance speed vs accuracy
3. Reduce video resolution if processing is slow

### Memory Management

The backend automatically manages memory usage:
- Model weights are loaded once at startup
- Video frames are processed in batches
- Old detection data is periodically cleaned up

## Troubleshooting

### Common Issues

**Model not loading:**
- Check internet connection (model downloads on first run)
- Verify sufficient disk space for model files
- Check Python version compatibility

**High latency:**
- Reduce video resolution in Pi server
- Use smaller model variant
- Check network bandwidth

**No detections:**
- Verify camera is working on Pi
- Check detection threshold settings
- Ensure proper lighting conditions

**Connection issues:**
- Verify Pi IP address is correct
- Check firewall settings
- Ensure both devices are on same network

### Debug Commands

```bash
# Check system health
curl http://localhost:8000/health

# Test motor control
curl -X POST http://localhost:8000/move/forward

# Get current detections
curl http://localhost:8000/detections

# Monitor detection stream
curl http://localhost:8000/detections/sse
```

## Integration with Frontend

The AI backend is designed to work seamlessly with the React frontend:

1. **Video Stream**: Frontend displays annotated video from `/stream`
2. **Detection Data**: Real-time updates via SSE or polling
3. **Control Interface**: Motor commands sent through backend proxy
4. **Session Management**: Detection history and session logging

## Development

### Adding Custom Models

To use a custom YOLOv8 model:

1. Place model file in `detector/models/`
2. Update model path in `detector/model.py`
3. Adjust class names if needed

### Extending Detection

To add new detection classes:

1. Retrain YOLOv8 model with additional classes
2. Update class mapping in `detector/model.py`
3. Modify frontend to handle new detection types

### Performance Monitoring

The backend includes built-in performance monitoring:
- Frame processing time
- Detection accuracy metrics
- Memory usage tracking
- Network latency monitoring

## Security Considerations

- API endpoints are accessible on local network only
- No authentication required for local development
- Consider adding authentication for production use
- Monitor network traffic for security

## Support

For technical issues and support:
- Check the troubleshooting section above
- Review the main VIPER README
- Submit issues to the GitHub repository