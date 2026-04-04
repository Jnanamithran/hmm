# =============================================================================
# pi/sensors/mq4.py  —  MQ4 Methane Gas Sensor via ADS1115 I2C ADC  v5
# =============================================================================
# WIRING:
#   ADS1115 VDD  → Pi 3.3V  (Pin 1)
#   ADS1115 GND  → Pi GND   (Pin 6)
#   ADS1115 SDA  → Pi GPIO2 (Pin 3)
#   ADS1115 SCL  → Pi GPIO3 (Pin 5)
#   ADS1115 ADDR → Pi GND   (Pin 6)  → address 0x48
#   MQ4 VCC  → Pi 5V   (Pin 2)
#   MQ4 GND  → Pi GND  (Pin 6)
#   MQ4 AO   → ADS1115 A0
#
# FIXES v5 — works with mlx90640_sensor.py v5:
#   - Lock timeout increased to 4.0s (was 2.0s)
#     MLX90640 at 1Hz + 0.6s settle = up to ~1.6s bus busy per cycle.
#     4.0s gives plenty of margin.
#   - Retry delay 0.3s to not waste the bus idle window
#   - Polling rate 0.5s
# =============================================================================

import threading, time, math, logging

log = logging.getLogger(__name__)

MQ4_A   = 1012.7
MQ4_B   = -2.786
MQ4_R0  = 10.0
MQ4_RL  = 10.0
MQ4_VCC = 5.0
ADS_FSV = 4.096

PPM_LOW    = 50
PPM_WARN   = 1000
PPM_DANGER = 5000

# At 4Hz MLX90640: getFrame ~250ms + settle 0.5s = ~0.75s max busy
# 1.5s gives 2x safety margin — enough without being slow
_LOCK_TIMEOUT = 1.5
_MAX_RETRIES  = 3


def _voltage_to_ppm(v):
    if v <= 0.01: return 0.0
    rs = ((MQ4_VCC - v) / v) * MQ4_RL
    if rs <= 0: return 0.0
    try:    return max(0.0, round(MQ4_A * math.pow(rs / max(MQ4_R0, 0.001), MQ4_B), 1))
    except: return 0.0


def _level(ppm):
    if ppm < PPM_LOW:    return "SAFE"
    if ppm < PPM_WARN:   return "LOW"
    if ppm < PPM_DANGER: return "WARNING"
    return "DANGER"


class MQ4Sensor:
    def __init__(self, i2c_address=0x48, channel=0):
        self.i2c_address = i2c_address
        self.channel     = channel
        self._i2c_lock   = None
        self._data       = None
        self._lock       = threading.Lock()
        self._thread     = None
        self._running    = False
        self._chan        = None
        self.available   = False

    def init_hardware(self, i2c=None, retries=5, retry_delay=0.5):
        import adafruit_ads1x15.ads1115 as ADS
        from adafruit_ads1x15.analog_in import AnalogIn

        if i2c is None:
            import board, busio
            i2c = busio.I2C(board.SCL, board.SDA)
        self._i2c = i2c

        if self._i2c_lock is None:
            log.warning("MQ4: i2c_lock not set — [Errno 5] errors likely.")

        for attempt in range(1, retries + 1):
            try:
                ads            = ADS.ADS1115(self._i2c, address=self.i2c_address)
                ads.gain       = 1
                self._ads      = ads
                self._chan     = AnalogIn(self._ads, self.channel)
                self.available = True
                log.info("ADS1115 ready at 0x%02X channel A%d (attempt %d/%d)",
                         self.i2c_address, self.channel, attempt, retries)
                return
            except Exception as exc:
                log.warning("ADS1115 init attempt %d/%d failed: %s", attempt, retries, exc)
                if attempt < retries:
                    time.sleep(retry_delay)

        self.available = False
        log.error("ADS1115 init failed after %d attempts", retries)

    def start_thread(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def start(self, i2c=None):
        self.init_hardware(i2c)
        self.start_thread()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _read_once(self):
        if self._i2c_lock:
            acquired = self._i2c_lock.acquire(timeout=_LOCK_TIMEOUT)
            if not acquired:
                raise TimeoutError(f"I2C bus busy >{_LOCK_TIMEOUT}s")
            try:
                voltage = self._chan.voltage
                raw     = self._chan.value
            finally:
                self._i2c_lock.release()
        else:
            voltage = self._chan.voltage
            raw     = self._chan.value
        return voltage, raw

    def _loop(self):
        while self._running:
            if not self.available:
                with self._lock:
                    self._data = None
                time.sleep(1)
                continue

            success = False
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    voltage, raw = self._read_once()
                    ppm = _voltage_to_ppm(voltage)
                    with self._lock:
                        self._data = {
                            "raw":       raw,
                            "voltage":   round(voltage, 4),
                            "ppm":       ppm,
                            "level":     _level(ppm),
                            "gas":       "CH4 / Methane",
                            "sensor":    "MQ4",
                            "adc":       "ADS1115",
                            "channel":   f"A{self.channel}",
                            "available": True,
                        }
                    success = True
                    break
                except TimeoutError as exc:
                    log.debug("MQ4 bus busy attempt %d/%d: %s", attempt, _MAX_RETRIES, exc)
                    time.sleep(0.3)
                except Exception as exc:
                    log.warning("ADS1115 read error attempt %d/%d: %s", attempt, _MAX_RETRIES, exc)
                    time.sleep(0.3)

            if not success:
                log.debug("MQ4: all %d attempts failed — skipping cycle", _MAX_RETRIES)

            time.sleep(0.2)   # 5Hz polling — fast gas updates

    def read(self):
        with self._lock:
            if self._data is None:
                return {"raw":None,"voltage":None,"ppm":None,"level":"OFFLINE",
                        "gas":"CH4 / Methane","sensor":"MQ4","adc":"ADS1115",
                        "channel":f"A{self.channel}","available":False}
            return dict(self._data)

    @property
    def ppm(self):
        with self._lock:
            return self._data["ppm"] if self._data else None

    @property
    def level(self):
        with self._lock:
            return self._data["level"] if self._data else "OFFLINE"