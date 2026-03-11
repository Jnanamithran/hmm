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

import cv2, json, logging, numpy as np, os, queue, threading, time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from detector.model import YOLODetector

# ── Firebase Admin SDK (Firestore backend push) ───────────────────────────────
# ── Firebase Admin SDK (Firestore + RTDB backend push) ───────────────────────
# Install:  pip install firebase-admin
# Provide service account key via env var FIREBASE_SA_KEY (path to JSON)
# or place serviceAccountKey.json beside ai_server.py.
# Both Firestore (mission_logs) and RTDB (detectionEvents) are disabled
# gracefully if the key is absent or firebase-admin is not installed.
#
# RTDB writes bypass Firebase security rules (admin privilege) so the
# "auth != null" guard on detectionEvents does not apply to this path.
# The RTDB URL is read from FIREBASE_RTDB_URL env var or hardcoded below.
_RTDB_URL        = os.environ.get(
    "FIREBASE_RTDB_URL", "https://viper-ndt-default-rtdb.firebaseio.com"
)
_firestore_client  = None
_rtdb_events_ref   = None    # firebase_admin.db reference → /detectionEvents

try:
    import firebase_admin
    from firebase_admin import credentials, firestore as _fs, db as _frtdb

    _sa_path = os.environ.get(
        "FIREBASE_SA_KEY",
        str(Path(__file__).parent / "serviceAccountKey.json"),
    )
    if Path(_sa_path).exists():
        _cred = credentials.Certificate(_sa_path)
        firebase_admin.initialize_app(_cred, {"databaseURL": _RTDB_URL})

        # Firestore — for mission_logs (existing)
        _firestore_client = _fs.client()

        # RTDB — for detectionEvents (critical alerts visible in DetectionLog.jsx)
        _rtdb_events_ref = _frtdb.reference("detectionEvents")

        logging.getLogger(__name__).info(
            "Firebase connected — Firestore mission_logs + RTDB detectionEvents ready"
        )
    else:
        logging.getLogger(__name__).warning(
            "Firebase disabled — no service account key found at %s. "
            "Set FIREBASE_SA_KEY env var or place serviceAccountKey.json "
            "next to ai_server.py.",
            _sa_path,
        )
except ImportError:
    logging.getLogger(__name__).warning(
        "firebase-admin not installed — Firestore + RTDB push disabled. "
        "Run: pip install firebase-admin"
    )

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
_crack_enabled     = False   # crack pipeline OFF — using YOLOv8n only
_defect_lock       = threading.Lock()
_pi_health_lock    = threading.Lock()
_pi_health_data    = {       # Pi system vitals — polled every 2 s
    "pi_temp":          None,   # CPU °C
    "pi_temp_status":   "ok",   # "ok" | "warning" | "critical"
    "thermal_avg_c":    None,   # MLX90640 scene avg °C
    "thermal_min_c":    None,
    "thermal_max_c":    None,
    "ping_ms":          None,   # round-trip to Pi /health (ms)
    "pi_camera_open":   None,
    "pi_thermal_sensor":None,
    "pi_gas_sensor":    None,
}
# _latest_defect: crack pipeline is OFF — always returns safe defaults.
# Re-enable by setting _crack_enabled = True and restarting.
_latest_defect = {
    "timestamp":      None,
    "crack_count":    0,
    "critical_count": 0,
    "worst_severity": "NONE",
    "max_width_mm":   0.0,
    "max_length_mm":  0.0,
}

# ── CLAHE engine (created once, thread-safe for read-only apply) ──────────────
# Used in _infer_worker to enhance low-light camera frames BEFORE YOLO.
# Separate from CrackAnalyzer's own CLAHE instance (which works on grayscale
# sub-crops); this one enhances the full luminance channel of the BGR frame.
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

