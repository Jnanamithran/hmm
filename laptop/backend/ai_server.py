# =============================================================================
# laptop/backend/ai_server.py  v4  —  server-side thermal blending
# =============================================================================
#
# KEY CHANGE v4: thermal overlay is done SERVER-SIDE in OpenCV.
#   Instead of sending a separate /thermal_feed to the browser and relying on
#   CSS mix-blend-mode (unreliable, no depth), the laptop now:
#     1. Holds the latest thermal BGR frame from Pi
#     2. In _cam_generator, if thermal_overlay=True, blends it onto the camera
#        frame with cv2.addWeighted before encoding the JPEG
#   Result: one stream to the browser, perfect pixel-aligned blend, gets
#   recorded automatically, no CSS complexity.
#
# THREADS:
#   _raw_reader     reads Pi camera MJPEG → _raw_jpeg  (never blocked)
#   _infer_worker   runs YOLO on _raw_jpeg → _annotated_jpeg
#   _thermal_reader reads Pi thermal MJPEG → _therm_bgr (decoded BGR, not JPEG)
#   _gas_poller     polls /gas every 500ms → _gas_data
#
# ENDPOINTS (port 8000):
#   GET  /stream              blended MJPEG (camera + optional thermal + AI boxes)
#   GET  /detections          YOLO detections JSON
#   GET  /gas                 MQ4 gas JSON
#   GET  /health              full status
#   POST /ai/toggle           toggle YOLO boxes
#   POST /thermal/toggle      toggle thermal blend
#   POST /thermal/opacity     set thermal blend alpha {"alpha": 0.0-1.0}
#   POST /move/<dir>          motor proxy
#   GET  /recording/status    recording info
#   POST /recording/start     start recording
#   POST /recording/stop      stop recording
# =============================================================================

import cv2, json, logging, numpy as np, os, threading, time
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from detector.model import YOLODetector

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [LAPTOP] %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
PI_IP   = os.environ.get("PI_IP",   "10.86.22.170")
PI_PORT = int(os.environ.get("PI_PORT", "5000"))
PI_BASE = f"http://{PI_IP}:{PI_PORT}"
log.info("Pi target: %s", PI_BASE)

RECORDINGS_DIR = Path(__file__).parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
CORS(app)

# ── Shared state ──────────────────────────────────────────────────────────────
_raw_lock    = threading.Lock()
_ann_lock    = threading.Lock()
_therm_lock  = threading.Lock()
_det_lock    = threading.Lock()
_gas_lock    = threading.Lock()

_raw_jpeg    = None          # latest raw JPEG bytes from Pi camera
_ann_jpeg    = None          # latest annotated+blended JPEG bytes
_therm_bgr   = None          # latest thermal decoded as BGR numpy (640×480)
_detections  = []
_gas_data    = {"available": False, "ppm": None, "level": "OFFLINE",
                "voltage": None, "gas": "CH4 / Methane", "sensor": "MQ4"}
_ai_enabled        = True
_thermal_enabled   = False   # server-side thermal blend toggle
_thermal_alpha     = 0.45    # blend weight for thermal (0.0 = camera only, 1.0 = thermal only)
_pi_connected      = False
_crack_enabled     = True    # toggle crack detection pipeline
_defect_lock       = threading.Lock()
_latest_defect     = {       # last defect report — served at /defects
    "timestamp":      None,
    "crack_count":    0,
    "critical_count": 0,
    "moderate_count": 0,
    "minor_count":    0,
    "worst_severity": "NONE",
    "max_width_mm":   0.0,
    "max_length_mm":  0.0,
    "max_growth_pct": 0.0,
    "cracks":         [],
}

# ── Load YOLO ─────────────────────────────────────────────────────────────────
log.info("Loading YOLOv8n ...")
detector = YOLODetector(model_path="yolov8n.pt", confidence=0.40, crack_enabled=_crack_enabled)
detector.warmup()
log.info("YOLOv8n ready")


# =============================================================================
# MJPEG stream parser
# =============================================================================

def _iter_mjpeg(resp):
    """Parse MJPEG HTTP response into individual JPEG byte strings."""
    buf = b""
    for chunk in resp.iter_content(chunk_size=16384):
        buf += chunk
        while True:
            s = buf.find(b"\xff\xd8")
            e = buf.find(b"\xff\xd9", s + 2) if s != -1 else -1
            if s == -1 or e == -1:
                break
            yield buf[s: e + 2]
            buf = buf[e + 2:]


# =============================================================================
# Thread A — Raw camera reader
# =============================================================================

