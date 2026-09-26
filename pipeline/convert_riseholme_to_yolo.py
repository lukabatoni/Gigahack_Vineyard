"""
Convert the 3-season Riseholme COCO-segmentation datasets into a single
YOLO-seg dataset for ultralytics training.

Keeps only classes we care about, remapped:
    trunk    -> 0
    vine_row -> 1
(pole is dropped; vineyard has zero annotations.)

Output layout:
    pipeline/riseholme_yolo/
        images/{train,val}/*.jpg   (symlinks to originals)
        labels/{train,val}/*.txt   (YOLO-seg: cls x1 y1 x2 y2 ... normalized)
        data.yaml

COCO train+valid -> YOLO train ; COCO test -> YOLO val (held-out for our metric).
"""
import json
from pathlib import Path

SRC = Path("/Users/luka-sap/Desktop/Gigahack/riseholme-vineyard")
OUT = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/riseholme_yolo")

SEASONS = [
    "riseholme-august-2024-full-resolution.coco-segmentation",
    "riseholme-march-2025-full-resolution.coco-segmentation",
    "riseholme-july-2025-full-resolution.coco-segmentation",
]

# COCO category name -> new YOLO class id
KEEP = {"trunk": 0, "vine_row": 1}


def convert_split(coco_json: Path, img_src_dir: Path,
                  out_img_dir: Path, out_lbl_dir: Path) -> int:
    d = json.load(open(coco_json))
    cats = {c["id"]: c["name"] for c in d["categories"]}
    images = {im["id"]: im for im in d["images"]}

    # group annotations by image
    per_img = {}
    for a in d["annotations"]:
        name = cats[a["category_id"]]
        if name not in KEEP:
            continue
        seg = a.get("segmentation")
        if not (isinstance(seg, list) and seg and isinstance(seg[0], list)):
            continue  # skip RLE / empty
        per_img.setdefault(a["image_id"], []).append((KEEP[name], seg[0]))

    n_written = 0
    for img_id, anns in per_img.items():
        im = images[img_id]
        w, h = im["width"], im["height"]
        stem = Path(im["file_name"]).stem
        src_img = img_src_dir / im["file_name"]
        if not src_img.exists():
            continue

        # symlink image (avoid duplicating GBs)
        dst_img = out_img_dir / im["file_name"]
        if not dst_img.exists():
            dst_img.symlink_to(src_img)

        lines = []
        for cls, poly in anns:
            # normalize polygon coords to [0,1]
            coords = []
            for i in range(0, len(poly), 2):
                x = min(max(poly[i] / w, 0.0), 1.0)
                y = min(max(poly[i + 1] / h, 0.0), 1.0)
                coords.append(f"{x:.6f} {y:.6f}")
            if len(coords) < 3:
                continue
            lines.append(f"{cls} " + " ".join(coords))
        if not lines:
            continue
        (out_lbl_dir / f"{stem}.txt").write_text("\n".join(lines) + "\n")
        n_written += 1
    return n_written


def main():
    for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    train_n = val_n = 0
    for season in SEASONS:
        sroot = SRC / season
        # COCO train + valid -> YOLO train
        for split in ["train", "valid"]:
            cj = sroot / split / "_annotations.coco.json"
            if cj.exists():
                train_n += convert_split(cj, sroot / split,
                                          OUT / "images/train", OUT / "labels/train")
        # COCO test -> YOLO val
        cj = sroot / "test" / "_annotations.coco.json"
        if cj.exists():
            val_n += convert_split(cj, sroot / "test",
                                   OUT / "images/val", OUT / "labels/val")

    yaml = OUT / "data.yaml"
    yaml.write_text(
        f"path: {OUT}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: 2\n"
        f"names: ['trunk', 'vine_row']\n"
    )
    print(f"Converted. train imgs with labels: {train_n}, val imgs: {val_n}")
    print(f"data.yaml -> {yaml}")


if __name__ == "__main__":
    main()
