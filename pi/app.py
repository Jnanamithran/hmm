# =============================================================================
# pi/app.py  —  v9  —  VIPER Pi server
# =============================================================================
#
# SENSORS + HARDWARE:
#   USB Camera   → /dev/video0  → /video_feed   (MJPEG stream)
#   MLX90640     → I2C 0x33    → /thermal_feed  (MJPEG heatmap)
#   MQ4 + ADS1115→ I2C 0x48    → /gas           (methane PPM)
#   L298N motors → GPIO BCM    → /move/<dir>
#
# I2C INIT ORDER (prevents [Errno 121] / [Errno 5]):
#   1. Create shared i2c_lock FIRST
#   2. thermal.init_hardware()
#   3. Forced getFrame() warmup
#   4. 0.5s idle gap
#   5. gas.init_hardware()
#   6. Both sensor threads start
#
# ALL ENDPOINTS:
#   GET  /video_feed
#   GET  /thermal_feed
#   GET  /thermal/stats
#   GET  /thermal/colormap/<n>
#   GET  /gas
#   POST /move/forward|backward|left|right|stop
#   GET  /move/status
#   GET  /health
# =============================================================================

import logging, os, signal, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify
from flask_cors import CORS

from camera.usb_camera       import USBCamera
from motors.l298n             import MotorController
from sensors.mlx90640_sensor  import MLX90640Sensor
from sensors.mq4              import MQ4Sensor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PI] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── CPU temp ──────────────────────────────────────────────────────────────────
def _read_cpu_temp():
    try:
        r   = subprocess.run(["vcgencmd", "measure_temp"],
                             capture_output=True, text=True, timeout=1)
        val = r.stdout.strip().split("=")[1].rstrip("'C")
        return round(float(val), 1)
    except Exception:
        pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass
    return None

# ── Release camera ────────────────────────────────────────────────────────────
def _release_camera():
    """Kill any process holding /dev/video0 and wait until it's free."""
    try:
        import subprocess as _sp
        for attempt in range(3):
            r    = _sp.run(["fuser", "/dev/video0"], capture_output=True, text=True)
            pids = r.stdout.strip().split()
            if not pids:
                break   # device is free
            log.warning("Releasing /dev/video0 held by PID(s): %s (attempt %d/3)",
                        " ".join(pids), attempt + 1)
            _sp.run(["fuser", "-k", "/dev/video0"], capture_output=True)
            time.sleep(1.5)   # wait longer for device to fully release
    except FileNotFoundError:
        pass   # fuser not available

# ── App + hardware ────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

_release_camera()

camera  = USBCamera(device_index=0, resolution=(640, 480), jpeg_quality=75)
motors  = MotorController()
thermal = MLX90640Sensor(colormap="inferno", flip_h=True)
gas     = MQ4Sensor(i2c_address=0x48, channel=0)

# =============================================================================
# Routes — Camera
# =============================================================================

@app.route("/video_feed")
def video_feed():
    return Response(camera.generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

# =============================================================================
# Routes — Thermal
# =============================================================================

@app.route("/thermal_feed")
def thermal_feed():
    return Response(thermal.read_jpeg_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/thermal/stats")
def thermal_stats():
    return jsonify(thermal.stats())

@app.route("/thermal/colormap/<name>")
def set_colormap(name):
    thermal.set_colormap(name)
    return jsonify({"colormap": name, "ok": True})

# =============================================================================
# Routes — Gas
# =============================================================================

@app.route("/gas")
def gas_reading():
    return jsonify(gas.read())

# =============================================================================
# Routes — Motors
# =============================================================================

def _motor_ok(d): return jsonify({"status": "ok", "direction": d})

@app.route("/move/forward",  methods=["POST"])
def move_forward():  motors.forward();  return _motor_ok("forward")

@app.route("/move/backward", methods=["POST"])
def move_backward(): motors.backward(); return _motor_ok("backward")

@app.route("/move/left",     methods=["POST"])
def move_left():     motors.left();     return _motor_ok("left")

@app.route("/move/right",    methods=["POST"])
def move_right():    motors.right();    return _motor_ok("right")

@app.route("/move/stop",     methods=["POST"])
def move_stop():     motors.stop();     return _motor_ok("stop")

@app.route("/move/status",   methods=["GET"])
def move_status():   return jsonify({"direction": motors.direction})

# =============================================================================
# Routes — Health
# =============================================================================

@app.route("/health")
def health():
    g        = gas.read()
    cpu_temp = _read_cpu_temp()
    t_min    = thermal.min_temp
    t_max    = thermal.max_temp
    t_avg    = round((t_min + t_max) / 2.0, 1) if t_min and t_max else None

    temp_status = ("critical" if cpu_temp and cpu_temp > 70
                   else "warning" if cpu_temp and cpu_temp > 55
                   else "ok")

    return jsonify({
        "status":          "ok",
        "camera_open":     camera.is_open,
        "thermal_sensor":  thermal.available,
        "thermal_min_c":   t_min,
        "thermal_max_c":   t_max,
        "thermal_avg_c":   t_avg,
        "gas_sensor":      gas.available,
        "gas_ppm":         g.get("ppm"),
        "gas_level":       g.get("level"),
        "pi_temp":         cpu_temp,
        "pi_temp_status":  temp_status,
        "battery_voltage": None,
    })

# =============================================================================
# Graceful shutdown
# =============================================================================

def _shutdown(sig, frame):
    log.info("Shutting down ...")
    motors.stop()
    motors.cleanup()
    camera.release()
    thermal.stop()
    gas.stop()
    log.info("All hardware released. Goodbye.")
    sys.exit(0)

signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# =============================================================================
# Startup sequence
# =============================================================================

if __name__ == "__main__":

    # 1. Camera
    camera._start_thread()
    log.info("Camera background thread started")

    # 2. Shared I2C lock
    _i2c_lock         = threading.Lock()
    thermal._i2c_lock = _i2c_lock
    gas._i2c_lock     = _i2c_lock
    log.info("Shared I2C bus lock created and assigned to both sensors")

    # 3. MLX90640 init
    log.info("Initialising thermal sensor ...")
    thermal.init_hardware()

    # 4. Warmup frame
    if thermal.available:
        buf = [0.0] * 768
        for attempt in range(3):
            try:
                thermal._sensor.getFrame(buf)
                log.info("MLX90640 frame read OK — I2C bus idle")
                break
            except Exception as exc:
                log.warning("MLX90640 warmup attempt %d/3: %s", attempt + 1, exc)
                time.sleep(0.5)

    # 5. Bus settle
    time.sleep(0.5)

    # 6. ADS1115 / MQ4 init
    log.info("Initialising gas sensor ...")
    gas.init_hardware()

    # 7. Start threads
    log.info("Starting sensor threads ...")
    thermal.start_thread()
    gas.start_thread()

    # 8. Flask
    log.info("Pi server → http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)