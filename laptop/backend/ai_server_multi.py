# =============================================================================
# laptop/backend/ai_server_multi.py  v2  —  model switcher (crack + multi)
# =============================================================================
#
# USE THIS FILE when you need to switch between:
#   - viper_pipe_v1   (crack-only,  mAP50=0.653)  → key: "crack"
#   - viper_multi_v12 (7 defects,   mAP50=0.808)  → key: "multi"
#
# USE ai_server.py when you ONLY need crack detection (faster startup).
#
# HOW TO RUN:
#   python ai_server_multi.py
#
# SWITCH MODEL AT RUNTIME (no restart):
#   POST /model/switch   {"model": "crack"}   or   {"model": "multi"}
#   GET  /model/status   → shows active model, classes, mAP50
#
# DEFAULT MODEL: viper_multi_v12  (7 classes, best accuracy)
# Override with env var:
#   $env:VIPER_MODEL="crack"   → start with crack-only model
#   $env:VIPER_MODEL="multi"   → start with multi model (default)
#
# ALL ENDPOINTS (same as ai_server.py plus /model/switch + /model/status):
#   GET  /stream                  MJPEG stream
#   GET  /detections              detections JSON (with distance_m, gas, thermal)
#   GET  /gas                     MQ4 gas JSON
#   GET  /health                  full system status + active model info
#   POST /ai/toggle               toggle AI on/off
#   GET  /ai/status
#   POST /thermal/toggle
#   POST /thermal/opacity
#   GET  /thermal/status
#   POST /model/switch            {"model": "crack"} or {"model": "multi"}
#   GET  /model/status            active model + available models
#   GET  /distance                {"distance_m", "speed_kmh", "moving"}
#   POST /distance/reset          reset odometer to 0
#   POST /move/<dir>              motor proxy (updates distance tracker)
#   GET  /recording/status
#   POST /recording/start
#   POST /recording/stop
#   GET  /defects
#   POST /crack/toggle
#   POST /crack/calibrate
# =============================================================================

import cv2, logging, numpy as np, os, queue, threading, time
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from detector.model import YOLODetector

# ── Firebase ──────────────────────────────────────────────────────────────────
_RTDB_URL         = os.environ.get("FIREBASE_RTDB_URL",
                                   "https://viper-ndt-default-rtdb.firebaseio.com")
_firestore_client = None
_rtdb_events_ref  = None

try:
    import firebase_admin
    from firebase_admin import credentials, firestore as _fs, db as _frtdb
    _sa_path = os.environ.get("FIREBASE_SA_KEY",
        str(Path(__file__).parent / "serviceAccountKey.json"))
    if Path(_sa_path).exists():
        _cred = credentials.Certificate(_sa_path)
        firebase_admin.initialize_app(_cred, {"databaseURL": _RTDB_URL})
        _firestore_client = _fs.client()
        _rtdb_events_ref  = _frtdb.reference("detectionEvents")
        logging.getLogger(__name__).info("Firebase connected")
    else:
        logging.getLogger(__name__).warning("Firebase disabled — key not found at %s.", _sa_path)
except ImportError:
    logging.getLogger(__name__).warning("firebase-admin not installed")

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [LAPTOP] %(levelname)s %(message)s", datefmt="%H:%M:%S")
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

# ── Model registry ─────────────────────────────────────────────────────────────
_BASE = Path(__file__).parent / "runs" / "detect"

MODELS = {
    "crack": {
        "path":    str(_BASE / "viper_pipe_v1"   / "weights" / "best.pt"),
        "mAP50":   0.653,
        "desc":    "Crack-only specialist",
        "classes": {0: "Crack"},
    },
    "multi": {
        "path":    str(_BASE / "viper_multi_v12" / "weights" / "best.pt"),
        "mAP50":   0.808,
        "desc":    "7-class full defect detector",
        "classes": {
            0: "Buckling",
            1: "Crack",
            2: "Debris",
            3: "Hole",
            4: "Joint Offset",
            5: "Obstacle",
            6: "Utility Intrusion",
        },
    },
}

def _class_map(key: str) -> dict:
    return MODELS[key]["classes"]

# =============================================================================
# Crack Severity Scoring  (same as ai_server.py)
# =============================================================================
# Estimates severity from bbox area relative to frame (640×480 = 307200 px²)
#   MINOR    : < 1% of frame  (<3072 px²)   — hairline crack
#   MODERATE : 1–4% of frame  (3072–12288)  — medium structural crack
#   CRITICAL : > 4% of frame  (>12288 px²)  — large / severe crack