def _raw_reader():
    global _raw_jpeg, _pi_connected
    while True:
        try:
            log.info("Connecting to Pi camera ...")
            r = requests.get(f"{PI_BASE}/video_feed", stream=True, timeout=8)
            r.raise_for_status()
            _pi_connected = True
            log.info("Pi camera connected")
            for jpg in _iter_mjpeg(r):
                with _raw_lock:
                    _raw_jpeg = jpg
        except requests.ConnectionError:
            _pi_connected = False
            log.warning("Pi camera offline — retry in 3s")
        except Exception as exc:
            _pi_connected = False
            log.error("Raw reader: %s — retry in 3s", exc)
        time.sleep(3)


# =============================================================================
# Thread B — Inference + thermal blend worker
# =============================================================================

def _blend_thermal(camera_bgr):
    """
    Blend thermal frame onto camera frame using cv2.addWeighted.
    camera_bgr: numpy BGR frame
    Returns blended BGR frame.
    """
    with _therm_lock:
        therm = _therm_bgr

    if therm is None:
        return camera_bgr   # no thermal data yet — return camera unchanged

    # Resize thermal to match camera if needed (both should be 640×480)
    if therm.shape[:2] != camera_bgr.shape[:2]:
        therm = cv2.resize(therm, (camera_bgr.shape[1], camera_bgr.shape[0]))

    cam_w   = 1.0 - _thermal_alpha
    therm_w = _thermal_alpha
    return cv2.addWeighted(camera_bgr, cam_w, therm, therm_w, 0)


