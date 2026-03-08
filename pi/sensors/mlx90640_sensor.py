# =============================================================================
# pi/sensors/mlx90640_sensor.py  —  MLX90640 32×24 Thermal Sensor  v4
# =============================================================================
# CHANGES v4:
#   - init_hardware() / start_thread() split — hardware init happens on the
#     main thread before ADS1115 init, so both I2C inits never race.
#   - REFRESH_4_HZ (125ms/frame) — faster than default 4 Hz
#   - Horizontal flip (np.fliplr) — fixes mirrored sensor mount
#   - FOV crop — crops thermal raw grid to match camera's narrower FOV
#
# FOV TUNING:
#   MLX90640 is 110°H × 75°V.
#   Set CAM_HFOV / CAM_VFOV to match your USB camera spec.
#   Increase CAM_HFOV → thermal zooms out (less crop).
#   Decrease CAM_HFOV → thermal zooms in (more crop).
# =============================================================================

import threading, time, logging
import numpy as np
import cv2

log = logging.getLogger(__name__)

THERMAL_HFOV = 110.0
THERMAL_VFOV = 75.0
CAM_HFOV     = 70.0   # ← tune to your USB camera
CAM_VFOV     = 55.0   # ← tune to your USB camera

SENSOR_W, SENSOR_H = 32, 24
OUTPUT_W, OUTPUT_H = 640, 480

_CROP_W = min(1.0, CAM_HFOV / THERMAL_HFOV)
_CROP_H = min(1.0, CAM_VFOV / THERMAL_VFOV)
_CW = max(1, round(SENSOR_W * _CROP_W))
_CH = max(1, round(SENSOR_H * _CROP_H))
_X0 = (SENSOR_W - _CW) // 2
_Y0 = (SENSOR_H - _CH) // 2
_X1 = _X0 + _CW
_Y1 = _Y0 + _CH

COLORMAPS = {
    "inferno": cv2.COLORMAP_INFERNO,
    "jet":     cv2.COLORMAP_JET,
    "hot":     cv2.COLORMAP_HOT,
    "plasma":  cv2.COLORMAP_PLASMA,
}


class MLX90640Sensor:
    def __init__(self, colormap="inferno", flip_h=True):
        self.colormap_key = colormap
        self.flip_h       = flip_h
        self._i2c_lock    = None   # set by app.py before start_thread()
        self._jpeg        = None
        self._min_temp    = None
        self._max_temp    = None
        self._lock        = threading.Lock()
        self._thread      = None
        self._running     = False
        self._sensor      = None
        self.available    = False

    # ------------------------------------------------------------------
    def init_hardware(self, i2c=None):
        """
        Initialise MLX90640 hardware ONLY — no background thread started.
        Call this on the main thread before starting any other I2C device,
        so all hardware inits happen sequentially without bus contention.
        """
        try:
            import adafruit_mlx90640
            if i2c is None:
                import board, busio
                i2c = busio.I2C(board.SCL, board.SDA, frequency=400_000)
            self._sensor = adafruit_mlx90640.MLX90640(i2c)
            self._sensor.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_2_HZ
            self.available = True
            log.info("MLX90640 hardware ready (2 Hz, flip=%s, crop=%dx%d of %dx%d)",
                     self.flip_h, _CW, _CH, SENSOR_W, SENSOR_H)
        except Exception as exc:
            self.available = False
            log.error("MLX90640 init failed: %s", exc)

    def start_thread(self):
        """Start the background capture thread. Call after init_hardware()."""
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # Keep start() for backwards compatibility — does both steps
    def start(self, i2c=None):
        self.init_hardware(i2c)
        self.start_thread()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    # ------------------------------------------------------------------
    def _loop(self):
        buf      = [0.0] * (SENSOR_W * SENSOR_H)
        interval = 1.0 / 2   # 500ms

        while self._running:
            if not self.available:
                with self._lock:
                    self._jpeg     = None
                    self._min_temp = None
                    self._max_temp = None
                time.sleep(1)
                continue

            t0 = time.monotonic()
            try:
                if self._i2c_lock:
                    with self._i2c_lock:
                        self._sensor.getFrame(buf)
                else:
                    self._sensor.getFrame(buf)
                arr = np.array(buf, dtype=np.float32).reshape(SENSOR_H, SENSOR_W)

                if self.flip_h:
                    arr = np.fliplr(arr)

                arr   = arr[_Y0:_Y1, _X0:_X1]
                t_min = float(arr.min())
                t_max = float(arr.max())
                span  = max(t_max - t_min, 0.5)

                norm     = ((arr - t_min) / span * 255).astype(np.uint8)
                cmap     = COLORMAPS.get(self.colormap_key, cv2.COLORMAP_INFERNO)
                colored  = cv2.applyColorMap(norm, cmap)
                upscaled = cv2.resize(colored, (OUTPUT_W, OUTPUT_H),
                                      interpolation=cv2.INTER_CUBIC)

                cv2.putText(upscaled, f"{t_min:.1f}C",
                            (8, OUTPUT_H - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)
                cv2.putText(upscaled, f"{t_max:.1f}C",
                            (OUTPUT_W - 72, OUTPUT_H - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1, cv2.LINE_AA)

                _, jpeg = cv2.imencode(".jpg", upscaled,
                                       [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self._lock:
                    self._jpeg     = jpeg.tobytes()
                    self._min_temp = round(t_min, 1)
                    self._max_temp = round(t_max, 1)

            except Exception as exc:
                log.warning("Thermal read error: %s", exc)

            elapsed   = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0.005:
                time.sleep(remaining)

    # ------------------------------------------------------------------
    def read_jpeg(self):
        with self._lock:
            return self._jpeg

    def read_jpeg_generator(self):
        hdr     = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        last_id = None
        while True:
            frame = self.read_jpeg()
            if frame is not None and id(frame) != last_id:
                last_id = id(frame)
                yield hdr + frame + b"\r\n"
            else:
                time.sleep(0.015)

    def set_colormap(self, name):
        if name in COLORMAPS:
            self.colormap_key = name

    @property
    def min_temp(self):
        with self._lock: return self._min_temp

    @property
    def max_temp(self):
        with self._lock: return self._max_temp

    def stats(self):
        with self._lock:
            return {
                "available":  self.available,
                "min_temp_c": self._min_temp,
                "max_temp_c": self._max_temp,
                "colormap":   self.colormap_key,
                "flip_h":     self.flip_h,
            }