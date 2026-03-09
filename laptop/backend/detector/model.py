# =============================================================================
# detector/model.py  v2  —  YOLOv8 + NDT Crack Detection
# =============================================================================
#
# Changes from v1:
#   - detect() now runs TWO parallel pipelines:
#       A) YOLOv8n  — general object detection (people, tools, pipe fittings)
#       B) CrackAnalyzer — OpenCV NDT crack detection (hairline to critical)
#     Both results are merged and returned together.
#
#   - draw_detections() is now crack-aware:
#       • YOLO detections → standard coloured bounding boxes (unchanged)
#       • Crack detections → severity-coded rendering:
#           MINOR    → thin green contour + measurements
#           MODERATE → orange contour + measurements
#           CRITICAL → crimson (#FF3E3E) filled contour + corner brackets
#                      + full-width CRITICAL DEFECT banner at frame bottom
#
#   - detect() returns enriched detection list. Each entry:
#       {
#         'label':       str,
#         'confidence':  float,
#         'bbox':        [x1,y1,x2,y2],
#         'cls_id':      int,
#         # crack-only (absent for YOLO detections):
#         'is_crack':    True,
#         'severity':    "MINOR"|"MODERATE"|"CRITICAL",
#         'width_mm':    float,
#         'length_mm':   float,
#         'angle_deg':   float,
#         'propagation_pct': float,
#         'crack_id':    str,
#       }
#
#   - latest_defect_report module variable is updated each frame so
#     ai_server.py can expose GET /defects without coupling.
# =============================================================================

import logging
from typing import Optional, Tuple

import cv2
import numpy as np
import torch

# ── PyTorch 2.6 compatibility ─────────────────────────────────────────────────
try:
    import ultralytics.nn.tasks as _ult_tasks
    torch.serialization.add_safe_globals([
        _ult_tasks.DetectionModel,
        _ult_tasks.SegmentationModel,
        _ult_tasks.PoseModel,
        _ult_tasks.ClassificationModel,
    ])
except (ImportError, AttributeError):
    pass

from ultralytics import YOLO
from detector.crack_analyzer import CrackAnalyzer, CrackConfig, DefectReport

logger = logging.getLogger(__name__)

# Module-level last defect report — polled by ai_server.py for /defects
latest_defect_report: Optional[DefectReport] = None


