"""
Fine-tune YOLO11-seg on the converted Riseholme dataset (trunk + vine_row).
Produces:
  - a vine_row detector  -> Task 4 (rows)
  - a trunk detector     -> per-plant seeder for canopy-via-SAM (Task 3)

Runs on Apple GPU (MPS). Weights land in pipeline/runs/segment/riseholme/weights/best.pt
This is the mandatory neural-network deliverable.
"""
from pathlib import Path
from ultralytics import YOLO

DATA = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/riseholme_yolo/data.yaml")
PROJECT = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/runs/segment")

def main():
    model = YOLO("yolo11n-seg.pt")  # pretrained COCO weights as starting point
    model.train(
        data=str(DATA),
        epochs=60,
        imgsz=640,           # low-mem setting: safe on MPS, ~2-3h total run
        batch=2,             # 4056x3040 originals downscaled to 640; small batch for MPS memory
        device="mps",
        patience=15,         # early stop if no val improvement
        project=str(PROJECT),
        name="riseholme",
        exist_ok=True,
        plots=True,
        val=True,
    )
    print("Training done. Best weights: pipeline/runs/segment/riseholme/weights/best.pt")

if __name__ == "__main__":
    main()
