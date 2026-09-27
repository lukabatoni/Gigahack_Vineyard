# Vineyard AI Field Challenge — Siret3 (Deeptech GigaHack 2026)

End-to-end pipeline that turns the 311 Siret3 orthomosaic tiles into the scored
deliverables: CVAT annotations (rows, canopy, inter-row), per-block measurements,
and a closed walking route. All output geometry is **EPSG:32635** (UTM 35N, metres).

## Root deliverables

| File | What it is |
|------|------------|
| `route.geojson` | Closed inspector walking route (one LineString, EPSG:32635, starts + ends within 5 m of START `[629663.8, 5220195.3]`, `length_m` property). |
| `route_farmer.geojson` | Waste-only farmer route (web-display layer). |
| `measurements.csv` | Block count, row count, total row length, canopy area, inter-row area — by `vineyard_id` / `row_id`. |

`measurements.csv` in the repo root covers the **verified 9-tile demo region** around
the two ground-truth example tiles (`siret3_r006_c004`, `siret3_r021_c012`) and their
edge neighbours — the slice we validated against the organizer's reference annotations
(rows 24 vs GT 26, inter-row 26 vs GT 25 on r006_c004). To regenerate for any tile
set, see **Run** below.

## Requirements

- Python 3.9, macOS/Linux. Apple Silicon (MPS) or CPU both work.
- `pip install -r requirements.txt` (fully pinned). Key libs: `ultralytics==8.3.0`,
  `torch==2.8.0`, `rasterio==1.3.11`, `shapely==2.0.6`, `networkx==3.2.1`, `pyproj==3.6.1`.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Model weights

- **Rows model** (single-class `row`, YOLO11s-seg, negatives-augmented; md5 `0c713ac2`):
  committed at `weights/rows_best.pt`. `pipeline/rows_postproc.py` loads it via a
  repo-relative path (override with the `ROWS_WEIGHTS` env var).
- **Canopy / inter-row**: classical CV (ExG + watershed), no weights needed
  (`pipeline/segment_canopy.py`, `pipeline/interrow.py`).

## Run — tiles → deliverables

Tiles live under `01_tiles/` (organizer-supplied, not committed). From the repo root:

```bash
# 1. Detect rows + canopy + inter-row → annotations + measurements
#    (demo region: the 9 ground-truth-adjacent tiles)
python pipeline/run_pipeline.py \
  --tiles-list r006_c004,r005_c004,r007_c004,r006_c003,r021_c012,r020_c012,r022_c012,r021_c011,r021_c013 \
  --tag demo9
#    → pipeline/output/annotations_demo9.xml  +  pipeline/output/measurements_demo9.csv
cp pipeline/output/measurements_demo9.csv measurements.csv

# Whole site instead: drop --tiles-list to process all 311 tiles.
#   python pipeline/run_pipeline.py --tag all

# 2. Walking route (closed loop from START, EPSG:32635, with length_m)
python pipeline/route_planner.py            # → route.geojson + route_farmer.geojson

# 3. Reproject annotations to WGS84 GeoJSON for the web map
python pipeline/export_web_data.py \
  --annotations pipeline/output/annotations_demo9.xml \
  --tiles 01_tiles --out web/data
```

## Web interface

Static Leaflet map in `web/` reading GeoJSON from `web/data/`:

```bash
cd web && python -m http.server 8848   # open http://localhost:8848
```

Layers: canopy polygons, row polylines, inter-row areas, both routes, plus context
(passages / forbidden / start / study area). Base layers: OSM streets, Esri satellite,
and the drone orthomosaic pyramid (`web/data/imagery/{z}/{x}/{y}.png`) when built via
`pipeline/build_imagery_tiles.py`.

## Processing time & hardware

Measured on **Apple M1 Pro, 16 GB RAM** (PyTorch 2.8.0, MPS):

| Stage | Time |
|-------|------|
| Rows + canopy + inter-row per tile | ~4–6 s/tile (tiled 640 inference) |
| 9-tile demo region (end to end) | ~1 min |
| Route planner (passages graph @ 2 m) | ~13 s graph build + TSP |
| Full 311-tile run | ~30–45 min |

No paid APIs or hosted LLMs are used at runtime.

## Layout

```
pipeline/
  run_pipeline.py       orchestrator: tiles → annotations.xml + measurements.csv
  rows_postproc.py      YOLO row masks → centreline polylines (loads weights/rows_best.pt)
  assign_ids.py         global vineyard_id / row_id stitching in world space
  segment_canopy.py     classical per-plant canopy polygons (ExG + watershed)
  interrow.py           inter-row strips between adjacent rows − canopy
  cvat_writer.py        CVAT 1.1 annotations.xml
  measurements.py       per-block areas + row lengths (EPSG:32635)
  route_planner.py      walkable graph → closed TSP route.geojson
  export_web_data.py    CVAT XML → WGS84 GeoJSON for the web map
weights/rows_best.pt    trained rows model
web/                    Leaflet interactive map
02_route/ 05_examples/  organizer route files + example tiles
docs_state/             live build state (status, decisions, findings)
```

## Known scope

- Canopy / inter-row are classical CV (not a neural instance segmenter) — good for
  per-plant polygons, weaker on IoU than a trained model. Rows use the trained YOLO.
- Waste layer is intentionally empty: no waste model; both example tiles have zero
  waste in ground truth, so "none detected" is verified, not fabricated.
- `interrow_cover` class is a heuristic from ExG green fraction.
