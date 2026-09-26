# 30 — FINDINGS & GOTCHAS (data facts, pitfalls, hard-won knowledge)

> Anything we learned about the data or the tooling that a fresh chat would
> otherwise have to rediscover the hard way. Append freely.

---

## Riseholme dataset(s) (downloaded 2026-09-26)

### Dataset A — Kaggle `jondave/...` (YOLOv11-seg), 8.63 GB
- Path: `~/.cache/kagglehub/datasets/jondave/riseholme-vineyard-uav-rgb-segmentation-dataset/versions/1/vineyard_segmentation_paper.yolov11`
- License CC BY 4.0. Classes `['pole','trunk','vine_row']` (nc=3). NO canopy class.
- Splits train 598 / valid 87 / test 170.

### Dataset B — `riseholme-vineyard/` in project root (COCO-seg), 3 seasons
- Paths: `riseholme-vineyard/riseholme-{august-2024,march-2025,july-2025}-full-resolution.coco-segmentation/{train,valid,test}/_annotations.coco.json`
- License CC BY 4.0 (Roboflow export). ~285 imgs/season, 4056×3040 px.
- Categories in schema: `{0:vineyard, 1:pole, 2:trunk, 3:vine_row}`.
- **BUT `vineyard` (canopy) has ZERO annotations in every split/season.** Nobody labeled it.
- Grand totals across all seasons+splits: pole 12639, trunk 22615, vine_row 4961, **vineyard 0**.
- All polygons are 4–7 points = coarse box-like markers, NOT fine leaf outlines.
- 3 seasons matter: March 2025 = dormant/bare vines (the case that broke color CV),
  Aug+Jul = full leaf. Training across all 3 should fix the dormant-vine recall collapse.

### KEY CONCLUSION for canopy (Task 3)
- **No available Riseholme dataset contains canopy leaf-outline training data.** The
  `vineyard` class is empty. So we CANNOT directly fine-tune a canopy-polygon segmenter.
- What we DO have: `trunk` (22k, one-per-plant location) + `vine_row` (5k, = our rows).
- **Canopy plan = hybrid:** train YOLO on `trunk` (pixel-based per-plant detector, works
  on dormant vines thanks to March data) → feed each trunk point as a SAM prompt → SAM
  grows the leaf-canopy outline. This replaces the failed ExG prompt generator.
- **Rows (Task 4): directly trainable** on `vine_row` (~5k labels, 3 seasons).

## Data facts (verified)
- 311 tiles total, grid r005–r039, c000–c033, split across 5 `01_tiles/` parts.
- Each tile: 2048×2048 px GeoTIFF, 2.5 cm/px → 51.2 m footprint, EPSG:32635.
- Source orthomosaic (`04_source/`) is EPSG:4326 — reproject to 32635 before use.
- Pixel → metre: multiply by 0.025.
- Reference example tiles: `siret3_r006_c004.tif`, `siret3_r021_c012.tif`
  (in `05_examples/siret3_examples_cvat/images/`, with `annotations.xml`). NOT scored.

## Annotation-format facts
- CVAT for Images 1.1. Coords in pixels, (0,0) = top-left.
- Labels: `vineyard`(polygon), `waste`(rectangle), `row`(polyline), `interrow_area`(polygon).
- `parse_annotations()` in `explore_tiles.py` returns
  `{filename: {width, height, objects: {vineyard, row, interrow_area, waste}}}`.
- Points format in XML: `'x1,y1;x2,y2;...'`. Waste stored as `xtl,ytl,xbr,ybr`.

## Scoring gotchas
- Canopy 25% = 0.6×class-IoU + 0.4×individual-canopy-F1 (match at IoU≥0.5).
- **Hidden scoring subset INCLUDES tiles with NO vineyards.** False canopies on those
  are penalized by −0.5 × share of tile covered. → precision matters, don't over-detect.
- Route: >2% outside passable areas OR not returning to START within 5 m → route score 0.
- Attributes must be EXACT lowercase strings (`regular`, `bare_soil`, etc.).

## Reference-canopy appearance (why classical CV struggled)
- Reference `vineyard` canopy pixels have hue ~20–39 (yellow-olive), NOT pure green.
- Original HSV 30–90 hue window cut most of them off → low recall.
- Dormant/yellow-brown vines are hard to separate from brown soil at 2.5cm/px by color.
- This is the core reason we need a NN, not just an index threshold.

## Environment gotchas
- Python is 3.9.6 → cannot use `str | Path` union syntax; use `typing.Union`.
- `networkx==3.3` needs Python ≥3.10 → we pinned `networkx==3.2.1`.
- Trees/large bushes get picked up as canopy by color; filter contours > MAX_AREA_PX
  (measured: a tree ≈ 750 m² vs a vine canopy max ≈ 10 m²).

## Golden rules that bite (from CLAUDE.md, worth repeating)
- One canopy = ONE plant, never one polygon over a whole row.
- Grapevines only — fruit trees, shrubs, weeds, grass are NOT `vineyard`.
- IDs survive tile edges: same block → same `vineyard_id` everywhere; same row → same
  `row_id`. Assign globally BEFORE cutting per tile.
- Every tile gets an answer (annotate or "No objects in this frame"). Blank = blocked job.
