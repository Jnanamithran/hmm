# =============================================================================
# detector/model.py — YOLOv8 Object Detector
# =============================================================================
# Why YOLOv8 nano over MobileNet SSD?
#   - YOLOv8n (ultralytics) achieves ~37 mAP on COCO vs ~23 mAP for MobileNet SSD.
#   - The 'ultralytics' package unifies model loading, inference, and result
#     parsing into a single clean API — far less boilerplate.
#   - YOLOv8n runs at 80–120 FPS on a modern laptop CPU and much faster on GPU.
#   - Auto-downloads weights (~6 MB) on first run — no manual setup.
#   - Detects 80 COCO classes out-of-the-box.
#
# Design:
#   - detect(frame) returns (annotated_frame, detections_list)
#   - Bounding boxes, labels, and confidence scores are drawn directly
#     onto the frame using OpenCV, matching the exact pixel coordinates
#     from YOLO's output.
#   - A seeded color palette ensures consistent class colors across frames.
# =============================================================================

import logging
import torch

# ---------------------------------------------------------------------------
# PyTorch 2.6 compatibility fix
# In PyTorch 2.6, torch.load() switched weights_only=True by default, which
# blocks ultralytics' custom classes (DetectionModel, etc.) from loading.
# We allowlist the required ultralytics globals so torch.load() accepts them.
# This is safe — we trust the official ultralytics weights.
# ---------------------------------------------------------------------------
try:
    import ultralytics.nn.tasks as _ult_tasks
    _safe_classes = [
        _ult_tasks.DetectionModel,
        _ult_tasks.SegmentationModel,
        _ult_tasks.PoseModel,
        _ult_tasks.ClassificationModel,
    ]
    torch.serialization.add_safe_globals(_safe_classes)
except (ImportError, AttributeError):
    pass  # older torch / older ultralytics — no patch needed
import numpy as np
import cv2
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class YOLODetector:
    """
    YOLOv8n real-time object detector.

    Parameters
    ----------
    model_path : str
        Path to .pt weights file, or a model name like 'yolov8n.pt'
        (auto-downloaded from Ultralytics CDN on first call).
    confidence : float
        Minimum confidence threshold (0.0–1.0).
    device : str
        'cpu', 'cuda', or 'mps' — auto-detected if None.
    """

    def __init__(self, model_path='yolov8n.pt', confidence=0.40, device=None):
        logger.info(f"Loading YOLO model: {model_path}")
        self.model      = YOLO(model_path)
        self.confidence = confidence
        self.device     = device  # None = Ultralytics auto-selects

        self.class_names = self.model.names   # dict: {0: 'person', 1: 'bicycle', ...}

        # Seeded palette — same class always gets same color
        rng = np.random.default_rng(seed=42)
        self._palette = rng.integers(80, 230, size=(len(self.class_names), 3)).tolist()

        logger.info(f"Model loaded — {len(self.class_names)} classes, "
                    f"confidence threshold: {confidence}")

    # ------------------------------------------------------------------
    # Core inference
    # ------------------------------------------------------------------

    def detect(self, frame: np.ndarray):
        """
        Run inference on a single BGR frame.

        Returns
        -------
        annotated_frame : np.ndarray
            BGR frame with bounding boxes + labels drawn.
        detections : list[dict]
            [{'label': str, 'confidence': float, 'bbox': [x1,y1,x2,y2]}, ...]
        """
        results = self.model(
            frame,
            conf=self.confidence,
            verbose=False,
            device=self.device,
        )[0]

        annotated = frame.copy()
        detections = []

        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            cls_id = int(box.cls[0])
            conf   = float(box.conf[0])
            label  = self.class_names.get(cls_id, f'class_{cls_id}')
            color  = tuple(self._palette[cls_id % len(self._palette)])

            # Bounding box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            # Label chip
            text = f"{label}  {conf:.2f}"
            (tw, th), baseline = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
            )
            chip_y1 = max(y1 - th - baseline - 6, 0)
            chip_y2 = max(y1, th + baseline + 6)
            cv2.rectangle(annotated, (x1, chip_y1), (x1 + tw + 6, chip_y2), color, -1)
            cv2.putText(
                annotated, text,
                (x1 + 3, chip_y2 - baseline - 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (255, 255, 255), 1, cv2.LINE_AA,
            )

            detections.append({
                'label':      label,
                'confidence': round(conf, 3),
                'bbox':       [x1, y1, x2, y2],
                'cls_id':     cls_id,
            })

        return annotated, detections

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def warmup(self):
        """Run one dummy inference to pre-load model into memory."""
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        self.detect(dummy)
        logger.info("YOLO model warmed up")
