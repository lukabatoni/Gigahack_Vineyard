"""
Build a YOLO11-seg dataset for the `row` class from the 2 fully-annotated
example tiles.

Why: the Riseholme-trained model fails on the Moldova domain (1/25 rows). The
example tiles are perfect ground truth on our exact imagery. Rows are visually
regular parallel stripes, so fine-tuning on them (sliced + augmented) is the
highest-leverage move.

Pipeline:
  1. Parse example annotations.xml -> per-tile row polylines (pixel coords).
  2. Buffer each polyline into a thin stripe polygon (rows are ~2 m apart;
     half-width ~15 px = 0.75 m keeps stripes separate).
  3. Slice each 2048px tile into overlapping PATCH x PATCH crops. For each patch,
     clip stripe polygons to the patch, emit YOLO-seg label rows (normalized
     polygon coords) + the image crop. Patches with no row are kept sparsely as
     negatives.
  4. Train/val split by patch; write data.yaml.

Output: pipeline/rows_yolo/{images,labels}/{train,val} + data.yaml
Single class: {0: row}.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import cv2
import rasterio
from shapely.geometry import LineString, box
from shapely.affinity import translate

EX_DIR = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat")
XML = EX_DIR / "annotations.xml"
IMG_DIR = EX_DIR / "images"
OUT = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/rows_yolo")

PATCH = 640
STRIDE = 480            # ~25% overlap so rows near patch edges aren't lost
HALF_W = 15.0          # stripe half-width in px (~0.75 m); rows ~2 m apart
MIN_AREA_PX = 200      # drop tiny clipped slivers
VAL_FRACTION = 0.2
NEG_KEEP = 0.15        # keep a fraction of empty patches as negatives


def parse_rows(xml_path):
    """{tile_name: [LineString(px), ...]} for the row polylines."""
    root = ET.parse(xml_path).getroot()
    out = {}
    for img in root.findall("image"):
        rows = []
        for pl in img.findall("polyline"):
            if pl.get("label") != "row":
                continue
            pts = [tuple(map(float, p.split(","))) for p in pl.get("points").split(";")]
            if len(pts) >= 2:
                rows.append(LineString(pts))
        out[img.get("name")] = rows
    return out


def read_rgb(tif):
    with rasterio.open(tif) as s:
        arr = np.transpose(s.read()[:3], (1, 2, 0))
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return arr


def stripe_polys(lines):
    """Buffer each centreline into a stripe polygon."""
    return [ln.buffer(HALF_W, cap_style=2, join_style=2) for ln in lines]


def emit_patch(rgb, polys, x0, y0, img_out, lbl_out, stem):
    """Write one patch image + its YOLO-seg label file. Returns True if it has
    any row (positive patch)."""
    h, w = rgb.shape[:2]
    x1, y1 = min(x0 + PATCH, w), min(y0 + PATCH, h)
    crop = rgb[y0:y1, x0:x1]
    if crop.shape[0] < PATCH or crop.shape[1] < PATCH:
        pad = np.zeros((PATCH, PATCH, 3), np.uint8)
        pad[:crop.shape[0], :crop.shape[1]] = crop
        crop = pad
    patch_box = box(x0, y0, x0 + PATCH, y0 + PATCH)

    label_lines = []
    for poly in polys:
        inter = poly.intersection(patch_box)
        if inter.is_empty or inter.area < MIN_AREA_PX:
            continue
        parts = list(inter.geoms) if inter.geom_type == "MultiPolygon" else [inter]
        for part in parts:
            if part.area < MIN_AREA_PX:
                continue
            local = translate(part, xoff=-x0, yoff=-y0)
            xs, ys = local.exterior.coords.xy
            coords = np.array(list(zip(xs, ys)))[:-1]        # drop closing dup
            coords[:, 0] = np.clip(coords[:, 0], 0, PATCH) / PATCH
            coords[:, 1] = np.clip(coords[:, 1], 0, PATCH) / PATCH
            flat = " ".join(f"{v:.6f}" for v in coords.flatten())
            label_lines.append(f"0 {flat}")

    name = f"{stem}_x{x0}_y{y0}"
    has_row = bool(label_lines)
    cv2.imwrite(str(img_out / f"{name}.png"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    (lbl_out / f"{name}.txt").write_text("\n".join(label_lines))
    return has_row


def main():
    rng = np.random.default_rng(42)
    rows_by_tile = parse_rows(XML)

    for split in ("train", "val"):
        (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)

    pos = neg = 0
    for tile_name, lines in rows_by_tile.items():
        tif = IMG_DIR / tile_name
        if not tif.exists():
            print(f"skip {tile_name}: not found")
            continue
        rgb = read_rgb(tif)
        polys = stripe_polys(lines)
        h, w = rgb.shape[:2]
        stem = Path(tile_name).stem

        patches = []
        for y0 in range(0, h, STRIDE):
            for x0 in range(0, w, STRIDE):
                patches.append((x0, y0))
        for (x0, y0) in patches:
            split = "val" if rng.random() < VAL_FRACTION else "train"
            has_row = emit_patch(rgb, polys, x0, y0,
                                 OUT / "images" / split, OUT / "labels" / split, stem)
            if has_row:
                pos += 1
            else:
                neg += 1
                # optionally drop most negatives to keep the set row-focused
                if rng.random() > NEG_KEEP:
                    name = f"{stem}_x{x0}_y{y0}"
                    (OUT / "images" / split / f"{name}.png").unlink(missing_ok=True)
                    (OUT / "labels" / split / f"{name}.txt").unlink(missing_ok=True)

    yaml = OUT / "data.yaml"
    yaml.write_text(
        f"path: {OUT}\n"
        "train: images/train\n"
        "val: images/val\n"
        "nc: 1\n"
        "names: ['row']\n"
    )
    # report kept counts
    ntr = len(list((OUT / "images" / "train").glob("*.png")))
    nva = len(list((OUT / "images" / "val").glob("*.png")))
    print(f"positive patches={pos}  negative(before prune)={neg}")
    print(f"kept: train={ntr}  val={nva}")
    print(f"data.yaml -> {yaml}")


if __name__ == "__main__":
    main()