FRAME_AREA = 640 * 480

def _severity(bbox) -> str:
    if not bbox or len(bbox) < 4:
        return "MINOR"
    try:
        x1, y1, x2, y2 = bbox
        area = abs((x2 - x1) * (y2 - y1))
        pct  = area / FRAME_AREA
        if pct > 0.04: return "CRITICAL"
        if pct > 0.01: return "MODERATE"
        return "MINOR"
    except Exception:
        return "MINOR"

# ── Settings ──────────────────────────────────────────────────────────────────
_CONFIDENCE    = float(os.environ.get("VIPER_CONFIDENCE", "0.10"))
_crack_enabled = False

# Starting model — env var VIPER_MODEL or default "multi"
_start_key = os.environ.get("VIPER_MODEL", "multi").lower()
if _start_key not in MODELS:
    log.warning("Unknown VIPER_MODEL=%s — defaulting to multi", _start_key)
    _start_key = "multi"

# ── Load initial model ────────────────────────────────────────────────────────
def _load_model(key: str) -> YOLODetector:
    """Load a model by key, patch class names, warmup."""
    cfg  = MODELS[key]
    path = cfg["path"]

    if not Path(path).exists():
        raise FileNotFoundError(f"Model not found: {path}")

    log.info("Loading model [%s]: %s", key, path)
    det = YOLODetector(model_path=path, confidence=_CONFIDENCE,
                       crack_enabled=_crack_enabled)
    for cid, cname in cfg["classes"].items():
        if cid in det.class_names:
            det.class_names[cid] = cname
    det.warmup()
    log.info("Model [%s] ready — classes: %s", key, dict(det.class_names))
    return det


log.info("=" * 60)
log.info("  ai_server_multi.py — model switcher mode")
log.info("  Available: crack (mAP50=0.653) | multi (mAP50=0.808)")
log.info("  Starting with: %s", _start_key)
log.info("  Confidence: %.2f", _CONFIDENCE)
log.info("=" * 60)

_active_key = _start_key
detector    = _load_model(_active_key)

log.info("=" * 60)
log.info("  ACTIVE MODEL : %s  (%s)", _active_key, MODELS[_active_key]["desc"])
log.info("  mAP50        : %.3f", MODELS[_active_key]["mAP50"])
log.info("  CLASSES      : %s", dict(detector.class_names))
log.info("=" * 60)

# =============================================================================
# Distance + Speed Tracker
# =============================================================================
ROVER_MAX_SPEED_MS  = 0.25
ROVER_DEFAULT_SPEED = 50

class DistanceTracker:
    def __init__(self, max_speed_ms=ROVER_MAX_SPEED_MS):
        self._max_speed = max_speed_ms
        self._lock      = threading.Lock()
        self._distance  = 0.0
        self._moving    = False
        self._speed_pct = ROVER_DEFAULT_SPEED
        self._last_t    = None

    def update(self, direction, speed_pct=ROVER_DEFAULT_SPEED):
        now = time.monotonic()
        with self._lock:
            self._flush(now)
            # Both forward AND backward accumulate distance
            self._moving    = direction in ("forward", "backward")
            self._speed_pct = speed_pct
            self._last_t    = now

    def _flush(self, now):
        if self._moving and self._last_t is not None:
            elapsed         = now - self._last_t
            velocity        = (self._speed_pct / 100.0) * self._max_speed
            self._distance += velocity * elapsed
        self._last_t = now

    def get(self):
        now = time.monotonic()
        with self._lock:
            if self._moving and self._last_t is not None:
                elapsed  = now - self._last_t
                velocity = (self._speed_pct / 100.0) * self._max_speed
                live_d   = self._distance + velocity * elapsed
            else:
                live_d   = self._distance
            velocity_ms = (self._speed_pct / 100.0) * self._max_speed if self._moving else 0.0
            return {
                "distance_m": round(live_d, 3),
                "speed_pct":  self._speed_pct,
                "speed_kmh":  round(velocity_ms * 3.6, 3),
                "moving":     self._moving,
            }

    def reset(self):
        now = time.monotonic()
        with self._lock:
            self._distance = 0.0
            self._last_t   = now if self._moving else None
        log.info("Odometer reset to 0.0 m")


