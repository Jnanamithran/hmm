# =============================================================================
# detector/crack_analyzer.py  v1  —  NDT Crack Detection & Quantification
# =============================================================================
#
# PURPOSE
# -------
# yolov8n.pt is COCO-trained and cannot detect surface cracks.
# This module runs a PARALLEL, fully OpenCV-based crack detection pipeline
# alongside YOLO, purpose-built for industrial NDT pipe inspection.
#
# PIPELINE STAGES
# ---------------
#   1. PRE-PROCESS   — CLAHE → Gaussian blur → Canny edge detection
#                      CLAHE is critical: it equalises local contrast so
#                      low-contrast hairline cracks become visible even in
#                      varying lighting conditions inside pipes.
#
#   2. CANDIDATE ISOLATION — morphological closing stitches broken edges
#                            into continuous crack lines; contour filter
#                            removes noise (area, aspect ratio, solidity).
#
#   3. SEGMENTATION  — binary mask per crack contour; Zhang-Suen skeleton
#                      gives a 1-px-wide centreline whose pixel count = length.
#                      Perpendicular width sampling at N points along the
#                      centreline gives a statistically robust width estimate.
#
#   4. SCALE MAPPING — pixel → mm using a known reference dimension
#                      (pipe inner diameter, set in config).
#                      Formula: mm = pixels / (frame_width_px * FILL_RATIO / PIPE_DIAM_MM)
#
#   5. SEVERITY SCORING — three-factor classifier:
#                         • Width (mm)
#                         • Length (mm)
#                         • Propagation rate (% area growth / second across frames)
#
#   6. PROPAGATION TRACKER — rolling dict keyed by crack "signature" (centroid
#                            bucket) tracks area over time so growth rate
#                            can be measured between frames.
#
# SEVERITY THRESHOLDS (based on ASME B31.3 / BS EN 13480 NDT practice)
# -----------------------------------------------------------------------
#   MINOR    — width < 1.0 mm  AND  length < 15 mm   AND  growth < 10%/s
#   MODERATE — 1.0 ≤ width < 3.0 mm  OR  15 ≤ length < 50 mm
#   CRITICAL — width ≥ 3.0 mm  OR  length ≥ 50 mm  OR  growth ≥ 10%/s
#
# SCALE CALIBRATION
# -----------------
# Default: DN100 (4-inch nominal bore) pipe, 100 mm inner diameter.
# The crawler camera is aimed down the pipe bore so the pipe
# fills approximately PIPE_FILL_RATIO (0.80) of the frame width.
# Change PIPE_DIAMETER_MM and PIPE_FILL_RATIO in CrackConfig to match
# your actual pipe spec — no code changes needed.
# =============================================================================

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration dataclass (edit here, nowhere else)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CrackConfig:
    # ── Scale mapping ──────────────────────────────────────────────────────
    pipe_diameter_mm: float = 100.0   # DN100 inner bore (mm)
    pipe_fill_ratio:  float = 0.80    # fraction of frame width the pipe fills
    # px_per_mm is computed at runtime from frame width

    # ── Pre-processing ─────────────────────────────────────────────────────
    clahe_clip_limit:    float = 3.0    # higher → stronger local contrast boost
    clahe_tile_grid:     int   = 8      # CLAHE tile grid size (NxN)
    gaussian_ksize:      int   = 5      # Gaussian blur kernel (must be odd)
    canny_low:           int   = 40     # Canny lower hysteresis threshold
    canny_high:          int   = 120    # Canny upper hysteresis threshold
    morph_close_ksize:   int   = 7      # closing kernel — stitches broken edges
    morph_dilate_iters:  int   = 1      # dilation after closing to thicken mask

    # ── Contour filtering ─────────────────────────────────────────────────
    min_crack_area_px:   int   = 150    # ignore tiny speckle noise
    max_crack_area_px:   int   = 50000  # ignore full-frame blobs (not cracks)
    min_aspect_ratio:    float = 2.5    # cracks are elongated (length/width ≥ 2.5)
    max_solidity:        float = 0.75   # cracks are jagged (hull fill ≤ 75%)

    # ── Severity thresholds ────────────────────────────────────────────────
    minor_max_width_mm:    float = 1.0
    minor_max_length_mm:   float = 15.0
    critical_min_width_mm: float = 3.0
    critical_min_length_mm:float = 50.0
    critical_growth_rate:  float = 0.10   # 10% area growth per second = critical

    # ── Propagation tracker ────────────────────────────────────────────────
    tracker_grid_cells:  int   = 16     # frame divided into NxN grid for ID
    tracker_history:     int   = 30     # frames of history to keep per crack

    # ── Width sampling ────────────────────────────────────────────────────
    width_sample_points: int   = 12     # perpendicular samples along skeleton


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CrackMeasurement:
    """Physical and geometric measurements for one detected crack."""
    contour:         np.ndarray          # raw OpenCV contour
    mask:            np.ndarray          # binary mask (frame-sized uint8)
    bbox:            Tuple[int,int,int,int]  # (x1, y1, x2, y2) axis-aligned
    centroid:        Tuple[float, float]
    area_px:         int
    length_px:       float               # centreline length = skeleton pixel count
    width_px:        float
    length_mm:       float
    width_mm:        float
    angle_deg:       float               # crack orientation (0° = horizontal)
    severity:        str                 # "MINOR" | "MODERATE" | "CRITICAL"
    propagation_pct: float               # area growth % / second (0 if new)
    confidence:      float               # OpenCV-derived confidence score
    crack_id:        str                 # grid-cell-based stable identifier
    # ── Skeleton image (Zhang-Suen / iterative-erosion) ──────────────────
    # 1-pixel-wide centreline mask, same shape as `mask`.
    # Stored here so callers (model.py, ai_server.py) can render the
    # skeleton overlay directly without re-running thinning.
    # Optional: None when the mask was too small to skeletonise.
    skeleton_mask:   Optional[np.ndarray] = field(
        default=None, repr=False, compare=False, hash=False,
    )