def _infer_worker():
    global _ann_jpeg, _detections
    enc      = [cv2.IMWRITE_JPEG_QUALITY, 97]   # max quality — recorded to disk
    last_raw = None

    while True:
        with _raw_lock:
            raw = _raw_jpeg

        if raw is None or raw is last_raw:
            time.sleep(0.005)
            continue

        last_raw = raw
        arr   = np.frombuffer(raw, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            continue

        try:
            # 1. Run YOLO + crack pipeline if enabled
            if _ai_enabled:
                annotated, dets = detector.detect(frame)
                # Pull latest defect report into shared state
                from detector.model import latest_defect_report as _ldr
                if _ldr is not None:
                    import dataclasses
                    with _defect_lock:
                        global _latest_defect
                        _latest_defect = dataclasses.asdict(_ldr)
            else:
                annotated, dets = frame, []

            # 2. Blend thermal if enabled
            if _thermal_enabled:
                annotated = _blend_thermal(annotated)

            # 3. Encode final frame
            ok, buf = cv2.imencode(".jpg", annotated, enc)
            if ok:
                with _ann_lock:
                    _ann_jpeg = buf.tobytes()
                with _det_lock:
                    _detections = dets

        except Exception as exc:
            log.error("Worker error: %s", exc)


# =============================================================================
# Thread C — Thermal stream reader (stores decoded BGR, not JPEG)
# =============================================================================

def _thermal_reader():
    """
    Reads Pi's thermal MJPEG, decodes each JPEG to BGR numpy array.
    Stored as BGR (not JPEG) so _infer_worker can blend directly with OpenCV.
    No need to re-decode in the blend path.
    """
    global _therm_bgr
    while True:
        try:
            log.info("Connecting to Pi thermal ...")
            r = requests.get(f"{PI_BASE}/thermal_feed", stream=True, timeout=15)
            r.raise_for_status()
            log.info("Pi thermal connected")
            for jpg in _iter_mjpeg(r):
                arr  = np.frombuffer(jpg, np.uint8)
                bgr  = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if bgr is not None:
                    with _therm_lock:
                        _therm_bgr = bgr
        except requests.ConnectionError:
            log.warning("Pi thermal offline — retry in 5s")
        except Exception as exc:
            log.error("Thermal reader: %s — retry in 5s", exc)
        time.sleep(5)


# =============================================================================
# Thread D — Gas poller
# =============================================================================

def _gas_poller():
    global _gas_data
    while True:
        try:
            r = requests.get(f"{PI_BASE}/gas", timeout=2)
            if r.status_code == 200:
                with _gas_lock:
                    _gas_data = r.json()
        except Exception:
            pass
        time.sleep(0.5)


threading.Thread(target=_raw_reader,     daemon=True, name="raw-reader").start()
threading.Thread(target=_infer_worker,   daemon=True, name="infer-worker").start()
threading.Thread(target=_thermal_reader, daemon=True, name="thermal-reader").start()
threading.Thread(target=_gas_poller,     daemon=True, name="gas-poller").start()


# =============================================================================
# VideoRecorder
# =============================================================================

class VideoRecorder:
    """
    Real-time video recorder.

    FAST-FORWARD FIX:
        The old recorder drained the entire frame queue every tick.
        If 5 frames queued up between ticks, all 5 got written at the
        VideoWriter's declared fps — resulting in 5× fast-forward.

        Fix: _loop writes exactly ONE frame per tick (the most recent one),
        dropping any intermediates. This matches wall-clock time to
        video time precisely.

    QUALITY:
        - Codec: MJPG in .avi — each frame stored as a near-lossless JPEG.
          No inter-frame compression, no motion artefacts, no quality loss.
        - Source JPEG quality bumped to 97 in _cam_generator.
        - FPS: 20 — matches the camera's effective rate.
    """

    def __init__(self, fps=20, width=640, height=480):
        self.fps    = fps
        self.width  = width
        self.height = height
        self._writer   = None
        self._filename = None
        self._running  = False
        self._lock     = threading.Lock()
        # Single-slot buffer — only the LATEST frame is kept.
        # Older frames between ticks are discarded (prevents fast-forward).
        self._latest      = None
        self._latest_lock = threading.Lock()
        self._thread   = None
        self._start_ts = None
        self._nframes  = 0

    def start(self):
        with self._lock:
            if self._running:
                return False
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            # MJPG in AVI: near-lossless, widely compatible, no re-encoding
            self._filename = str(RECORDINGS_DIR / f"{ts}.avi")
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self._writer = cv2.VideoWriter(
                self._filename, fourcc, self.fps, (self.width, self.height))
            if not self._writer.isOpened():
                # Fallback to mp4v if MJPG not available
                self._filename = str(RECORDINGS_DIR / f"{ts}.mp4")
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self._writer = cv2.VideoWriter(
                    self._filename, fourcc, self.fps, (self.width, self.height))
            if not self._writer.isOpened():
                log.error("VideoWriter failed: %s", self._filename)
                return False
            self._running  = True
            self._start_ts = time.time()
            self._nframes  = 0
            self._latest   = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Recording: %s", self._filename)
        return True

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            if self._writer:
                self._writer.release()
                self._writer = None

    def write(self, jpeg_bytes):
        """
        Accept a new JPEG frame from the stream generator.
        Only stores it — does NOT decode here. Decoding happens in _loop
        on the recorder thread so the stream generator is never slowed down.
        """
        if not self._running:
            return
        with self._latest_lock:
            # Overwrite previous — only the newest frame matters
            self._latest = jpeg_bytes

    def _loop(self):
        """
        Writes exactly one frame every (1/fps) seconds.
        Takes the most recent frame available; if none arrived since the
        last tick, repeats the previous frame (freeze rather than skip).
        This keeps video duration = wall-clock duration with no fast-forward.
        """
        interval   = 1.0 / self.fps
        prev_frame = None   # last decoded BGR frame — used for freeze

        while self._running:
            t0 = time.monotonic()

            # Grab and clear the latest JPEG
            with self._latest_lock:
                jpeg, self._latest = self._latest, None

            # Decode if we have a new frame
            if jpeg is not None:
                arr = np.frombuffer(jpeg, np.uint8)
                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if bgr is not None:
                    if bgr.shape[1] != self.width or bgr.shape[0] != self.height:
                        bgr = cv2.resize(bgr, (self.width, self.height))
                    prev_frame = bgr

            # Write to disk — repeat last frame if nothing new yet
            if prev_frame is not None:
                with self._lock:
                    if self._writer and self._writer.isOpened():
                        self._writer.write(prev_frame)
                        self._nframes += 1

            # Sleep precisely for remainder of the tick
            elapsed = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0.001:
                time.sleep(remaining)

    @property
    def status(self):
        with self._lock:
            return {
                "recording":  self._running,
                "filename":   os.path.basename(self._filename) if self._filename else None,
                "duration_s": round(time.time() - self._start_ts, 1) if self._start_ts and self._running else None,
                "frames":     self._nframes,
            }


recorder = VideoRecorder(fps=20, width=640, height=480)  # MJPG .avi, near-lossless
recorder.start()
log.info("Auto-recording started → %s", RECORDINGS_DIR)


# =============================================================================
# Camera MJPEG generator
# =============================================================================

def _cam_generator():
    hdr  = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    enc  = [cv2.IMWRITE_JPEG_QUALITY, 97]   # max quality stream
    last = None

    while True:
        with _ann_lock:
            frame = _ann_jpeg

        if frame is None:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank, "Waiting for Pi...", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 80, 40), 2)
            _, buf = cv2.imencode(".jpg", blank, enc)
            frame  = buf.tobytes()

        if frame is not last:
            last = frame
            recorder.write(frame)
            yield hdr + frame + b"\r\n"
        else:
            time.sleep(0.003)


# =============================================================================
# Flask routes
# =============================================================================

