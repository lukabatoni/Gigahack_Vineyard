"""
Resume the Riseholme YOLO11-seg run from its last checkpoint, capped at 40 epochs.

The original run (train_riseholme.py) targeted 60 epochs but was stopped at epoch 22.
We only want ~35-40 epochs to evaluate whether the model is good enough on the real
Sireț3 tiles before committing to a full run. Loading last.pt and setting epochs=40
makes Ultralytics continue and stop at epoch 40 (or earlier if patience triggers).

Weights land in the SAME dir: pipeline/runs/segment/riseholme/weights/best.pt
"""
from pathlib import Path
from ultralytics import YOLO

LAST = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/runs/segment/riseholme/weights/last.pt")
DATA = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/riseholme_yolo/data.yaml")
PROJECT = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/runs/segment")

def main():
    model = YOLO(str(LAST))
    model.train(
        data=str(DATA),
        epochs=40,           # continue from epoch 22 -> stop at 40
        imgsz=640,
        batch=2,
        device="mps",
        patience=15,
        project=str(PROJECT),
        name="riseholme",
        exist_ok=True,       # keep writing into the same run dir
        resume=False,        # NOT a raw resume-to-60; we re-target to 40 epochs
        plots=True,
        val=True,
    )
    print("Resume done. Best weights: pipeline/runs/segment/riseholme/weights/best.pt")

if __name__ == "__main__":
    main()