@dataclass
class DefectReport:
    """Summary pushed to /defects endpoint and embedded in /health."""
    timestamp:         float
    crack_count:       int
    critical_count:    int
    moderate_count:    int
    minor_count:       int
    worst_severity:    str               # "NONE" | "MINOR" | "MODERATE" | "CRITICAL"
    max_width_mm:      float
    max_length_mm:     float
    max_growth_pct:    float
    cracks:            List[dict]        # JSON-serialisable measurement list
    # ── Non-serialisable measurement objects (numpy arrays inside) ────────
    # Kept here so downstream code (model.py skeleton overlay, ai_server.py
    # RTDB push) can access skeleton_mask and contour without a second pass.
    # NEVER pass this to dataclasses.asdict() — use to_dict() instead.
    measurements: List["CrackMeasurement"] = field(
        default_factory=list, repr=False, compare=False, hash=False,
    )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable snapshot of this report.

        Identical to what dataclasses.asdict() would produce for the scalar
        fields, but safely skips the `measurements` list which contains
        numpy arrays (contour, mask, skeleton_mask) that are not serialisable.
        """
        return {
            "timestamp":      self.timestamp,
            "crack_count":    self.crack_count,
            "critical_count": self.critical_count,
            "moderate_count": self.moderate_count,
            "minor_count":    self.minor_count,
            "worst_severity": self.worst_severity,
            "max_width_mm":   self.max_width_mm,
            "max_length_mm":  self.max_length_mm,
            "max_growth_pct": self.max_growth_pct,
            "cracks":         self.cracks,   # already a list[dict]
        }


# ─────────────────────────────────────────────────────────────────────────────
# Propagation tracker
# ─────────────────────────────────────────────────────────────────────────────

class PropagationTracker:
    """
    Tracks crack area over time to compute growth rate.

    Each crack is keyed by the grid cell its centroid falls into —
    a coarse but stable identifier that survives small frame-to-frame
    movements of the rover.
    """

    def __init__(self, grid: int = 16, history: int = 30):
        self._grid    = grid
        self._history = history
        # crack_id → deque of (timestamp, area_px)
        self._records: Dict[str, deque] = {}

    def make_id(self, cx: float, cy: float, fw: int, fh: int) -> str:
        gx = int(cx / fw * self._grid)
        gy = int(cy / fh * self._grid)
        return f"c{gx:02d}r{gy:02d}"

    def update(self, crack_id: str, area_px: int) -> float:
        """
        Record a new area sample. Returns growth rate (fraction/second).
        0.0 if this is the first observation.
        """
        now = time.monotonic()
        if crack_id not in self._records:
            self._records[crack_id] = deque(maxlen=self._history)

        hist = self._records[crack_id]
        hist.append((now, area_px))

        if len(hist) < 2:
            return 0.0

        t0, a0 = hist[0]
        t1, a1 = hist[-1]
        dt = t1 - t0
        if dt < 0.1 or a0 == 0:
            return 0.0

        # Fractional growth per second
        return max(0.0, (a1 - a0) / a0 / dt)

    def prune(self, active_ids):
        """Remove stale crack entries not seen in current frame."""
        stale = [k for k in self._records if k not in active_ids]
        for k in stale:
            del self._records[k]


# ─────────────────────────────────────────────────────────────────────────────
# Main crack analyzer
# ─────────────────────────────────────────────────────────────────────────────

class CrackAnalyzer:
    """
    Full NDT crack detection and quantification engine.

    Usage
    -----
    analyzer = CrackAnalyzer()
    report   = analyzer.analyze(bgr_frame)
    # report.cracks  → list of measurement dicts
    # report.worst_severity  → "MINOR" / "MODERATE" / "CRITICAL" / "NONE"
    """

    SEVERITY_ORDER = {"NONE": 0, "MINOR": 1, "MODERATE": 2, "CRITICAL": 3}
    SEVERITY_COLOR = {
        "MINOR":    (0,   200, 80),    # green
        "MODERATE": (0,   165, 255),   # orange
        "CRITICAL": (50,  62,  255),   # crimson #FF3E32  (BGR)
    }
    # Crimson #FF3E3E in BGR
    CRIMSON = (62, 62, 255)

    def __init__(self, config: Optional[CrackConfig] = None):
        self.cfg     = config or CrackConfig()
        self.tracker = PropagationTracker(
            grid    = self.cfg.tracker_grid_cells,
            history = self.cfg.tracker_history,
        )

        # CLAHE engine
        self._clahe = cv2.createCLAHE(
            clipLimit   = self.cfg.clahe_clip_limit,
            tileGridSize= (self.cfg.clahe_tile_grid, self.cfg.clahe_tile_grid),
        )

        # Morphological kernels (built once)
        kc = self.cfg.morph_close_ksize
        self._close_kernel  = cv2.getStructuringElement(cv2.MORPH_RECT, (kc, kc))
        self._dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        self._skel_kernel   = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))

        logger.info(
            "CrackAnalyzer ready — pipe %.0f mm, fill %.0f%%, "
            "Canny %d/%d, severity thresholds: CRITICAL ≥%.1fmm",
            self.cfg.pipe_diameter_mm,
            self.cfg.pipe_fill_ratio * 100,
            self.cfg.canny_low,
            self.cfg.canny_high,
            self.cfg.critical_min_width_mm,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def analyze(self, bgr_frame: np.ndarray) -> DefectReport:
        """
        Run full NDT pipeline on one BGR frame.
        Returns a DefectReport (always — empty if no cracks found).
        """
        fh, fw = bgr_frame.shape[:2]
        px_per_mm = self._px_per_mm(fw)

        # Stage 1 — pre-process to crack-highlight mask
        edge_mask = self._preprocess(bgr_frame)

        # Stage 2 — extract candidate crack contours
        candidates = self._find_candidates(edge_mask)

        # Stage 3-5 — measure, score, track each candidate
        measurements: List[CrackMeasurement] = []
        active_ids = set()

        for cnt in candidates:
            m = self._measure(cnt, edge_mask, bgr_frame, px_per_mm, fw, fh)
            if m is None:
                continue
            active_ids.add(m.crack_id)
            m.propagation_pct = self.tracker.update(m.crack_id, m.area_px)
            m.severity        = self._classify(m)
            measurements.append(m)

        self.tracker.prune(active_ids)

        # Sort by severity (worst first)
        measurements.sort(key=lambda m: self.SEVERITY_ORDER[m.severity], reverse=True)

        return self._build_report(measurements)

    def preprocess_preview(self, bgr_frame: np.ndarray) -> np.ndarray:
        """
        Return a 3-channel BGR visualisation of the pre-processing stages
        for debugging. Not used in the inference loop.
        """
        gray  = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
        clahe = self._clahe.apply(gray)
        blur  = cv2.GaussianBlur(clahe, (self.cfg.gaussian_ksize,)*2, 0)
        edges = cv2.Canny(blur, self.cfg.canny_low, self.cfg.canny_high)
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

    # ──────────────────────────────────────────────────────────────────────
    # Stage 1 — Pre-processing
    # ──────────────────────────────────────────────────────────────────────

    def _preprocess(self, bgr: np.ndarray) -> np.ndarray:
        """
        Returns a binary mask where bright pixels = candidate crack edges.

        Pipeline:
          Gray → CLAHE (local contrast equalisation)
               → Gaussian blur (remove high-freq sensor noise)
               → Canny edges
               → Morphological closing (stitch broken edge lines)
               → Dilation (thicken for contour stability)
        """
        gray  = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        clahe = self._clahe.apply(gray)
        blur  = cv2.GaussianBlur(
            clahe,
            (self.cfg.gaussian_ksize, self.cfg.gaussian_ksize),
            0,
        )
        edges = cv2.Canny(blur, self.cfg.canny_low, self.cfg.canny_high)
        closed= cv2.morphologyEx(edges, cv2.MORPH_CLOSE, self._close_kernel)
        dilated = cv2.dilate(closed, self._dilate_kernel,
                             iterations=self.cfg.morph_dilate_iters)
        return dilated

    # ──────────────────────────────────────────────────────────────────────
    # Stage 2 — Candidate extraction
    # ──────────────────────────────────────────────────────────────────────

    def _find_candidates(self, mask: np.ndarray) -> List[np.ndarray]:
        """
        Find contours that geometrically resemble cracks:
          - Area within [min, max] range
          - High aspect ratio (elongated shape)
          - Low solidity (jagged / non-convex outline)
        """
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        candidates = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.cfg.min_crack_area_px or area > self.cfg.max_crack_area_px:
                continue

            # Aspect ratio from minimum-area rotated rectangle
            rect   = cv2.minAreaRect(cnt)
            w, h   = rect[1]
            if w == 0 or h == 0:
                continue
            aspect = max(w, h) / min(w, h)
            if aspect < self.cfg.min_aspect_ratio:
                continue

            # Solidity = contour area / convex hull area
            hull     = cv2.convexHull(cnt)
            hull_area= cv2.contourArea(hull)
            if hull_area == 0:
                continue
            solidity = area / hull_area
            if solidity > self.cfg.max_solidity:
                continue

            candidates.append(cnt)

        return candidates

    # ──────────────────────────────────────────────────────────────────────
    # Stage 3 — Segmentation + measurement
    # ──────────────────────────────────────────────────────────────────────

    def _measure(
        self,
        contour: np.ndarray,
        edge_mask: np.ndarray,
        bgr: np.ndarray,
        px_per_mm: float,
        fw: int,
        fh: int,
    ) -> Optional[CrackMeasurement]:
        """
        Given a crack contour, compute all physical measurements.
        Returns None if the contour is degenerate.
        """
        # Bounding box
        x, y, w, h = cv2.boundingRect(contour)
        x1, y1, x2, y2 = x, y, x+w, y+h

        # Centroid
        M = cv2.moments(contour)
        if M["m00"] == 0:
            return None
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]

        # Crack orientation (angle of minimum-area rotated rect)
        rect     = cv2.minAreaRect(contour)
        angle    = rect[2]  # degrees

        # Build binary mask for this crack
        crack_mask = np.zeros(edge_mask.shape, dtype=np.uint8)
        cv2.drawContours(crack_mask, [contour], -1, 255, cv2.FILLED)

        # Skeleton (Zhang-Suen thinning) → centreline length
        # _skeleton_length() now returns (count, skel_image) so we retain
        # the skeleton image for overlay rendering in model.py / ai_server.py.
        length_px, skeleton_image = self._skeleton_length(crack_mask)

        # Width via perpendicular sampling along skeleton
        width_px = self._measure_width(crack_mask, contour)

        # Convert to mm
        length_mm = length_px / px_per_mm if px_per_mm > 0 else 0.0
        width_mm  = width_px  / px_per_mm if px_per_mm > 0 else 0.0

        # Confidence score: combination of area, aspect, and edge density
        area = int(cv2.contourArea(contour))
        confidence = self._score_confidence(contour, crack_mask, edge_mask)

        # Stable crack ID from grid cell
        crack_id = self.tracker.make_id(cx, cy, fw, fh)

        return CrackMeasurement(
            contour        = contour,
            mask           = crack_mask,
            bbox           = (x1, y1, x2, y2),
            centroid       = (cx, cy),
            area_px        = area,
            length_px      = float(length_px),
            width_px       = float(width_px),
            length_mm      = round(length_mm, 2),
            width_mm       = round(width_mm,  2),
            angle_deg      = round(float(angle), 1),
            severity       = "MINOR",   # overwritten by _classify()
            propagation_pct= 0.0,       # overwritten by tracker.update()
            confidence     = round(confidence, 3),
            crack_id       = crack_id,
            skeleton_mask  = skeleton_image,   # ← centreline image stored here
        )

    # ──────────────────────────────────────────────────────────────────────
    # Skeleton length (Zhang-Suen iterative thinning)
    # ──────────────────────────────────────────────────────────────────────

    def _skeleton_length(self, mask: np.ndarray) -> Tuple[int, np.ndarray]:
        """
        Thin binary mask to a 1-pixel-wide centreline skeleton and count
        non-zero pixels.  Pixel count ≈ centreline length in pixels.

        Returns
        -------
        (length_px, skeleton_image)
            length_px      — int, number of lit skeleton pixels (= crack length)
            skeleton_image — uint8 ndarray, same shape as mask, 255 on
                             centreline pixels and 0 elsewhere.  Callers can
                             use this to render the skeleton overlay directly.

        Uses cv2.ximgproc.thinning (Zhang-Suen) when available.
        Falls back to iterative erosion — slower but dependency-free.
        """
        try:
            import cv2.ximgproc as xip
            skel = xip.thinning(mask, thinningType=xip.THINNING_ZHANGSUEN)
        except (AttributeError, ImportError, ModuleNotFoundError):
            # AttributeError      — ximgproc present but thinning() unavailable
            # ModuleNotFoundError — opencv-contrib-python not installed (common)
            # ImportError         — partial install or platform mismatch
            # All three: fall back to pure-OpenCV iterative erosion skeleton.
            # To get the faster Zhang-Suen version:
            #   pip install opencv-contrib-python
            skel = self._manual_skeleton(mask)
        return int(np.count_nonzero(skel)), skel

    def _manual_skeleton(self, mask: np.ndarray) -> np.ndarray:
        """Fallback skeleton via iterative erosion (no ximgproc needed)."""
        img  = mask.copy()
        skel = np.zeros_like(img)
        k    = self._skel_kernel
        for _ in range(64):   # max iterations
            eroded  = cv2.erode(img, k)
            opened  = cv2.dilate(eroded, k)
            temp    = cv2.subtract(img, opened)
            skel    = cv2.bitwise_or(skel, temp)
            img     = eroded.copy()
            if cv2.countNonZero(img) == 0:
                break
        return skel

    # ──────────────────────────────────────────────────────────────────────
    # Width measurement via perpendicular sampling
    # ──────────────────────────────────────────────────────────────────────

    def _measure_width(self, mask: np.ndarray, contour: np.ndarray) -> float:
        """
        Estimate crack width by casting perpendicular rays at evenly spaced
        points along the contour and measuring the first-hit distances to
        the mask boundary on both sides.

        Returns median width across all sample points (robust to outliers).
        """
        n     = self.cfg.width_sample_points
        total = len(contour)
        if total < 4:
            # Fallback: use bounding box short-axis
            _, (bw, bh), _ = cv2.minAreaRect(contour)
            return float(min(bw, bh))

        step     = max(1, total // n)
        widths   = []
        fh, fw   = mask.shape[:2]

        for i in range(0, total, step):
            pt     = contour[i][0]
            # Approximate tangent from neighbouring points
            i_prev = max(0,     i - step)
            i_next = min(total-1, i + step)
            p0     = contour[i_prev][0].astype(float)
            p1     = contour[i_next][0].astype(float)
            tang   = p1 - p0
            norm   = np.linalg.norm(tang)
            if norm < 1e-6:
                continue
            # Perpendicular direction (unit vector)
            perp   = np.array([-tang[1], tang[0]]) / norm

            # Cast ray in +perp direction until mask boundary
            d_pos = self._ray_distance(mask, pt.astype(float), perp, fw, fh)
            d_neg = self._ray_distance(mask, pt.astype(float), -perp, fw, fh)
            widths.append(d_pos + d_neg)

        if not widths:
            _, (bw, bh), _ = cv2.minAreaRect(contour)
            return float(min(bw, bh))

        return float(np.median(widths))

    @staticmethod
    def _ray_distance(
        mask: np.ndarray,
        start: np.ndarray,
        direction: np.ndarray,
        fw: int, fh: int,
        max_steps: int = 80,
    ) -> float:
        """Walk along `direction` from `start` until mask pixel = 0 or boundary."""
        pos = start.copy()
        for step in range(1, max_steps + 1):
            pos += direction
            x, y = int(pos[0]), int(pos[1])
            if x < 0 or x >= fw or y < 0 or y >= fh:
                return float(step)
            if mask[y, x] == 0:
                return float(step)
        return float(max_steps)

    # ──────────────────────────────────────────────────────────────────────
    # Confidence scoring
    # ──────────────────────────────────────────────────────────────────────

    def _score_confidence(
        self,
        contour: np.ndarray,
        crack_mask: np.ndarray,
        edge_mask: np.ndarray,
    ) -> float:
        """
        Heuristic confidence (0.0–1.0) for OpenCV-detected cracks.

        Factors:
          - Edge density inside the mask (how many Canny edges are inside)
          - Aspect ratio score (more elongated → more crack-like)
          - Area score (moderate size → more credible)
        """
        area = cv2.contourArea(contour)
        if area < 1:
            return 0.0

        # Edge density: proportion of crack mask pixels that are Canny edges
        inside_edges = cv2.bitwise_and(edge_mask, crack_mask)
        density = cv2.countNonZero(inside_edges) / area
        density_score = min(1.0, density * 3.0)   # saturates at 33% edge density

        # Aspect ratio score
        rect  = cv2.minAreaRect(contour)
        w, h  = rect[1]
        if w == 0 or h == 0:
            return 0.0
        aspect = max(w, h) / min(w, h)
        aspect_score = min(1.0, (aspect - self.cfg.min_aspect_ratio) / 7.0 + 0.5)

        # Area score: peak at ~1000 px
        area_score = min(1.0, area / 1000.0) if area < 1000 else max(
            0.3, 1.0 - (area - 1000) / 49000.0
        )

        return round(
            0.50 * density_score + 0.30 * aspect_score + 0.20 * area_score,
            3,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Stage 4 — Scale mapping
    # ──────────────────────────────────────────────────────────────────────

    def _px_per_mm(self, frame_width_px: int) -> float:
        """
        Compute pixels-per-millimetre from the known pipe diameter.

        Assumes the pipe bore fills `pipe_fill_ratio` of the frame width.
        pipe_diameter_px  = frame_width_px * pipe_fill_ratio
        px_per_mm         = pipe_diameter_px / pipe_diameter_mm
        """
        pipe_px = frame_width_px * self.cfg.pipe_fill_ratio
        return pipe_px / self.cfg.pipe_diameter_mm

    # ──────────────────────────────────────────────────────────────────────
    # Stage 5 — Severity classification
    # ──────────────────────────────────────────────────────────────────────

    def _classify(self, m: CrackMeasurement) -> str:
        """
        Three-factor severity gate (width, length, propagation rate).

        CRITICAL if ANY factor exceeds its critical threshold.
        MODERATE if ANY factor exceeds its moderate threshold.
        Otherwise MINOR.
        """
        cfg = self.cfg

        # ── CRITICAL gates ──────────────────────────────────────────────
        if m.width_mm  >= cfg.critical_min_width_mm:   return "CRITICAL"
        if m.length_mm >= cfg.critical_min_length_mm:  return "CRITICAL"
        if m.propagation_pct >= cfg.critical_growth_rate: return "CRITICAL"

        # ── MODERATE gates ──────────────────────────────────────────────
        if m.width_mm  >= cfg.minor_max_width_mm:      return "MODERATE"
        if m.length_mm >= cfg.minor_max_length_mm:     return "MODERATE"
        if m.propagation_pct >= cfg.critical_growth_rate * 0.5: return "MODERATE"

        return "MINOR"

    # ──────────────────────────────────────────────────────────────────────
    # Build serialisable DefectReport
    # ──────────────────────────────────────────────────────────────────────

    def _build_report(self, measurements: List[CrackMeasurement]) -> DefectReport:
        if not measurements:
            return DefectReport(
                timestamp=time.time(), crack_count=0,
                critical_count=0, moderate_count=0, minor_count=0,
                worst_severity="NONE", max_width_mm=0.0,
                max_length_mm=0.0, max_growth_pct=0.0, cracks=[],
            )

        sev_counts = {"MINOR": 0, "MODERATE": 0, "CRITICAL": 0}
        for m in measurements:
            sev_counts[m.severity] += 1

        worst = max(
            (m.severity for m in measurements),
            key=lambda s: self.SEVERITY_ORDER[s],
        )

        cracks_json = [
            {
                "crack_id":           m.crack_id,
                "severity":           m.severity,
                "confidence":         m.confidence,
                "width_mm":           m.width_mm,
                "length_mm":          m.length_mm,
                "width_px":           round(m.width_px, 1),
                "length_px":          round(m.length_px, 1),
                # skeleton_length_px == length_px (pixel count of Zhang-Suen
                # centreline), exposed explicitly so consumers don't need to
                # know the implementation detail.
                "skeleton_length_px": round(m.length_px, 1),
                "angle_deg":          m.angle_deg,
                "area_px":            m.area_px,
                "propagation_pct":    round(m.propagation_pct * 100, 2),
                "bbox":               list(m.bbox),
                "centroid":           [round(m.centroid[0], 1), round(m.centroid[1], 1)],
            }
            for m in measurements
        ]

        return DefectReport(
            timestamp      = time.time(),
            crack_count    = len(measurements),
            critical_count = sev_counts["CRITICAL"],
            moderate_count = sev_counts["MODERATE"],
            minor_count    = sev_counts["MINOR"],
            worst_severity = worst,
            max_width_mm   = max(m.width_mm  for m in measurements),
            max_length_mm  = max(m.length_mm for m in measurements),
            max_growth_pct = max(m.propagation_pct * 100 for m in measurements),
            cracks         = cracks_json,
            measurements   = measurements,   # raw objects for overlay rendering
        )