def _clahe_enhance(bgr: np.ndarray) -> np.ndarray:
    """
    Apply CLAHE to the L channel of the BGR frame (LAB colour space).
    Improves local contrast in dark pipe interiors without blowing out
    bright areas — unlike global histogram equalisation.
    Adds ~0.5 ms per frame on a modern CPU (negligible).
    """
    lab        = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b    = cv2.split(lab)
    l_enhanced = _clahe.apply(l)
    enhanced   = cv2.merge([l_enhanced, a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

# ── YOLO inference queue ─────────────────────────────────────────────────────
# _infer_worker submits frames here; _yolo_thread picks them up and returns
# (annotated_frame, detections) via _yolo_out_q.
# Depth=1 so only the latest frame is ever queued — old frames are dropped.
_yolo_in_q:  queue.Queue = queue.Queue(maxsize=1)
_yolo_out_q: queue.Queue = queue.Queue(maxsize=1)

def _yolo_thread():
    """Dedicated YOLO inference thread — one frame at a time, never blocks stream."""
    log.info("YOLO thread started (device=%s)", detector.device)
    while True:
        try:
            frame = _yolo_in_q.get(timeout=1.0)
            annotated, dets = detector.detect(frame)
            # Drop previous unread result before putting new one
            try:
                _yolo_out_q.get_nowait()
            except queue.Empty:
                pass
            _yolo_out_q.put((annotated, dets))
        except queue.Empty:
            continue
        except Exception:
            import traceback as _tb
            log.error("YOLO thread crash:\n%s", _tb.format_exc())

# ── Firestore write queue (non-blocking background thread) ───────────────────
# Detection events are pushed here from _infer_worker and written to
# Firestore's `mission_logs` collection by _firestore_writer.
# Queue depth 500 — older events dropped silently if writer falls behind.
_fs_queue: queue.Queue = queue.Queue(maxsize=500)

# ── RTDB critical-defect queue ────────────────────────────────────────────────
# Reserved for future use when crack pipeline is re-enabled.
# Currently empty — crack pipeline is OFF (YOLO-only mode).
_rtdb_queue: queue.Queue = queue.Queue(maxsize=200)

# ── Load YOLO ─────────────────────────────────────────────────────────────────
# Model path priority:
#   1. VIPER_MODEL_PATH env var  — custom trained model (set after training)
#   2. "yolov8n.pt"              — default COCO pretrained weights (fallback)
#
# After training with data/training/train.py, set the env var and restart:
#   Windows: set VIPER_MODEL_PATH=S:\...\runs\detect\viper_crack_v1\weights\best.pt
#   Linux:   export VIPER_MODEL_PATH=/path/to/runs/detect/viper_crack_v1/weights/best.pt
#
# Confidence can also be tuned via VIPER_CONFIDENCE (default 0.40).
# Lower confidence (e.g. 0.30) catches more cracks at the cost of more false
# positives; higher (e.g. 0.50) is stricter.
_DEFAULT_MODEL = r"S:\Dev\Program\VIPER\VIPER-vx\laptop\backend\runs\detect\viper_crack_v1\weights\best.pt"
_MODEL_PATH  = os.environ.get("VIPER_MODEL_PATH", _DEFAULT_MODEL)
_CONFIDENCE  = float(os.environ.get("VIPER_CONFIDENCE", "0.35"))

if _MODEL_PATH != "yolov8n.pt":
    _mp = Path(_MODEL_PATH)
    if not _mp.exists():
        log.warning("VIPER_MODEL_PATH=%s not found — falling back to yolov8n.pt", _MODEL_PATH)
        _MODEL_PATH = "yolov8n.pt"
    elif _mp.stat().st_size < 1024:
        log.warning("VIPER_MODEL_PATH=%s is too small (%d bytes) — may be corrupt", _MODEL_PATH, _mp.stat().st_size)
    else:
        log.info("Custom model: %s  (%.1f MB)", _MODEL_PATH, _mp.stat().st_size / 1e6)

log.info("Loading YOLO model: %s  (confidence=%.2f)", _MODEL_PATH, _CONFIDENCE)
detector = YOLODetector(
    model_path    = _MODEL_PATH,
    confidence    = _CONFIDENCE,
    crack_enabled = _crack_enabled,
)
detector.warmup()
log.info("YOLO model ready — %s", _MODEL_PATH)
log.info("=" * 60)
log.info("  ACTIVE MODEL : %s", _MODEL_PATH)
log.info("  CONFIDENCE   : %.2f", _CONFIDENCE)
log.info("  CRACK PIPE   : %s", "ON" if _crack_enabled else "OFF")
log.info("=" * 60)


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
            # Start recording on first real Pi connection (not at module load)
            if not recorder._running:
                recorder.start()
                log.info("Auto-recording started → %s", RECORDINGS_DIR)
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
    Blend thermal heatmap onto camera frame using cv2.addWeighted.

    Enhancement over v4:
      - Converts incoming thermal BGR to grayscale intensity, then re-applies
        COLORMAP_INFERNO for a perceptually uniform, high-contrast heatmap.
        (Pi sends viridis-colored JPEG; re-mapping to INFERNO gives clearer
        hot-spot isolation in narrow pipe interiors.)
      - Uses cv2.INTER_CUBIC for upscaling — eliminates the blocky pixel
        artefacts that INTER_NEAREST produces when scaling 32×24 → 640×480.
      - Applies a CLAHE pass on the thermal intensity before colormap so
        low-temperature-contrast scenes still show useful gradients.

    camera_bgr: numpy BGR frame (640×480)
    Returns: blended BGR frame
    """
    with _therm_lock:
        therm = _therm_bgr

    if therm is None:
        return camera_bgr

    # Convert Pi's pre-colored JPEG back to intensity then re-colorize.
    # This normalises out whatever colormap the Pi used and gives us a
    # consistent INFERNO heatmap regardless of Pi-side rendering choices.
    gray     = cv2.cvtColor(therm, cv2.COLOR_BGR2GRAY)

    # CLAHE on thermal intensity — reveals subtle temperature gradients
    gray     = _clahe.apply(gray)

    # Upscale with cubic interpolation to camera resolution
    th, tw   = camera_bgr.shape[:2]
    if gray.shape != (th, tw):
        gray = cv2.resize(gray, (tw, th), interpolation=cv2.INTER_CUBIC)

    # Apply INFERNO colormap — best perceptual separation of heat values
    heatmap  = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)

    cam_w    = 1.0 - _thermal_alpha
    therm_w  = _thermal_alpha
    return cv2.addWeighted(camera_bgr, cam_w, heatmap, therm_w, 0)


def _infer_worker():
    """
    Frame pump — decoupled from YOLO inference speed.

    1. Reads latest raw frame from Pi.
    2. If AI is ON: submits frame to _yolo_in_q (non-blocking).
                    Reads any finished YOLO result from _yolo_out_q.
                    Always writes SOMETHING to _ann_jpeg every loop.
    3. If AI is OFF: writes enhanced raw frame directly to _ann_jpeg.

    YOLO runs in _yolo_thread separately so a 2s CPU inference call
    never stalls this loop — _cam_generator always has fresh frames.
    """
    global _ann_jpeg, _detections

    enc      = [cv2.IMWRITE_JPEG_QUALITY, 85]
    last_raw = None

    log.info("Inference worker started")

    while True:
        # ── Get latest raw frame ──────────────────────────────────────────
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
            enhanced = _clahe_enhance(frame)

            if _ai_enabled:
                # Submit to YOLO thread (drop frame if queue full — YOLO busy)
                try:
                    _yolo_in_q.put_nowait(enhanced)
                except queue.Full:
                    pass  # YOLO still running on previous frame — skip this one

                # Pick up any finished YOLO result (non-blocking)
                try:
                    annotated, dets = _yolo_out_q.get_nowait()
                    with _det_lock:
                        _detections = dets
                    if _thermal_enabled:
                        annotated = _blend_thermal(annotated)
                    ok, buf = cv2.imencode(".jpg", annotated, enc)
                    if ok:
                        with _ann_lock:
                            _ann_jpeg = buf.tobytes()
                except queue.Empty:
                    # YOLO not done yet — write enhanced raw so stream stays live
                    out = _blend_thermal(enhanced) if _thermal_enabled else enhanced
                    ok, buf = cv2.imencode(".jpg", out, enc)
                    if ok:
                        with _ann_lock:
                            _ann_jpeg = buf.tobytes()
            else:
                # AI off — pass raw frame through (with optional thermal blend)
                out = _blend_thermal(enhanced) if _thermal_enabled else enhanced
                ok, buf = cv2.imencode(".jpg", out, enc)
                if ok:
                    with _ann_lock:
                        _ann_jpeg = buf.tobytes()
                with _det_lock:
                    _detections = []

        except Exception:
            import traceback as _tb
            log.error("Worker crash:\n%s", _tb.format_exc())


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


# =============================================================================
# Thread E — Pi system health poller
# =============================================================================

def _pi_health_poller():
    """
    Polls Pi /health every 2 s to collect system vitals: CPU temperature,
    thermal scene stats, sensor availability.

    Also measures round-trip time to Pi as a ping proxy by timing the
    HTTP request itself — no raw ICMP needed.

    Data stored in _pi_health_data and forwarded by laptop /health endpoint
    so the frontend only needs to talk to one server.
    """
    global _pi_health_data
    while True:
        try:
            t0 = time.monotonic()
            r  = requests.get(f"{PI_BASE}/health", timeout=3)
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
            with _pi_health_lock:
                _pi_health_data["ping_ms"] = None   # Pi unreachable
        time.sleep(2)


def _firestore_writer():
    """
    Background thread that drains _fs_queue and writes each detection event
    to the Firestore `mission_logs` collection.

    Uses auto-generated document IDs so parallel writes never collide.
    Each document contains:
        label, confidence, timestamp (ISO-8601 UTC), bbox, is_crack
        + NDT fields (severity, width_mm, length_mm, propagation_pct) for cracks.

    Batches are NOT used here intentionally: Firestore free tier allows
    ~20k writes/day. At 20 FPS with typical 1-3 detections/frame that
    budget is reached in ~5 minutes. The queue's 500-item cap and the
    conditional check (_firestore_client is not None) together ensure
    the writer simply idles when Firestore is not configured.
    """
    if _firestore_client is None:
        return   # Firestore not configured — thread exits immediately

    col = _firestore_client.collection("mission_logs")
    log.info("Firestore writer thread started → mission_logs")

    while True:
        try:
            event = _fs_queue.get(timeout=1.0)
            col.add(event)
        except queue.Empty:
            continue
        except Exception as exc:
            log.warning("Firestore write failed: %s", exc)


def _rtdb_writer():
    """
    Background thread — drains _rtdb_queue and pushes each critical-defect
    alert to Firebase Realtime Database /detectionEvents.

    Uses firebase_admin.db (Admin SDK) which bypasses the "auth != null"
    security rule, so no user token is needed.  The push() call generates
    a unique key (same as client-side push()) so concurrent writes from
    multiple frames never collide.

    Exits immediately if _rtdb_events_ref is None (Firebase not configured).
    """
    if _rtdb_events_ref is None:
        log.debug("RTDB writer idle — Firebase not configured")
        return

    log.info("RTDB writer started → detectionEvents (critical alerts only)")

    while True:
        try:
            alert = _rtdb_queue.get(timeout=1.0)
            _rtdb_events_ref.push(alert)
            log.info(
                "RTDB alert pushed — crack_id=%s  width=%.1fmm  severity=%s",
                alert.get("crack_id", "?"),
                alert.get("width_mm", 0.0),
                alert.get("severity", "?"),
            )
        except queue.Empty:
            continue
        except Exception as exc:
            log.warning("RTDB write failed: %s", exc)


threading.Thread(target=_raw_reader,       daemon=True, name="raw-reader").start()
threading.Thread(target=_yolo_thread,      daemon=True, name="yolo-thread").start()
threading.Thread(target=_infer_worker,     daemon=True, name="infer-worker").start()
threading.Thread(target=_thermal_reader,   daemon=True, name="thermal-reader").start()
threading.Thread(target=_gas_poller,       daemon=True, name="gas-poller").start()
threading.Thread(target=_pi_health_poller, daemon=True, name="pi-health-poller").start()
threading.Thread(target=_firestore_writer, daemon=True, name="fs-writer").start()
# Only start RTDB writer if Firebase RTDB is configured (avoids idle thread)
if _rtdb_events_ref is not None:
    threading.Thread(target=_rtdb_writer, daemon=True, name="rtdb-writer").start()
else:
    log.debug("RTDB writer not started — Firebase RTDB not configured")


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
# Recording is started on first successful Pi connection in _raw_reader,
# not at module load — prevents recordings full of black placeholder frames.
log.info("Recorder ready — will auto-start on Pi connection → %s", RECORDINGS_DIR)


# =============================================================================
# Camera MJPEG generator
# =============================================================================

def _cam_generator():
    """
    Stream generator.

    Logic:
    - _ann_jpeg is written by _infer_worker on EVERY raw frame (either
      with AI boxes or plain enhanced). It is ALWAYS the right frame to show.
    - Raw fallback is ONLY used during the first few frames before
      _infer_worker has produced its first output.
    - This eliminates the flicker caused by alternating between annotated
      and raw frames while YOLO is mid-inference.
    """
    hdr      = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    enc      = [cv2.IMWRITE_JPEG_QUALITY, 85]
    last     = None   # last frame bytes we yielded (any source)

    while True:
        # ── Primary: always use _ann_jpeg (updated every raw frame) ───────
        with _ann_lock:
            frame = _ann_jpeg

        # ── Fallback: raw frame only before first _ann_jpeg is ready ──────
        if frame is None:
            with _raw_lock:
                frame = _raw_jpeg

        # ── Placeholder: Pi not connected yet ─────────────────────────────
        if frame is None:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank, "Waiting for Pi...", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 80, 40), 2)
            _, buf = cv2.imencode(".jpg", blank, enc)
            frame  = buf.tobytes()

        if frame is not last:
            last = frame
            # Only record real frames — skip the "Waiting for Pi" placeholder
            # so recordings never start with black frames before Pi connects.
            with _raw_lock:
                pi_has_frame = _raw_jpeg is not None
            if pi_has_frame:
                recorder.write(frame)
            yield hdr + frame + b"\r\n"
        else:
            time.sleep(0.010)


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
    with _therm_lock:
        online = _therm_bgr is not None
    return jsonify({
        "thermal_enabled": _thermal_enabled,
        "thermal_alpha":   _thermal_alpha,
        "thermal_online":  online,
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


@app.route("/defect/size", methods=["POST"])
def defect_size():
    """
    Compute real-world size (mm) for a detection dict.
    Body: detection object as returned by /detections
    Optional: {"calibration_factor_mm_per_px": 0.195}
    Returns: {label, width_px, length_px, width_mm, length_mm, severity, source}
    """
    data   = request.get_json(silent=True) or {}
    factor = data.pop("calibration_factor_mm_per_px", None)
    if "bbox" not in data:
        return jsonify({"error": "detection object with 'bbox' field required"}), 400
    result = detector.get_defect_size(data, factor)
    return jsonify(result)


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


@app.route("/calibrate/metric_width", methods=["GET", "POST"])
def calibrate_metric_width():
    """
    Convert a horizontal pixel measurement to real-world millimetres using
    the camera's field of view.  Wraps YOLODetector.get_metric_width().

    Two calibration modes are selected automatically:

    MODE A — Pipe-geometry (no distance_mm supplied)
        Uses the configured pipe inner diameter and fill-ratio.
        This is the same formula CrackAnalyzer uses internally and works
        well when the camera is aimed straight down the pipe bore.

            px_per_mm = frame_width_px * pipe_fill_ratio / pipe_diameter_mm
            mm        = pixel_width / px_per_mm

    MODE B — FOV + known distance (distance_mm supplied)
        Uses the pinhole-camera model.  Use for external/side-scan
        inspections where the pipe-bore fill assumption breaks down.

            real_frame_width = 2 * distance_mm * tan(HFOV_rad / 2)
            mm               = pixel_width * real_frame_width / frame_width_px

    Parameters (JSON body or URL query string — both accepted)
    -----------------------------------------------------------
    pixel_width   float  required
    frame_width   int    optional  default 640
    distance_mm   float  optional  enables Mode B when supplied

    Response fields
    ---------------
    mm, px_per_mm, mm_per_px, mode, cam_hfov_deg, pixel_width
    + pipe_diameter_mm, pipe_fill_ratio  (Mode A only)
    + distance_mm                        (Mode B only)
    """
    data = (request.get_json(silent=True) or {}) if request.method == "POST"            else request.args.to_dict()

    if "pixel_width" not in data:
        return jsonify({
            "error":   "'pixel_width' is required",
            "example": {"pixel_width": 42, "frame_width": 640},
            "modes":   {
                "pipe_geometry": "omit distance_mm  — uses pipe_diameter from /crack/calibrate",
                "fov_distance":  "supply distance_mm — uses camera HFOV for pinhole projection",
            },
        }), 400

    try:
        pixel_width = float(data["pixel_width"])
        frame_width = int(data.get("frame_width", 640))
        d_mm        = data.get("distance_mm")
        distance_mm = float(d_mm) if d_mm is not None else None
    except (ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid parameter: {exc}"}), 400

    result = detector.get_metric_width(
        pixel_width = pixel_width,
        frame_width = frame_width,
        distance_mm = distance_mm,
    )
    return jsonify(result)

# ── Health ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    with _gas_lock:
        g = dict(_gas_data)
    # _latest_defect is never written while crack pipeline is OFF.
    # Snapshot without lock — values are always the safe defaults.
    defect_summary = {
        "worst_severity":  _latest_defect["worst_severity"],
        "crack_count":     _latest_defect["crack_count"],
        "critical_count":  _latest_defect["critical_count"],
        "max_width_mm":    _latest_defect["max_width_mm"],
        "max_length_mm":   _latest_defect["max_length_mm"],
    }
    with _pi_health_lock:
        pi_h = dict(_pi_health_data)
    with _therm_lock:
        thermal_online = _therm_bgr is not None
    return jsonify({
        "status":            "ok",
        "pi_connected":      _pi_connected,
        "ai_enabled":        _ai_enabled,
        "thermal_enabled":   _thermal_enabled,
        "thermal_online":    thermal_online,
        "thermal_alpha":     _thermal_alpha,
        "crack_enabled":     _crack_enabled,
        "gas":               g,
        "recording":         recorder.status,
        "defect":            defect_summary,
        # ── Pi system vitals (forwarded from Pi /health every 2 s) ──────
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
    log.info("=== VIPER AI Server — port 8000 ===")
    log.info("Pi: %s", PI_BASE)
    log.info("Recordings: %s", RECORDINGS_DIR)
    app.run(host="0.0.0.0", port=8000, threaded=True, debug=False)