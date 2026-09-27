"""
Add non-vineyard NEGATIVE patches to the rows_yolo dataset.

Why: the rows model was trained on 2 all-vineyard tiles (all-positive patches),
so it hallucinates rows on forest / ploughed field / grass / village (see
30_FINDINGS 2026-09-26). Feeding empty-label patches from clearly non-vineyard
challenge tiles teaches it what ISN'T a row, killing those false positives.

Slices each listed non-vineyard tile into PATCH x PATCH crops, writes the image
with an EMPTY label file (YOLO treats an empty .txt as a true negative). Appends
into the existing rows_yolo/{images,labels}/{train,val} — run build_rows_dataset.py
first (it creates the positives), then this.

The tiles below were hand-picked from a 25-tile contact sheet (2026-09-26): they
contain NO vineyard rows — only tree canopy, bare/ploughed soil, meadow, or roofs.
"""
from pathlib import Path

import numpy as np
import cv2
import rasterio

OUT = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/rows_yolo")
TILES_ROOT = Path("/Users/luka-sap/Desktop/Gigahack/01_tiles")

PATCH = 640
STRIDE = 512            # negatives don't need heavy overlap
VAL_FRACTION = 0.2
KEEP = 0.6             # keep a majority of negative patches (we want variety)

# Hand-picked non-vineyard tiles: forest/orchard, bare field/meadow, buildings.
NEG_STEMS = [
    "r016_c010", "r028_c017", "r022_c016",              # forest / orchard
    "r026_c031", "r027_c023", "r030_c019", "r030_c032",  # bare field / meadow
    "r032_c028", "r033_c028", "r034_c029", "r029_c024",
    "r017_c010", "r031_c029",                            # village / buildings
]


def read_rgb(tif):
    with rasterio.open(tif) as s:
        arr = np.transpose(s.read()[:3], (1, 2, 0))
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return arr


def main():
    rng = np.random.default_rng(7)
    for split in ("train", "val"):
        (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)

    added = 0
    for stem in NEG_STEMS:
        hits = list(TILES_ROOT.rglob(f"siret3_{stem}.tif"))
        if not hits:
            print(f"skip {stem}: not found")
            continue
        rgb = read_rgb(hits[0])
        h, w = rgb.shape[:2]
        for y0 in range(0, h - PATCH + 1, STRIDE):
            for x0 in range(0, w - PATCH + 1, STRIDE):
                if rng.random() > KEEP:
                    continue
                crop = rgb[y0:y0 + PATCH, x0:x0 + PATCH]
                # skip mostly-black edge crops (no-data outside imagery)
                if (crop.sum(axis=2) < 15).mean() > 0.5:
                    continue
                split = "val" if rng.random() < VAL_FRACTION else "train"
                name = f"neg_{stem}_x{x0}_y{y0}"
                cv2.imwrite(str(OUT / "images" / split / f"{name}.png"),
                            cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
                (OUT / "labels" / split / f"{name}.txt").write_text("")  # empty = negative
                added += 1

    ntr = len(list((OUT / "images" / "train").glob("*.png")))
    nva = len(list((OUT / "images" / "val").glob("*.png")))
    print(f"added {added} negative patches")
    print(f"dataset now: train={ntr}  val={nva}")


if __name__ == "__main__":
    main()