class YOLODetector:
    """
    Dual-pipeline detector: YOLOv8n (general objects) + CrackAnalyzer (NDT).

    Parameters
    ----------
    model_path : str
        Path to .pt weights, or name like 'yolov8n.pt' (auto-downloaded).
    confidence : float
        YOLO minimum confidence threshold.
    device : str | None
        'cpu' | 'cuda' | 'mps' — auto-detected if None.
    crack_config : CrackConfig | None
        Override default crack parameters (pipe diameter, thresholds, etc.).
    crack_enabled : bool
        Set False to disable OpenCV crack pipeline entirely.
    """

    # ── Visual constants ────────────────────────────────────────────────────
    _CRIMSON = (50,  62, 255)   # BGR for #FF3E32 — critical defects
    _ORANGE  = (0,  165, 255)   # BGR for moderate defects
    _GREEN   = (0,  200,  80)   # BGR for minor defects
    _WHITE   = (255, 255, 255)
    _FONT    = cv2.FONT_HERSHEY_SIMPLEX

    def __init__(
        self,
        model_path:    str   = "yolov8n.pt",
        confidence:    float = 0.40,
        device:        Optional[str] = None,
        crack_config:  Optional[CrackConfig] = None,
        crack_enabled: bool  = True,
        cam_hfov_deg:  float = 68.0,    # horizontal FOV of the USB camera (degrees)
                                         # Typical wide-angle USB cam ≈ 60–75°.
                                         # Used by get_metric_width() when caller
                                         # supplies a known camera-to-wall distance.
    ):
        logger.info("Loading YOLO model: %s", model_path)
        self.model       = YOLO(model_path)
        self.confidence  = confidence
        # Pin device explicitly — never leave as None.
        # ultralytics with device=None re-runs device detection on every call
        # which adds 100-500ms overhead and can deadlock on Windows with
        # CPU-only torch due to OpenMP/MKL thread pool conflicts.
        if device is None:
            import torch as _torch
            self.device = 0 if _torch.cuda.is_available() else "cpu"
        else:
            self.device = device
        self.class_names = self.model.names

        # Seeded colour palette — same class = same colour every time
        rng = np.random.default_rng(seed=42)
        self._palette = rng.integers(80, 230, size=(max(len(self.class_names), 1), 3)).tolist()

        # NDT crack engine
        self.crack_enabled  = crack_enabled
        self.analyzer       = CrackAnalyzer(crack_config or CrackConfig())
        self.cam_hfov_deg   = float(cam_hfov_deg)

        logger.info(
            "YOLODetector ready — %d classes @ conf=%.2f | crack pipeline=%s",
            len(self.class_names), confidence,
            "ON" if crack_enabled else "OFF",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # detect()
    # ──────────────────────────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray) -> Tuple[np.ndarray, list]:
        """
        Run dual-pipeline inference on a single BGR frame.

        Pipeline A — YOLOv8n
            Standard COCO detection. General scene awareness.

        Pipeline B — CrackAnalyzer (runs only if crack_enabled=True)
            CLAHE → Gaussian blur → Canny → morphological closing →
            contour filter → skeleton length → perpendicular width →
            scale mapping → severity classification → propagation tracking.

        Returns
        -------
        annotated : np.ndarray
            BGR frame with all overlays drawn.
        detections : list[dict]
            Merged detection list (YOLO + crack entries).
        """
        global latest_defect_report
        annotated  = frame.copy()
        detections = []

        # ── Pipeline A: YOLO ──────────────────────────────────────────────
        try:
            results = self.model(
                frame,
                conf    = self.confidence,
                verbose = False,
                device  = self.device,
                stream  = False,   # return list, not generator
                imgsz   = 640,     # pin shape — avoids per-call reshape overhead
            )[0]

            for box in results.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                cls_id = int(box.cls[0])
                conf   = float(box.conf[0])
                label  = self.class_names.get(cls_id, f"class_{cls_id}")
                color  = tuple(self._palette[cls_id % len(self._palette)])

                self._draw_yolo_box(annotated, x1, y1, x2, y2, label, conf, color)

                detections.append({
                    "label":      label,
                    "confidence": round(conf, 3),
                    "bbox":       [x1, y1, x2, y2],
                    "cls_id":     cls_id,
                    "is_crack":   False,
                })

        except Exception as exc:
            logger.error("YOLO inference error: %s", exc)

        # ── Pipeline B: CrackAnalyzer ─────────────────────────────────────
        if self.crack_enabled:
            try:
                report = self.analyzer.analyze(frame)
                latest_defect_report = report

                # ── Skeleton overlay ──────────────────────────────────────
                # Draw the Zhang-Suen centreline directly on the annotated
                # frame BEFORE the bounding-box / label pass so the skeleton
                # appears underneath the measurement panels.
                #
                # Each severity uses a distinct colour that contrasts with
                # the bounding-box colour:
                #   MINOR    → bright cyan   (#00FFFF)  — thin crack, easy to see
                #   MODERATE → yellow        (#FFFF00)  — attention-level
                #   CRITICAL → white         (#FFFFFF)  — maximum contrast on
                #              the crimson fill so NDT engineers can trace it
                SKEL_COLORS = {
                    "MINOR":    (255, 255,   0),   # cyan  BGR
                    "MODERATE": (  0, 255, 255),   # yellow BGR
                    "CRITICAL": (255, 255, 255),   # white BGR
                }
                for m in report.measurements:
                    if m.skeleton_mask is None:
                        continue
                    skel_color = SKEL_COLORS.get(m.severity, (0, 255, 255))
                    # Dilate 1 px so the 1-px-wide skeleton is visible on screen
                    skel_vis = cv2.dilate(
                        m.skeleton_mask,
                        cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
                    )
                    # Colorise skeleton pixels without affecting the rest
                    skel_layer = np.zeros_like(annotated)
                    skel_layer[skel_vis > 0] = skel_color
                    # Blend at full opacity on top of current annotated frame
                    cv2.addWeighted(skel_layer, 0.85, annotated, 1.0, 0, annotated)

                # ── Per-crack detection dicts + bounding-box drawing ──────
                for crack in report.cracks:
                    self._draw_crack(annotated, crack)

                    detections.append({
                        "label":              f"crack ({crack['severity']})",
                        "confidence":         crack["confidence"],
                        "bbox":               crack["bbox"],
                        "cls_id":             -1,
                        "is_crack":           True,
                        "severity":           crack["severity"],
                        "width_mm":           crack["width_mm"],
                        "length_mm":          crack["length_mm"],
                        "angle_deg":          crack["angle_deg"],
                        "area_px":            crack["area_px"],
                        "propagation_pct":    crack["propagation_pct"],
                        "crack_id":           crack["crack_id"],
                        "centroid":           crack["centroid"],
                        # skeleton_length_px: Zhang-Suen centreline pixel count.
                        # Sourced from CrackMeasurement.length_px which is set
                        # by CrackAnalyzer._skeleton_length() — the value is the
                        # count of non-zero pixels in the thinned skeleton image.
                        # This is the most accurate crack-length proxy available
                        # without physical contact measurement.
                        "skeleton_length_px": crack["skeleton_length_px"],
                    })

                if report.critical_count > 0:
                    self._draw_critical_banner(annotated, report)

            except Exception as exc:
                logger.error("Crack analysis error: %s", exc)

        return annotated, detections

    # ──────────────────────────────────────────────────────────────────────────
    # draw_detections()  — standalone overlay (replay / recording annotation)
    # ──────────────────────────────────────────────────────────────────────────

    def draw_detections(self, frame: np.ndarray, detections: list) -> np.ndarray:
        """
        Re-draw a saved detection list onto any frame.

        Crack entries (is_crack=True) are rendered with severity colours:
          MINOR    → #00C850  green
          MODERATE → #FFA500  orange
          CRITICAL → #FF3E3E  crimson  (as specified in task)

        YOLO entries use standard class-coloured bounding boxes.
        """
        out = frame.copy()
        has_critical = any(
            d.get("is_crack") and d.get("severity") == "CRITICAL"
            for d in detections
        )

        for d in detections:
            if d.get("is_crack"):
                self._draw_crack(out, d)
            else:
                cls_id = d.get("cls_id", 0)
                color  = tuple(self._palette[max(0, cls_id) % len(self._palette)])
                x1, y1, x2, y2 = d["bbox"]
                self._draw_yolo_box(
                    out, x1, y1, x2, y2,
                    d["label"], d["confidence"], color,
                )

        # Banner if any critical crack
        if has_critical and latest_defect_report is not None:
            self._draw_critical_banner(out, latest_defect_report)

        return out

    # ──────────────────────────────────────────────────────────────────────────
    # Internal drawing helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _draw_yolo_box(
        self,
        img: np.ndarray,
        x1: int, y1: int, x2: int, y2: int,
        label: str, conf: float, color: tuple,
    ):
        """Standard YOLO bounding box + label chip (unchanged from v1)."""
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        text = f"{label}  {conf:.2f}"
        (tw, th), bl = cv2.getTextSize(text, self._FONT, 0.55, 1)
        cy1 = max(y1 - th - bl - 6, 0)
        cy2 = max(y1, th + bl + 6)
        cv2.rectangle(img, (x1, cy1), (x1 + tw + 6, cy2), color, -1)
        cv2.putText(img, text, (x1 + 3, cy2 - bl - 2),
                    self._FONT, 0.55, self._WHITE, 1, cv2.LINE_AA)

    def _draw_crack(self, img: np.ndarray, crack: dict):
        """
        Severity-coded crack overlay.

        MINOR    — thin green bounding box + measurement label
        MODERATE — orange box (thickness 2) + measurement panel
        CRITICAL — crimson semi-transparent fill + thick crimson outline
                   + industrial corner brackets
                   + measurement panel with red background
        """
        severity = crack.get("severity", "MINOR")
        x1, y1, x2, y2 = crack["bbox"]
        w_mm   = crack.get("width_mm", 0.0)
        l_mm   = crack.get("length_mm", 0.0)
        growth = crack.get("propagation_pct", 0.0)
        conf   = crack.get("confidence", 0.0)

        if severity == "CRITICAL":
            color      = self._CRIMSON
            thickness  = 3
            fill_alpha = 0.28
        elif severity == "MODERATE":
            color      = self._ORANGE
            thickness  = 2
            fill_alpha = 0.14
        else:
            color      = self._GREEN
            thickness  = 1
            fill_alpha = 0.07

        # Semi-transparent fill
        if fill_alpha > 0:
            overlay = img.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
            cv2.addWeighted(overlay, fill_alpha, img, 1 - fill_alpha, 0, img)

        # Bounding box
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)

        # Corner brackets for CRITICAL — NDT-inspection style
        if severity == "CRITICAL":
            blen = 14
            for px, py, sx, sy in [
                (x1, y1,  1,  1),
                (x2, y1, -1,  1),
                (x1, y2,  1, -1),
                (x2, y2, -1, -1),
            ]:
                cv2.line(img, (px, py), (px + sx * blen, py), color, 3)
                cv2.line(img, (px, py), (px, py + sy * blen), color, 3)

        # Measurement label panel (above bounding box)
        lines = [f"{severity}  {conf*100:.0f}%",
                 f"W:{w_mm:.1f}mm  L:{l_mm:.1f}mm"]
        if growth > 0.5:
            lines.append(f"\u25b2 GROWTH {growth:.1f}%/s")

        bg      = (40, 20, 160) if severity == "CRITICAL" else (20, 20, 20)
        panel_y = y1 - 4

        for i, line in enumerate(reversed(lines)):
            (tw, th), bl = cv2.getTextSize(line, self._FONT, 0.44, 1)
            ry = panel_y - i * (th + bl + 4)
            ry = max(ry, th + bl + 4)
            cv2.rectangle(img,
                          (x1, ry - th - bl - 2),
                          (x1 + tw + 6, ry + 2), bg, -1)
            cv2.putText(img, line, (x1 + 3, ry - bl),
                        self._FONT, 0.44, self._WHITE, 1, cv2.LINE_AA)

    def _draw_critical_banner(self, img: np.ndarray, report: DefectReport):
        """
        Full-width crimson alert banner at the frame bottom.
        Shown whenever any CRITICAL crack is present in the frame.
        """
        fh, fw   = img.shape[:2]
        banner_h = 36
        by1      = fh - banner_h

        # Semi-transparent dark-red background
        overlay = img.copy()
        cv2.rectangle(overlay, (0, by1), (fw, fh), (0, 0, 160), -1)
        cv2.addWeighted(overlay, 0.78, img, 0.22, 0, img)

        # Top border
        cv2.line(img, (0, by1), (fw, by1), self._CRIMSON, 2)

        text = (
            f"\u26a0  CRITICAL DEFECT  "
            f"\u2502  {report.critical_count} CRITICAL  "
            f"\u2502  MAX W:{report.max_width_mm:.1f}mm  "
            f"L:{report.max_length_mm:.1f}mm"
        )
        (tw, th), bl = cv2.getTextSize(text, self._FONT, 0.50, 1)
        tx = max(0, (fw - tw) // 2)
        ty = by1 + (banner_h + th) // 2
        cv2.putText(img, text, (tx, ty), self._FONT, 0.50,
                    self._WHITE, 1, cv2.LINE_AA)

    # ──────────────────────────────────────────────────────────────────────────
    # get_defect_size()  — standalone NDT measurement helper
    # ──────────────────────────────────────────────────────────────────────────

    def get_defect_size(
        self,
        detection: dict,
        calibration_factor_mm_per_px: float = None,
    ) -> dict:
        """
        Compute the real-world size of any bounding-box detection.

        For crack detections (is_crack=True) the CrackAnalyzer's more
        accurate skeleton + perpendicular-sampling measurements are used
        directly (already in the detection dict).

        For non-crack detections (YOLO boxes) the bounding box short-axis
        is used as a proxy for defect width and the long-axis for length,
        converted via the calibration factor.

        Parameters
        ----------
        detection : dict
            A single detection dict as returned by detect().
        calibration_factor_mm_per_px : float | None
            Override the default scale factor.
            Default = pipe_diameter_mm / (frame_width_px * pipe_fill_ratio)
            which equals 1 / px_per_mm from CrackAnalyzer.
            For a 640-px-wide frame, DN100 pipe, 80% fill:
                factor = 100 / (640 * 0.80) ≈ 0.195 mm/px

        Returns
        -------
        dict with keys:
            width_px    float  — bounding-box short-axis width in pixels
            length_px   float  — bounding-box long-axis length in pixels
            width_mm    float  — converted width in millimetres
            length_mm   float  — converted length in millimetres
            source      str    — "crack_analyzer" | "bbox_proxy"
            label       str    — detection label
            severity    str    — severity if crack, else "N/A"
        """
        # Derive default calibration factor from crack analyzer config
        if calibration_factor_mm_per_px is None:
            cfg     = self.analyzer.cfg
            # px_per_mm = frame_width * fill / pipe_diam
            # We don't know frame_width here so use 640 as standard reference.
            # Caller can override with actual frame width if needed.
            px_per_mm = (640.0 * cfg.pipe_fill_ratio) / cfg.pipe_diameter_mm
            calibration_factor_mm_per_px = 1.0 / px_per_mm if px_per_mm > 0 else 0.195

        # ── Crack detection: use CrackAnalyzer's measurements directly ──────
        if detection.get("is_crack"):
            w_mm = detection.get("width_mm",  0.0)
            l_mm = detection.get("length_mm", 0.0)
            w_px = detection.get("width_px",  0.0)
            l_px = detection.get("length_px", 0.0)
            # Fall back to bbox-derived values if crack fields missing
            if w_px == 0.0:
                x1, y1, x2, y2 = detection["bbox"]
                bw, bh = abs(x2 - x1), abs(y2 - y1)
                w_px   = float(min(bw, bh))
                l_px   = float(max(bw, bh))
                w_mm   = round(w_px * calibration_factor_mm_per_px, 2)
                l_mm   = round(l_px * calibration_factor_mm_per_px, 2)
            return {
                "label":    detection["label"],
                "width_px": round(w_px, 1),
                "length_px":round(l_px, 1),
                "width_mm": round(w_mm, 2),
                "length_mm":round(l_mm, 2),
                "severity": detection.get("severity", "UNKNOWN"),
                "source":   "crack_analyzer",
            }

        # ── YOLO detection: derive from bounding box ─────────────────────────
        x1, y1, x2, y2 = detection["bbox"]
        bw = abs(x2 - x1)
        bh = abs(y2 - y1)
        w_px = float(min(bw, bh))   # short axis = width proxy
        l_px = float(max(bw, bh))   # long axis  = length proxy
        return {
            "label":    detection["label"],
            "width_px": round(w_px, 1),
            "length_px":round(l_px, 1),
            "width_mm": round(w_px * calibration_factor_mm_per_px, 2),
            "length_mm":round(l_px * calibration_factor_mm_per_px, 2),
            "severity": "N/A",
            "source":   "bbox_proxy",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # get_metric_width()  — FOV-based pixel → mm calibration
    # ──────────────────────────────────────────────────────────────────────────

    def get_metric_width(
        self,
        pixel_width:   float,
        frame_width:   int   = 640,
        distance_mm:   Optional[float] = None,
    ) -> dict:
        """
        Convert a horizontal pixel measurement to real-world millimetres
        using the camera's field of view.

        This method backs the ``GET /calibrate/metric_width`` REST endpoint
        in ai_server.py, which accepts the same parameters via JSON body or
        URL query string.

        Two calibration modes are selected automatically:

        MODE A — Pipe-geometry (default, ``distance_mm`` omitted)
        ----------------------------------------------------------
        Uses the known pipe inner diameter and fill-ratio assumption.
        The same formula CrackAnalyzer uses internally, so results are
        consistent with the crack mm measurements served on /defects.

            px_per_mm = frame_width * pipe_fill_ratio / pipe_diameter_mm
            mm        = pixel_width / px_per_mm

        Pipe diameter is set via ``/crack/calibrate`` (default: DN100 = 100 mm).

        MODE B — FOV + known camera-to-surface distance
        ------------------------------------------------
        Uses the pinhole-camera model.  Suitable for external inspection
        or any scenario where the camera does NOT look straight down the
        bore.

            real_frame_width = 2 * distance_mm * tan(HFOV_rad / 2)
            mm_per_px        = real_frame_width / frame_width
            mm               = pixel_width * mm_per_px

        Parameters
        ----------
        pixel_width : float
            Horizontal extent of the feature in pixels.
        frame_width : int
            Width of the frame in pixels.  Defaults to 640 (Pi USB camera).
        distance_mm : float | None
            Camera-to-surface distance in mm.
            Provide to select Mode B; omit to use Mode A.

        Returns
        -------
        dict
            ``mm``               — real-world width in millimetres
            ``px_per_mm``        — calibration scale factor used
            ``mm_per_px``        — reciprocal of px_per_mm
            ``mode``             — ``"pipe_geometry"`` | ``"fov_distance"``
            ``pipe_diameter_mm`` — active pipe diameter (Mode A only)
            ``pipe_fill_ratio``  — active fill ratio   (Mode A only)
            ``distance_mm``      — the input distance   (Mode B only)
            ``cam_hfov_deg``     — configured camera HFOV (always present)
            ``pixel_width``      — the original pixel_width echoed back

        Notes
        -----
        ``cam_hfov_deg`` defaults to 68° which is a typical estimate for
        USB webcams with 3.6 mm lenses.  Pass the exact value from your
        camera's spec sheet to ``__init__`` for higher accuracy in Mode B.
        The pipe-geometry mode (Mode A) is independent of HFOV.
        """
        import math

        if distance_mm is not None:
            # ── Mode B: FOV + known distance ─────────────────────────────
            hfov_rad   = math.radians(self.cam_hfov_deg)
            real_width = 2.0 * float(distance_mm) * math.tan(hfov_rad / 2.0)
            mm_per_px  = real_width / max(frame_width, 1)
            px_per_mm  = 1.0 / mm_per_px if mm_per_px > 0 else 0.0
            mm         = round(pixel_width * mm_per_px, 3)
            return {
                "mm":               mm,
                "px_per_mm":        round(px_per_mm, 4),
                "mm_per_px":        round(mm_per_px, 6),
                "mode":             "fov_distance",
                "distance_mm":      float(distance_mm),
                "cam_hfov_deg":     self.cam_hfov_deg,
                "pixel_width":      pixel_width,
            }

        # ── Mode A: pipe-geometry (default) ──────────────────────────────
        cfg       = self.analyzer.cfg
        px_per_mm = (float(frame_width) * cfg.pipe_fill_ratio) / cfg.pipe_diameter_mm
        mm_per_px = 1.0 / px_per_mm if px_per_mm > 0 else 0.0
        mm        = round(pixel_width / px_per_mm, 3) if px_per_mm > 0 else 0.0
        return {
            "mm":               mm,
            "px_per_mm":        round(px_per_mm, 4),
            "mm_per_px":        round(mm_per_px, 6),
            "mode":             "pipe_geometry",
            "pipe_diameter_mm": cfg.pipe_diameter_mm,
            "pipe_fill_ratio":  cfg.pipe_fill_ratio,
            "cam_hfov_deg":     self.cam_hfov_deg,
            "pixel_width":      pixel_width,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────────────────────

    def warmup(self):
        """Pre-load both pipelines into memory with one dummy frame."""
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        self.detect(dummy)
        logger.info("YOLODetector warmed up (YOLO + CrackAnalyzer)")

    def set_crack_enabled(self, enabled: bool):
        self.crack_enabled = enabled
        logger.info("Crack pipeline: %s", "ON" if enabled else "OFF")

    def set_pipe_diameter(self, mm: float):
        """Hot-update pipe diameter for scale mapping — no restart needed."""
        self.analyzer.cfg.pipe_diameter_mm = mm
        logger.info("Pipe diameter updated to %.1f mm", mm)