@app.route("/stream")
def stream():
    return Response(_cam_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/detections")
def detections():
    with _det_lock:
        return jsonify(list(_detections))


@app.route("/gas")
def gas():
    with _gas_lock:
        return jsonify(dict(_gas_data))


# ── AI toggle ─────────────────────────────────────────────────────────────────
@app.route("/ai/toggle", methods=["POST"])
def ai_toggle():
    global _ai_enabled
    _ai_enabled = not _ai_enabled
    log.info("AI: %s", "ON" if _ai_enabled else "OFF")
    return jsonify({"ai_enabled": _ai_enabled})

@app.route("/ai/status")
def ai_status():
    return jsonify({"ai_enabled": _ai_enabled})


# ── Thermal toggle + opacity ───────────────────────────────────────────────────
@app.route("/thermal/toggle", methods=["POST"])
def thermal_toggle():
    global _thermal_enabled
    _thermal_enabled = not _thermal_enabled
    log.info("Thermal blend: %s", "ON" if _thermal_enabled else "OFF")
    return jsonify({"thermal_enabled": _thermal_enabled,
                    "thermal_alpha":   _thermal_alpha})

@app.route("/thermal/opacity", methods=["POST"])
def thermal_opacity():
    global _thermal_alpha
    data  = request.get_json(silent=True) or {}
    alpha = float(data.get("alpha", _thermal_alpha))
    _thermal_alpha = max(0.0, min(1.0, alpha))
    log.info("Thermal alpha: %.2f", _thermal_alpha)
    return jsonify({"thermal_alpha": _thermal_alpha})

@app.route("/thermal/status")
def thermal_status():
    return jsonify({
        "thermal_enabled": _thermal_enabled,
        "thermal_alpha":   _thermal_alpha,
        "thermal_online":  _therm_bgr is not None,
    })


# ── Recording ─────────────────────────────────────────────────────────────────
@app.route("/recording/status")
def rec_status():
    return jsonify(recorder.status)

@app.route("/recording/start", methods=["POST"])
def rec_start():
    ok = recorder.start()
    return jsonify({"ok": ok, **recorder.status})

@app.route("/recording/stop", methods=["POST"])
def rec_stop():
    recorder.stop()
    return jsonify({"ok": True, **recorder.status})


# ── Motor proxy ───────────────────────────────────────────────────────────────
MOTOR_DIRS = {"forward", "backward", "left", "right", "stop"}

@app.route("/move/<direction>", methods=["POST"])
def proxy_motor(direction):
    if direction not in MOTOR_DIRS:
        return jsonify({"error": "unknown direction"}), 400
    try:
        r = requests.post(f"{PI_BASE}/move/{direction}", timeout=2)
        return jsonify(r.json()), r.status_code
    except requests.ConnectionError:
        return jsonify({"error": "Pi not reachable"}), 503


# ── Defects ───────────────────────────────────────────────────────────────────
@app.route("/defects")
def defects():
    """Latest NDT crack detection report."""
    with _defect_lock:
        return jsonify(dict(_latest_defect))


@app.route("/crack/toggle", methods=["POST"])
def crack_toggle():
    """Toggle the OpenCV crack detection pipeline on/off."""
    global _crack_enabled
    _crack_enabled = not _crack_enabled
    detector.set_crack_enabled(_crack_enabled)
    log.info("Crack pipeline: %s", "ON" if _crack_enabled else "OFF")
    return jsonify({"crack_enabled": _crack_enabled})


@app.route("/crack/calibrate", methods=["POST"])
def crack_calibrate():
    """
    Update pipe diameter for scale mapping.
    Body: {"pipe_diameter_mm": 100.0}
    """
    data = request.get_json(silent=True) or {}
    mm   = float(data.get("pipe_diameter_mm", 100.0))
    mm   = max(10.0, min(2000.0, mm))
    detector.set_pipe_diameter(mm)
    return jsonify({"pipe_diameter_mm": mm})


# ── Health ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    with _gas_lock:
        g = dict(_gas_data)
    with _defect_lock:
        defect_summary = {
            "worst_severity":  _latest_defect["worst_severity"],
            "crack_count":     _latest_defect["crack_count"],
            "critical_count":  _latest_defect["critical_count"],
            "max_width_mm":    _latest_defect["max_width_mm"],
            "max_length_mm":   _latest_defect["max_length_mm"],
        }
    return jsonify({
        "status":           "ok",
        "pi_connected":     _pi_connected,
        "ai_enabled":       _ai_enabled,
        "thermal_enabled":  _thermal_enabled,
        "thermal_online":   _therm_bgr is not None,
        "thermal_alpha":    _thermal_alpha,
        "crack_enabled":    _crack_enabled,
        "gas":              g,
        "recording":        recorder.status,
        "defect":           defect_summary,
    })


if __name__ == "__main__":
    log.info("=== VIPER AI Server — port 8000 ===")
    log.info("Pi: %s", PI_BASE)
    log.info("Recordings: %s", RECORDINGS_DIR)
    app.run(host="0.0.0.0", port=8000, threaded=True, debug=False)
