# =============================================================================
# train_viper.py — VIPER Crack Detection Model Training
# =============================================================================

import os
import sys
import re
from pathlib import Path

import torch
from ultralytics import YOLO


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DATASETS_DIR = SCRIPT_DIR / "data" / "training" / "datasets"
DATA_YAML = DATASETS_DIR / "data.yaml"
RUNS_DIR = SCRIPT_DIR / "runs"


# -----------------------------------------------------------------------------
# Training configuration
# -----------------------------------------------------------------------------

CFG = {
    "base_model": "yolov8n.pt",
    "run_name": "viper_crack_v1",

    "imgsz": 640,
    "epochs": 100,
    "patience": 15,

    "batch": 8,
    "workers": 4,

    "amp": True,
    "cache": "disk",

    "optimizer": "AdamW",
    "lr0": 0.001,
    "lrf": 0.01,

    "degrees": 10.0,
    "flipud": 0.3,
    "fliplr": 0.5,
    "mosaic": 1.0,
    "mixup": 0.1,
    "hsv_s": 0.4,
    "hsv_v": 0.4,

    "conf": 0.35,
    "iou": 0.50,

    "save": True,
    "save_period": 10,
}


# -----------------------------------------------------------------------------
# Fix Roboflow segmentation labels automatically
# -----------------------------------------------------------------------------

def fix_dataset_labels():
    print("\nChecking dataset labels...")

    label_dirs = [
        DATASETS_DIR / "train" / "labels",
        DATASETS_DIR / "valid" / "labels",
        DATASETS_DIR / "test" / "labels",
    ]

    fixed = 0

    for lbl_dir in label_dirs:
        if not lbl_dir.exists():
            continue

        for file in lbl_dir.glob("*.txt"):

            lines = file.read_text().strip().splitlines()
            cleaned = []

            for line in lines:
                parts = re.split(r"\s+", line.strip())

                if len(parts) >= 5:
                    cleaned.append(" ".join(parts[:5]))

                    if len(parts) > 5:
                        fixed += 1

            file.write_text("\n".join(cleaned))

    print(f"✓ Fixed {fixed} segmentation labels")


# -----------------------------------------------------------------------------
# Remove YOLO cache files
# -----------------------------------------------------------------------------

def clear_cache():
    removed = 0

    for cache in DATASETS_DIR.rglob("*.cache"):
        cache.unlink()
        removed += 1

    if removed:
        print(f"✓ Cleared {removed} dataset cache files")


# -----------------------------------------------------------------------------
# Detect number of classes automatically
# -----------------------------------------------------------------------------

def detect_classes():

    label_dir = DATASETS_DIR / "train" / "labels"

    classes = set()

    for txt in label_dir.glob("*.txt"):

        for line in txt.read_text().splitlines():

            if line.strip() == "":
                continue

            cls = int(line.split()[0])
            classes.add(cls)

    nc = max(classes) + 1 if classes else 1

    print(f"Detected {nc} class(es) from labels")

    return nc


# -----------------------------------------------------------------------------
# Environment check
# -----------------------------------------------------------------------------

def check_environment():

    print("=" * 60)
    print("VIPER Crack Detection Training")
    print("=" * 60)

    if torch.cuda.is_available():

        gpu = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory / 1e9

        print(f"GPU detected: {gpu}")
        print(f"VRAM: {vram:.1f} GB")

        device = 0

    else:

        print("⚠ No CUDA GPU detected. Training will run on CPU.")

        device = "cpu"

    print(f"Python: {sys.version.split()[0]}")
    print(f"Torch : {torch.__version__}")

    if not DATASETS_DIR.exists():
        print("Dataset folder not found.")
        sys.exit(1)

    if not DATA_YAML.exists():
        print("data.yaml missing.")
        sys.exit(1)

    print(f"Dataset directory: {DATASETS_DIR}")

    return device


# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------

def train(device):

    fix_dataset_labels()
    clear_cache()

    nc = detect_classes()

    project_dir = str(RUNS_DIR / "detect")

    print("\nTraining configuration")
    print("----------------------")
    print(f"Base model : {CFG['base_model']}")
    print(f"Run name   : {CFG['run_name']}")
    print(f"Epochs     : {CFG['epochs']}")
    print(f"Batch      : {CFG['batch']}")
    print()

    model = YOLO(CFG["base_model"])

    results = model.train(
        data=str(DATA_YAML),

        epochs=CFG["epochs"],
        imgsz=CFG["imgsz"],
        batch=CFG["batch"],

        name=CFG["run_name"],
        project=project_dir,

        device=device,
        workers=CFG["workers"],
        cache=CFG["cache"],

        amp=CFG["amp"],
        patience=CFG["patience"],

        optimizer=CFG["optimizer"],
        lr0=CFG["lr0"],
        lrf=CFG["lrf"],

        degrees=CFG["degrees"],
        flipud=CFG["flipud"],
        fliplr=CFG["fliplr"],
        mosaic=CFG["mosaic"],
        mixup=CFG["mixup"],
        hsv_s=CFG["hsv_s"],
        hsv_v=CFG["hsv_v"],

        save=CFG["save"],
        save_period=CFG["save_period"],

        exist_ok=True,
        verbose=True,
    )

    return results


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

def validate(device):

    best = RUNS_DIR / "detect" / CFG["run_name"] / "weights" / "best.pt"

    if not best.exists():
        print("best.pt not found")
        return

    print("\nRunning validation...")

    model = YOLO(str(best))

    metrics = model.val(
        data=str(DATA_YAML),
        imgsz=CFG["imgsz"],
        device=device,
        conf=CFG["conf"],
        iou=CFG["iou"],
        verbose=False,
    )

    print("\nResults")
    print("-------")
    print(f"mAP50     : {metrics.box.map50:.4f}")
    print(f"mAP50-95  : {metrics.box.map:.4f}")
    print(f"Precision : {metrics.box.mp:.4f}")
    print(f"Recall    : {metrics.box.mr:.4f}")


# -----------------------------------------------------------------------------
# Deploy instructions
# -----------------------------------------------------------------------------

def print_deploy():

    best = RUNS_DIR / "detect" / CFG["run_name"] / "weights" / "best.pt"

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)

    print(f"\nBest model:")
    print(best)

    print("\nTo use in ai_server.py run:")

    print(f"\nset VIPER_MODEL_PATH={best}")
    print("set VIPER_CONFIDENCE=0.35")
    print("python ai_server.py")

    print("\n" + "=" * 60)


# -----------------------------------------------------------------------------

if __name__ == "__main__":

    device = check_environment()

    train(device)

    validate(device)

    print_deploy()