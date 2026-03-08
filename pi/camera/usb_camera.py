# =============================================================================
# pi/camera/usb_camera.py  —  USB Camera with background reader thread  v2
# =============================================================================
# FIX: Use path string "/dev/videoN" instead of integer index.
# On Pi, cv2.VideoCapture(0) goes through OpenCV's device-enumeration which
# can fail when /dev/video0 is a UVC device alongside ISP/codec devices.
# cv2.VideoCapture("/dev/video0") opens V4L2 directly by path — always works.
# =============================================================================

import cv2, threading, time, logging, os

log = logging.getLogger(__name__)


class USBCamera:
    def __init__(self, device_index=0, resolution=(640, 480), jpeg_quality=75):
        self.device_index  = device_index
        self.device_path   = f"/dev/video{device_index}"
        self.width, self.height = resolution
        self.jpeg_quality  = jpeg_quality

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

        # Open by path string — bypasses OpenCV's broken index enumeration on Pi
        self._cap = cv2.VideoCapture(self.device_path)

        if not self._cap.isOpened():
            log.error("Cannot open %s", self.device_path)
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS,          30)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info("Camera opened: %dx%d @ %s", w, h, self.device_path)

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
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.05)
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