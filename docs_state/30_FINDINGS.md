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

## Route planner (Task 9) findings
- START `[629504.7, 5220250.75]` EPSG:32635 lies INSIDE `passages.geojson` (dist 0).
- `passages` = 4.0 ha of thin roads spanning ~1.7 km; `forbidden` = 74.5 ha.
- Road-only walkable → routes back-and-forth heavily (mock blue 1360 pts). Real
  `interrow.geojson` (2D walkable fields, Lane A A4) will make routes far more efficient.
- Measuring "inside %" via a single `line.intersection(walkable).length` UNDER-reports
  when the route reuses a corridor (GEOS merges overlaps). Measure PER SEGMENT instead.
- `shapely.contains_xy` / `shapely.covers` (shapely 2.0) are vectorised → whole-area
  grid graph builds in seconds; no need to window the area.

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

---

## Moldova rows model — trained 2026-09-26 (Colab T4)

- Trained YOLO11s-seg single-class {0: row} on the 2 example tiles (sliced to
  640px patches, stripe-buffered polylines). Metrics on val patches near-perfect
  (mAP50 mask 0.979) — but val patches came from the SAME 2 source tiles.
- Weights: `pipeline/runs/segment/riseholme/weights/best.pt` (single-class 'row').
  Old Riseholme 2-class weights backed up as `best_riseholme_backup.pt`.
- Inference path: TILED (auto when names=={'row'}). 2048 tile -> 640 patches ->
  composite mask union -> directional close (bridge gaps) -> connected components
  -> per-component PCA centreline -> endpoint-gap collinear merge.
- **On vineyard example tiles it is EXCELLENT:** every row traced down its centre.
  Counts: r006_c004 = 26 vs ref 26 (0% err); r021_c012 = 30 vs ref 25 (20% err,
  a few rows still split by >90px gaps).
- **CRITICAL GOTCHA — false positives on non-vineyard tiles.** Trained on 2
  all-vineyard tiles (all-positive patches), the model has never seen forest /
  ploughed field / grass / village, and HALLUCINATES rows on any parallel texture
  (tree canopy, soil furrows, grass). Unseen tile r021_c010 (forest+track) -> 92
  spurious short fragments; r029_c025 (bare field+meadow) -> 65. Many of the 311
  tiles are non-vineyard, so raw inference will massively inflate row count and
  hurt axis F1. NEEDS: negative training patches (retrain) and/or a geometric
  post-filter (min length + parallelism to dominant angle) to suppress junk.
- Perf: ~3-4 s/tile on Mac (MPS/CPU), 16 patches/tile. 311 tiles ~ 15-20 min.

### UPDATE 2026-09-27 — false positives fixed by geometric filter
The non-vineyard FP problem (above) is resolved by `_filter_rows()` in
rows_postproc.py (length + parallelism-to-dominant-angle + straightness, with a
"<6 rows => emit none" guard). Retraining with negatives did NOT help (mosaic
diluted the signal). See 20_DECISIONS 2026-09-27. Residual: straight fence/track
lines on ambiguous field-edge tiles can survive as a few spurious rows — minor.
