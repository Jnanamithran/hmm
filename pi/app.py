# =============================================================================
# pi/app.py  —  v5
# =============================================================================
# I2C INIT ORDER (solves ADS1115 [Errno 121]):
#   1. thermal.init_hardware() — creates sensor, reads EEPROM synchronously
#   2. Forced getFrame() loop  — drains any remaining I2C traffic on main thread
#   3. 0.5s idle gap           — bus fully quiet
#   4. gas.init_hardware()     — ADS1115 config, bus is guaranteed idle
#   5. thermal.start_thread()  — background 4 Hz loop begins
#   6. gas.start_thread()      — background 2 Hz polling begins
# =============================================================================

import logging, signal, sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify
from flask_cors import CORS

from camera.usb_camera      import USBCamera
from motors.l298n            import MotorController
from sensors.mlx90640_sensor import MLX90640Sensor
from sensors.mq4             import MQ4Sensor

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [PI] %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ── Hardware ──────────────────────────────────────────────────────────────────
camera  = USBCamera(device_index=0, resolution=(640, 480), jpeg_quality=75)
motors  = MotorController()
thermal = MLX90640Sensor(colormap="inferno", flip_h=True)
gas     = MQ4Sensor(i2c_address=0x48, channel=0)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/video_feed")
def video_feed():
    return Response(camera.generate_frames(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/thermal_feed")
def thermal_feed():
    return Response(thermal.read_jpeg_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/thermal/stats")
def thermal_stats():
    return jsonify(thermal.stats())

@app.route("/thermal/colormap/<n>")
def set_colormap(name):
    thermal.set_colormap(name)
    return jsonify({"colormap": name, "ok": True})

@app.route("/gas")
def gas_reading():
    return jsonify(gas.read())

def _ok(d): return jsonify({"status": "ok", "direction": d})

@app.route("/move/forward",  methods=["POST"])
def fwd(): motors.forward();  return _ok("forward")
@app.route("/move/backward", methods=["POST"])
def bwd(): motors.backward(); return _ok("backward")
@app.route("/move/left",     methods=["POST"])
def lft(): motors.left();     return _ok("left")
@app.route("/move/right",    methods=["POST"])
def rgt(): motors.right();    return _ok("right")
@app.route("/move/stop",     methods=["POST"])
def stp(): motors.stop();     return _ok("stop")
@app.route("/move/status",   methods=["GET"])
def mst(): return jsonify({"direction": motors.direction})

@app.route("/health")
def health():
    g = gas.read()
    return jsonify({
        "status":         "ok",
        "camera_open":    camera.is_open,
        "thermal_sensor": thermal.available,
        "thermal_min_c":  thermal.min_temp,
        "thermal_max_c":  thermal.max_temp,
        "gas_sensor":     gas.available,
        "gas_ppm":        g.get("ppm"),
        "gas_level":      g.get("level"),
    })


# ── Shutdown ──────────────────────────────────────────────────────────────────
def _shutdown(sig, frame):
    log.info("Shutting down ...")
    motors.cleanup()
    camera.release()
    thermal.stop()
    gas.stop()
    sys.exit(0)

signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


# ── Startup ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    # 1. Camera — V4L2, independent of I2C
    camera._start_thread()
    log.info("Camera background thread started")

    # 2. MLX90640 hardware init (creates sensor object, reads EEPROM params)
    log.info("Initialising thermal sensor ...")
    thermal.init_hardware()

    # 3. Force one complete getFrame() on the main thread so the full EEPROM
    #    I2C burst finishes here — not racing with ADS1115 init later.
    if thermal.available:
        buf = [0.0] * 768
        for attempt in range(3):
            try:
                thermal._sensor.getFrame(buf)
                log.info("MLX90640 frame read OK — I2C bus idle")
                break
            except Exception as e:
                log.warning("Frame warmup attempt %d/3: %s", attempt + 1, e)
                time.sleep(0.5)

    # 4. Let bus settle completely before touching ADS1115
    time.sleep(0.5)

    # 5. ADS1115 init — I2C bus is now fully idle
    log.info("Initialising gas sensor ...")
    gas.init_hardware()

    # 6. Give both sensors the same threading.Lock so their I2C transactions
    #    are serialised — MLX90640 getFrame() takes ~400ms at 100kHz and
    #    collides with ADS1115 reads without this guard.
    import threading as _th
    _i2c_lock = _th.Lock()
    thermal._i2c_lock = _i2c_lock
    gas._i2c_lock     = _i2c_lock
    log.info("Shared I2C bus lock installed")

    # 7. Start both background threads — hardware fully configured
    log.info("Starting sensor threads ...")
    thermal.start_thread()
    gas.start_thread()

    log.info("Pi server → http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)