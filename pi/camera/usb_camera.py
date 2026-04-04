# =============================================================================
# pi/camera/usb_camera.py  —  USB Camera with background reader thread  v3
# =============================================================================
# FIX v3: Buffer drain to eliminate stale-frame delay.
#
# Root cause of delay:
#   cv2.CAP_PROP_BUFFERSIZE=1 is silently ignored by V4L2 on most Pi kernels.
#   The driver still queues 3-4 frames internally. Every cap.read() returns
#   the OLDEST buffered frame — not the current one — causing visible lag.
#
# Fix:
#   Call cap.grab() in a tight loop to drain all queued frames, then
#   cap.retrieve() to decode only the freshest one. This gives ~0 buffer lag.
#
# Also:
#   - Explicit CAP_V4L2 backend — faster open, skips GStreamer probe
#   - Reduced encode sleep for tighter frame loop
# =============================================================================

import cv2, threading, time, logging, os

log = logging.getLogger(__name__)

# How many grab() calls to drain the V4L2 buffer before retrieve().
# 3 is enough for the default 3-frame V4L2 queue.
_DRAIN_FRAMES = 3


class USBCamera:
    def __init__(self, device_index=0, resolution=(640, 480), jpeg_quality=75):
        self.device_index       = device_index
        self.device_path        = f"/dev/video{device_index}"
        self.width, self.height = resolution
        self.jpeg_quality       = jpeg_quality

        self._cap     = None
        self._jpeg    = None
        self._lock    = threading.Lock()
        self._thread  = None
        self._running = False

        self._open_cap()

    # ------------------------------------------------------------------
    def _open_cap(self):
        if not os.path.exists(self.device_path):
            log.error("Device not found: %s", self.device_path)
            return

        # CAP_V4L2 backend: opens V4L2 directly, skips GStreamer/FFMPEG probe
        self._cap = cv2.VideoCapture(self.device_path, cv2.CAP_V4L2)

        if not self._cap.isOpened():
            log.error("Cannot open %s", self.device_path)
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS,          30)
        # Request smallest buffer — V4L2 may ignore this but try anyway
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = int(self._cap.get(cv2.CAP_PROP_FPS))
        log.info("Camera opened: %dx%d @ %dfps → %s", w, h, fps, self.device_path)

    def _start_thread(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def release(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap:
            self._cap.release()
        log.info("Camera released")

    # ------------------------------------------------------------------
    def _loop(self):
        enc = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        while self._running:
            if not self._cap or not self._cap.isOpened():
                log.warning("Camera lost — reopening %s ...", self.device_path)
                time.sleep(1)
                self._open_cap()
                continue

            # ── KEY FIX: drain the V4L2 buffer ──────────────────────────────
            # grab() pulls a frame from the driver queue WITHOUT decoding it.
            # Calling it _DRAIN_FRAMES times discards stale buffered frames.
            # retrieve() then decodes only the freshest grabbed frame.
            for _ in range(_DRAIN_FRAMES):
                self._cap.grab()
            ret, frame = self._cap.retrieve()
            # ────────────────────────────────────────────────────────────────

            if not ret or frame is None:
                time.sleep(0.01)
                continue

            ok, buf = cv2.imencode(".jpg", frame, enc)
            if ok:
                with self._lock:
                    self._jpeg = buf.tobytes()

    # ------------------------------------------------------------------
    def read(self):
        with self._lock:
            return self._jpeg

    def generate_frames(self):
        hdr  = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        last = None
        while True:
            frame = self.read()
            if frame is not None and frame is not last:
                last = frame
                yield hdr + frame + b"\r\n"
            else:
                time.sleep(0.003)

    @property
    def is_open(self):
        return self._running and self._cap is not None and self._cap.isOpened()