distance_tracker = DistanceTracker()

# ── Shared state ──────────────────────────────────────────────────────────────
_raw_lock   = threading.Lock()
_ann_lock   = threading.Lock()
_therm_lock = threading.Lock()
_det_lock   = threading.Lock()
_gas_lock   = threading.Lock()
_model_lock = threading.Lock()   # protects detector hot-swap

_raw_jpeg   = None
_ann_jpeg   = None
_therm_bgr  = None
_detections = []
_gas_data   = {"available":False,"ppm":None,"level":"OFFLINE",
               "voltage":None,"gas":"CH4 / Methane","sensor":"MQ4"}
_ai_enabled      = True
_thermal_enabled = False
_thermal_alpha   = 0.45
_pi_connected    = False

_defect_lock   = threading.Lock()
_latest_defect = {"timestamp":None,"crack_count":0,"critical_count":0,
                  "worst_severity":"NONE","max_width_mm":0.0,"max_length_mm":0.0}

_pi_health_lock = threading.Lock()
_pi_health_data = {
    "pi_temp":None,"pi_temp_status":"ok",
    "thermal_avg_c":None,"thermal_min_c":None,"thermal_max_c":None,
    "ping_ms":None,"pi_camera_open":None,
    "pi_thermal_sensor":None,"pi_gas_sensor":None,
}

# ── CLAHE ─────────────────────────────────────────────────────────────────────
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

