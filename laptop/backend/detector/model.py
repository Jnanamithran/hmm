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
    ):
        logger.info("Loading YOLO model: %s", model_path)
        self.model       = YOLO(model_path)
        self.confidence  = confidence
        self.device      = device
        self.class_names = self.model.names

        # Seeded colour palette — same class = same colour every time
        rng = np.random.default_rng(seed=42)
        self._palette = rng.integers(80, 230, size=(max(len(self.class_names), 1), 3)).tolist()

        # NDT crack engine
        self.crack_enabled = crack_enabled
        self.analyzer      = CrackAnalyzer(crack_config or CrackConfig())

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

                for crack in report.cracks:
                    self._draw_crack(annotated, crack)

                    detections.append({
                        "label":           f"crack ({crack['severity']})",
                        "confidence":      crack["confidence"],
                        "bbox":            crack["bbox"],
                        "cls_id":          -1,
                        "is_crack":        True,
                        "severity":        crack["severity"],
                        "width_mm":        crack["width_mm"],
                        "length_mm":       crack["length_mm"],
                        "angle_deg":       crack["angle_deg"],
                        "area_px":         crack["area_px"],
                        "propagation_pct": crack["propagation_pct"],
                        "crack_id":        crack["crack_id"],
                        "centroid":        crack["centroid"],
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