def _clahe_enhance(bgr):
    lab     = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    enhanced= cv2.merge([_clahe.apply(l), a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

# ── YOLO queues ───────────────────────────────────────────────────────────────
_yolo_in_q:  queue.Queue = queue.Queue(maxsize=1)
_yolo_out_q: queue.Queue = queue.Queue(maxsize=1)


def _yolo_thread():
    log.info("YOLO thread started [%s]", _active_key)
    while True:
        try:
            frame = _yolo_in_q.get(timeout=1.0)

            with _model_lock:
                annotated, dets = detector.detect(frame)
                current_key     = _active_key

            # Attach telemetry to every detection
            snap = distance_tracker.get()
            with _gas_lock:
                gas_snap = dict(_gas_data)
            with _pi_health_lock:
                therm_c = _pi_health_data.get("thermal_avg_c")

            class_map = _class_map(current_key)
            for d in dets:
                raw = d.get("label", "")
                if raw in ("item", "0", "", "class_0"):
                    d["label"] = class_map.get(d.get("cls_id", 0), "Defect")
                d["distance_m"]    = snap["distance_m"]
                d["gas_ppm"]       = gas_snap.get("ppm")
                d["gas_level"]     = gas_snap.get("level", "OFFLINE")
                d["thermal_avg_c"] = therm_c
                d["severity"]      = _severity(d.get("bbox"))

            try:
                _yolo_out_q.get_nowait()
            except queue.Empty:
                pass
            _yolo_out_q.put((annotated, dets))

        except queue.Empty:
            continue
        except Exception:
            import traceback as _tb
            log.error("YOLO crash:\n%s", _tb.format_exc())

# ── Firebase queues ───────────────────────────────────────────────────────────
_fs_queue:   queue.Queue = queue.Queue(maxsize=500)
_rtdb_queue: queue.Queue = queue.Queue(maxsize=200)

# =============================================================================
# MJPEG parser
# =============================================================================

def _iter_mjpeg(resp):
    buf = b""
    for chunk in resp.iter_content(chunk_size=16384):
        buf += chunk
        while True:
            s = buf.find(b"\xff\xd8")
            e = buf.find(b"\xff\xd9", s + 2) if s != -1 else -1
            if s == -1 or e == -1: break
            yield buf[s: e + 2]
            buf = buf[e + 2:]

# =============================================================================
# Threads
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
            log.error("Raw reader: %s", exc)
        time.sleep(3)

def _blend_thermal(camera_bgr):
    with _therm_lock:
        therm = _therm_bgr
    if therm is None: return camera_bgr
    gray = cv2.cvtColor(therm, cv2.COLOR_BGR2GRAY)
    gray = _clahe.apply(gray)
    th, tw = camera_bgr.shape[:2]
    if gray.shape != (th, tw):
        gray = cv2.resize(gray, (tw, th), interpolation=cv2.INTER_CUBIC)
    heatmap = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
    return cv2.addWeighted(camera_bgr, 1.0 - _thermal_alpha,
                           heatmap, _thermal_alpha, 0)


def _infer_worker():
    global _ann_jpeg, _detections
    enc      = [cv2.IMWRITE_JPEG_QUALITY, 85]
    last_raw = None
    log.info("Inference worker started")

    while True:
        with _raw_lock:
            raw = _raw_jpeg
        if raw is None or raw is last_raw:
            time.sleep(0.005)
            continue
        last_raw = raw

        arr   = np.frombuffer(raw, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None: continue

        try:
            enhanced = _clahe_enhance(frame)
            if _ai_enabled:
                try: _yolo_in_q.put_nowait(enhanced)
                except queue.Full: pass
                try:
                    annotated, dets = _yolo_out_q.get_nowait()
                    with _det_lock: _detections = dets
                    out = _blend_thermal(annotated) if _thermal_enabled else annotated
                    ok, buf = cv2.imencode(".jpg", out, enc)
                    if ok:
                        with _ann_lock: _ann_jpeg = buf.tobytes()
                except queue.Empty:
                    out = _blend_thermal(enhanced) if _thermal_enabled else enhanced
                    ok, buf = cv2.imencode(".jpg", out, enc)
                    if ok:
                        with _ann_lock: _ann_jpeg = buf.tobytes()
            else:
                out = _blend_thermal(enhanced) if _thermal_enabled else enhanced
                ok, buf = cv2.imencode(".jpg", out, enc)
                if ok:
                    with _ann_lock: _ann_jpeg = buf.tobytes()
                with _det_lock: _detections = []
        except Exception:
            import traceback as _tb
            log.error("Worker crash:\n%s", _tb.format_exc())


def _thermal_reader():
    global _therm_bgr
    while True:
        try:
            r = requests.get(f"{PI_BASE}/thermal_feed", stream=True, timeout=15)
            r.raise_for_status()
            log.info("Pi thermal connected")
            for jpg in _iter_mjpeg(r):
                arr = np.frombuffer(jpg, np.uint8)
                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if bgr is not None:
                    with _therm_lock: _therm_bgr = bgr
        except requests.ConnectionError:
            log.warning("Pi thermal offline — retry in 5s")
        except Exception as exc:
            log.error("Thermal reader: %s", exc)
        time.sleep(5)


def _gas_poller():
    global _gas_data
    while True:
        try:
            r = requests.get(f"{PI_BASE}/gas", timeout=2)
            if r.status_code == 200:
                with _gas_lock: _gas_data = r.json()
        except Exception: pass
        time.sleep(0.5)


def _pi_health_poller():
    global _pi_health_data
    while True:
        try:
            t0      = time.monotonic()
            r       = requests.get(f"{PI_BASE}/health", timeout=3)
            ping_ms = round((time.monotonic() - t0) * 1000, 1)
            if r.status_code == 200:
                d = r.json()
                with _pi_health_lock:
                    _pi_health_data = {
                        "pi_temp":           d.get("pi_temp"),
                        "pi_temp_status":    d.get("pi_temp_status", "ok"),
                        "thermal_avg_c":     d.get("thermal_avg_c"),
                        "thermal_min_c":     d.get("thermal_min_c"),
                        "thermal_max_c":     d.get("thermal_max_c"),
                        "ping_ms":           ping_ms,
                        "pi_camera_open":    d.get("camera_open"),
                        "pi_thermal_sensor": d.get("thermal_sensor"),
                        "pi_gas_sensor":     d.get("gas_sensor"),
                    }
        except Exception:
            with _pi_health_lock: _pi_health_data["ping_ms"] = None
        time.sleep(2)


def _firestore_writer():
    if _firestore_client is None: return
    col = _firestore_client.collection("mission_logs")
    while True:
        try: col.add(_fs_queue.get(timeout=1.0))
        except queue.Empty: continue
        except Exception as exc: log.warning("Firestore write failed: %s", exc)


def _rtdb_writer():
    if _rtdb_events_ref is None: return
    while True:
        try: _rtdb_events_ref.push(_rtdb_queue.get(timeout=1.0))
        except queue.Empty: continue
        except Exception as exc: log.warning("RTDB write failed: %s", exc)


threading.Thread(target=_raw_reader,       daemon=True, name="raw-reader").start()
threading.Thread(target=_yolo_thread,      daemon=True, name="yolo-thread").start()
threading.Thread(target=_infer_worker,     daemon=True, name="infer-worker").start()
threading.Thread(target=_thermal_reader,   daemon=True, name="thermal-reader").start()
threading.Thread(target=_gas_poller,       daemon=True, name="gas-poller").start()
threading.Thread(target=_pi_health_poller, daemon=True, name="pi-health-poller").start()
threading.Thread(target=_firestore_writer, daemon=True, name="fs-writer").start()
if _rtdb_events_ref is not None:
    threading.Thread(target=_rtdb_writer, daemon=True, name="rtdb-writer").start()

# =============================================================================
# VideoRecorder
# =============================================================================

class VideoRecorder:
    def __init__(self, fps=20, width=640, height=480):
        self.fps=fps; self.width=width; self.height=height
        self._writer=None; self._filename=None; self._running=False
        self._lock=threading.Lock(); self._latest=None
        self._latest_lock=threading.Lock(); self._thread=None
        self._start_ts=None; self._nframes=0

    def start(self):
        with self._lock:
            if self._running: return False
            ts=datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self._filename=str(RECORDINGS_DIR/f"{ts}.avi")
            fourcc=cv2.VideoWriter_fourcc(*"MJPG")
            self._writer=cv2.VideoWriter(self._filename,fourcc,self.fps,(self.width,self.height))
            if not self._writer.isOpened():
                self._filename=str(RECORDINGS_DIR/f"{ts}.mp4")
                self._writer=cv2.VideoWriter(self._filename,cv2.VideoWriter_fourcc(*"mp4v"),self.fps,(self.width,self.height))
            if not self._writer.isOpened():
                log.error("VideoWriter failed: %s",self._filename); return False
            self._running=True; self._start_ts=time.time(); self._nframes=0; self._latest=None
        self._thread=threading.Thread(target=self._loop,daemon=True); self._thread.start()
        log.info("Recording: %s",self._filename); return True

    def stop(self):
        with self._lock:
            if not self._running: return
            self._running=False
        if self._thread: self._thread.join(timeout=5)
        with self._lock:
            if self._writer: self._writer.release(); self._writer=None

    def write(self,jpeg_bytes):
        if not self._running: return
        with self._latest_lock: self._latest=jpeg_bytes

    def _loop(self):
        interval=1.0/self.fps; prev_frame=None
        while self._running:
            t0=time.monotonic()
            with self._latest_lock:
                jpeg,self._latest=self._latest,None
            if jpeg is not None:
                arr=np.frombuffer(jpeg,np.uint8)
                bgr=cv2.imdecode(arr,cv2.IMREAD_COLOR)
                if bgr is not None:
                    if bgr.shape[1]!=self.width or bgr.shape[0]!=self.height:
                        bgr=cv2.resize(bgr,(self.width,self.height))
                    prev_frame=bgr
            if prev_frame is not None:
                with self._lock:
                    if self._writer and self._writer.isOpened():
                        self._writer.write(prev_frame); self._nframes+=1
            remaining=interval-(time.monotonic()-t0)
            if remaining>0.001: time.sleep(remaining)

    @property
    def status(self):
        with self._lock:
            return {"recording":self._running,
                    "filename":os.path.basename(self._filename) if self._filename else None,
                    "duration_s":round(time.time()-self._start_ts,1) if self._start_ts and self._running else None,
                    "frames":self._nframes}


recorder = VideoRecorder()
log.info("Recorder ready → %s", RECORDINGS_DIR)

# =============================================================================
# Stream generator
# =============================================================================

def _cam_generator():
    hdr=b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    enc=[cv2.IMWRITE_JPEG_QUALITY,85]; last=None
    while True:
        with _ann_lock: frame=_ann_jpeg
        if frame is None:
            with _raw_lock: frame=_raw_jpeg
        if frame is None:
            blank=np.zeros((480,640,3),dtype=np.uint8)
            cv2.putText(blank,"Waiting for Pi...",(150,240),cv2.FONT_HERSHEY_SIMPLEX,1.0,(40,80,40),2)
            _,buf=cv2.imencode(".jpg",blank,enc); frame=buf.tobytes()
        if frame is not last:
            last = frame
            if recorder._running:
                with _raw_lock:
                    if _raw_jpeg is not None: recorder.write(frame)
            yield hdr+frame+b"\r\n"
        else:
            time.sleep(0.010)

# =============================================================================
# Flask routes
# =============================================================================

@app.route("/stream")
def stream():
    return Response(_cam_generator(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/detections")
def detections():
    with _det_lock: return jsonify(list(_detections))

@app.route("/gas")
def gas():
    with _gas_lock: return jsonify(dict(_gas_data))

# ── AI toggle ──────────────────────────────────────────────────────────────────
@app.route("/ai/toggle", methods=["POST"])
def ai_toggle():
    global _ai_enabled
    _ai_enabled = not _ai_enabled
    log.info("AI: %s", "ON" if _ai_enabled else "OFF")
    return jsonify({"ai_enabled": _ai_enabled})

@app.route("/ai/status")
def ai_status():
    return jsonify({"ai_enabled": _ai_enabled})

# ── Model switcher ─────────────────────────────────────────────────────────────
@app.route("/model/switch", methods=["POST"])
def model_switch():
    """
    Switch between crack-only and multi-defect model at runtime.
    Body: {"model": "crack"} or {"model": "multi"}
    No restart needed — takes effect on the next frame.
    """
    global detector, _active_key, _crack_enabled

    data = request.get_json(silent=True) or {}
    key  = data.get("model", "").lower()

    if key not in MODELS:
        return jsonify({
            "error":     "Invalid model. Use 'crack' or 'multi'",
            "available": list(MODELS.keys()),
        }), 400

    if key == _active_key:
        return jsonify({
            "ok":         True,
            "model":      key,
            "note":       "Already active — no change",
            "model_file": Path(MODELS[key]["path"]).parent.parent.name,
            "classes":    dict(detector.class_names),
        })

    path = MODELS[key]["path"]
    if not Path(path).exists():
        return jsonify({"error": f"Model file not found: {path}"}), 404

    log.info("Switching model: %s → %s", _active_key, key)

    with _model_lock:
        _active_key = key
        detector    = _load_model(key)
        detector.set_crack_enabled(_crack_enabled)

    log.info("Model switched → [%s]  classes: %s", key, dict(detector.class_names))

    return jsonify({
        "ok":         True,
        "model":      key,
        "model_file": Path(MODELS[key]["path"]).parent.parent.name,
        "mAP50":      MODELS[key]["mAP50"],
        "desc":       MODELS[key]["desc"],
        "classes":    dict(detector.class_names),
        "confidence": _CONFIDENCE,
    })


@app.route("/model/status")
def model_status():
    return jsonify({
        "active_model": _active_key,
        "model_file":   Path(MODELS[_active_key]["path"]).parent.parent.name,
        "mAP50":        MODELS[_active_key]["mAP50"],
        "desc":         MODELS[_active_key]["desc"],
        "confidence":   _CONFIDENCE,
        "classes":      dict(detector.class_names),
        "available": {
            k: {
                "exists":  Path(v["path"]).exists(),
                "mAP50":   v["mAP50"],
                "desc":    v["desc"],
                "classes": v["classes"],
            }
            for k, v in MODELS.items()
        },
    })

# ── Distance ───────────────────────────────────────────────────────────────────
@app.route("/distance")
def get_distance():
    return jsonify(distance_tracker.get())

@app.route("/distance/reset", methods=["POST"])
def reset_distance():
    distance_tracker.reset()
    return jsonify({"ok": True, "distance_m": 0.0})

# ── Thermal ────────────────────────────────────────────────────────────────────
@app.route("/thermal/toggle", methods=["POST"])
def thermal_toggle():
    global _thermal_enabled
    _thermal_enabled = not _thermal_enabled
    log.info("Thermal blend: %s", "ON" if _thermal_enabled else "OFF")
    return jsonify({"thermal_enabled": _thermal_enabled, "thermal_alpha": _thermal_alpha})

@app.route("/thermal/opacity", methods=["POST"])
def thermal_opacity():
    global _thermal_alpha
    data           = request.get_json(silent=True) or {}
    _thermal_alpha = max(0.0, min(1.0, float(data.get("alpha", _thermal_alpha))))
    return jsonify({"thermal_alpha": _thermal_alpha})

@app.route("/thermal/status")
def thermal_status():
    with _therm_lock: online = _therm_bgr is not None
    return jsonify({"thermal_enabled": _thermal_enabled,
                    "thermal_alpha":   _thermal_alpha,
                    "thermal_online":  online})

# ── Recording ──────────────────────────────────────────────────────────────────
@app.route("/recording/status")
def rec_status():   return jsonify(recorder.status)

@app.route("/recording/start", methods=["POST"])
def rec_start():    return jsonify({"ok": recorder.start(), **recorder.status})

@app.route("/recording/stop", methods=["POST"])
def rec_stop():
    recorder.stop()
    return jsonify({"ok": True, **recorder.status})

# ── Motor proxy ────────────────────────────────────────────────────────────────
MOTOR_DIRS = {"forward", "backward", "left", "right", "stop"}

@app.route("/move/<direction>", methods=["POST"])
def proxy_motor(direction):
    if direction not in MOTOR_DIRS:
        return jsonify({"error": "unknown direction"}), 400
    distance_tracker.update(direction)
    try:
        r = requests.post(f"{PI_BASE}/move/{direction}", timeout=2)
        return jsonify(r.json()), r.status_code
    except requests.ConnectionError:
        return jsonify({"error": "Pi not reachable"}), 503

# ── Defects ────────────────────────────────────────────────────────────────────
@app.route("/defects")
def defects():
    with _defect_lock: return jsonify(dict(_latest_defect))

@app.route("/crack/toggle", methods=["POST"])
def crack_toggle():
    global _crack_enabled
    _crack_enabled = not _crack_enabled
    detector.set_crack_enabled(_crack_enabled)
    log.info("Crack pipeline: %s", "ON" if _crack_enabled else "OFF")
    return jsonify({"crack_enabled": _crack_enabled})

@app.route("/crack/calibrate", methods=["POST"])
def crack_calibrate():
    data = request.get_json(silent=True) or {}
    mm   = max(10.0, min(2000.0, float(data.get("pipe_diameter_mm", 100.0))))
    detector.set_pipe_diameter(mm)
    return jsonify({"pipe_diameter_mm": mm})

# ── Health ─────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    with _gas_lock:        g    = dict(_gas_data)
    with _pi_health_lock:  pi_h = dict(_pi_health_data)
    with _therm_lock:      thermal_online = _therm_bgr is not None
    dist = distance_tracker.get()
    return jsonify({
        "status":            "ok",
        "pi_connected":      _pi_connected,
        "ai_enabled":        _ai_enabled,
        "active_model":      _active_key,
        "model_file":        Path(MODELS[_active_key]["path"]).parent.parent.name,
        "model_desc":        MODELS[_active_key]["desc"],
        "mAP50":             MODELS[_active_key]["mAP50"],
        "confidence":        _CONFIDENCE,
        "thermal_enabled":   _thermal_enabled,
        "thermal_online":    thermal_online,
        "thermal_alpha":     _thermal_alpha,
        "crack_enabled":     _crack_enabled,
        "distance_m":        dist["distance_m"],
        "speed_kmh":         dist["speed_kmh"],
        "gas":               g,
        "recording":         recorder.status,
        "defect": {
            "worst_severity": _latest_defect["worst_severity"],
            "crack_count":    _latest_defect["crack_count"],
            "critical_count": _latest_defect["critical_count"],
            "max_width_mm":   _latest_defect["max_width_mm"],
            "max_length_mm":  _latest_defect["max_length_mm"],
        },
        "pi_temp":           pi_h.get("pi_temp"),
        "pi_temp_status":    pi_h.get("pi_temp_status", "ok"),
        "thermal_avg_c":     pi_h.get("thermal_avg_c"),
        "thermal_min_c":     pi_h.get("thermal_min_c"),
        "thermal_max_c":     pi_h.get("thermal_max_c"),
        "ping_ms":           pi_h.get("ping_ms"),
        "pi_camera_open":    pi_h.get("pi_camera_open"),
        "pi_thermal_sensor": pi_h.get("pi_thermal_sensor"),
        "pi_gas_sensor":     pi_h.get("pi_gas_sensor"),
    })


if __name__ == "__main__":
    log.info("=== VIPER AI Server (multi) v2 — port 8000 ===")
    log.info("Pi: %s", PI_BASE)
    log.info("Active model: [%s]  %s", _active_key, MODELS[_active_key]["desc"])
    log.info("Switch model: POST /model/switch  {\"model\": \"crack\"} or {\"model\": \"multi\"}")
    log.info("Recording:   POST /recording/start  |  POST /recording/stop")
    log.info("Recordings → %s", RECORDINGS_DIR)
    app.run(host="0.0.0.0", port=8000, threaded=True, debug=False)