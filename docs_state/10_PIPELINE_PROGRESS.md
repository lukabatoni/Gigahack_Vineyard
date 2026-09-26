# 10 — PIPELINE PROGRESS (per-component build status)

> One row per pipeline component. Update the **Status** and **Notes** the moment a
> component changes. Statuses: `TODO` · `IN PROGRESS` · `BASELINE DONE` · `DONE`.

| # | Component | Status | File(s) | Notes |
|---|-----------|--------|---------|-------|
| 1 | Env + deps | DONE | `venv/`, `requirements.txt` | Python 3.9.6, all deps pinned. |
| 2 | Explore tiles + parse annotations | DONE | `pipeline/explore_tiles.py` | Confirmed 311 tiles, EPSG:32635, 2.5cm/px, 2048². Parses CVAT XML. |
| 3 | Canopy segmentation (classical CV) | BASELINE DONE (weak) | `pipeline/segment_canopy.py` | ExG + adaptive threshold + watershed. Recall too low on dormant vines. Being replaced/augmented by NN. |
| 3b | Canopy segmentation (neural net) | IN PROGRESS | `pipeline/segment_canopy_sam.py`, `pipeline/eval_canopy.py`, `pipeline/train_riseholme.py` | SAM+ExG baseline F1 0.228 (insufficient). Now: YOLO11-seg training on Riseholme trunk+vine_row (bg run). Canopy = trunk-detector → SAM prompt. **Mandatory deliverable.** |
| 4 | Row extraction (polylines) | BASELINE DONE | `pipeline/rows_postproc.py`, `pipeline/convert_riseholme_to_yolo.py` | vine_row masks → polylines. Method: per-tile DOMINANT ANGLE (structure tensor on mask union) + perpendicular-offset clustering → one polyline per row. Per-mask PCA FAILED (single masks too round to carry direction). E2E verified on 2 example tiles: 14 rows, 370.6m, CVAT round-trips. Coverage limited by epoch-22 model recall (sparse/dormant rows unmasked); re-run when 40-epoch model lands. |
| 5 | Inter-row areas + `interrow_cover` | TODO | — | Derived from rows + canopy edges. |
| 6 | Waste detection (bboxes) | TODO (plan ready) | — | See "Task 6 plan" below. YOLO detector fine-tuned on DroneWaste; precision-biased; IoU≥0.3 scoring. |
| 7 | Global ID assignment (`vineyard_id`,`row_id`) | CODE DONE (blocked on model recall) | `pipeline/assign_ids.py` | Stitch in WORLD space (grid abuts exactly: 51.2m tiles, verified). Union-find: blocks = segments within 5m (docs: <5m gap = same block, road separates); rows = parallel+collinear within 4m. Writes ids back into row dicts. **Correct algorithm, but block count inflated on the epoch-22 model** — missing row detections open false >5m gaps that split one block into several. Do NOT raise the 5m threshold (would merge real road-separated blocks). Re-verify on the 40-epoch model. |
| 8 | CVAT XML generator | BASELINE DONE | `pipeline/cvat_writer.py` | Emits CVAT 1.1 with mandatory label block. Round-trip validated: reference XML → emit → reparse preserves all counts exactly (vineyard 399/251, row 25/26, interrow 24/25). Ready for model output. |
| 9 | Route planner (TSP) | IN PROGRESS (mock engine done) | `pipeline/route_planner.py` | Grid nav-graph over walkable (passages⋃interrow−forbidden) → networkx shortest paths → NN+2-opt TSP → both routes, return to START. Verified on MOCK targets: blue 3459m / red 2951m, both 100% inside, ends within 5m (PASS). Emits `route.geojson`(blue,scored)+`route_farmer.geojson`(red) at repo root w/ `length_m`, EPSG:32635. **Pending:** swap mock interrow/targets for Lane A `interrow.geojson`+disrupted-row/waste targets (via `--interrow --targets`, no code change). |
| 10 | Measurements module | BASELINE DONE | `pipeline/measurements.py` | Pixel→EPSG:32635 via tile transform; canopy=union per block, interrow=sum, row length=sum. Validated on reference: 2 blocks, 51 rows, canopy 536m², interrow 4064m², rows 1942m — all physically sane. Ready for model output. |
| 11 | Web interface | IN PROGRESS (built, data-verified) | `web/{index.html,style.css,app.js}`, `web/data/*`, `pipeline/export_web_data.py` | Plain HTML/CSS/JS + Leaflet, Esri satellite basemap. All layers + toggles + filters + popups + measurements panel. Exporter turns CVAT XML + tiles → WGS84 GeoJSON + measurements.csv. Verified on 2 example tiles (canopy 650/rows 51/interrow 49). Pending: deploy + real model data. **See `docs_state/40_INTERFACE.md` for full handoff.** |
| 12 | Upload to Marcaj + publish | TODO | — | 5 ZIPs ≤90MB, confirm 311 files, publish ONCE (~Sat). |
| 13 | Manual correction + submit jobs | TODO | — | 63 jobs of 5 tiles; submit all before deadline. |
| 14 | README + final recompute + repo | TODO | — | Install/run steps, weights location, perf, hardware. |
| 15 | Orchestrator (all-311 driver) | BASELINE DONE | `pipeline/run_pipeline.py` | Discovers 311 tiles across 5 part-dirs → model → objects_by_tile → annotations.xml + measurements.csv. `--limit N` dry run. Verified on 5-tile sample: 17 rows, no crashes, ~1.7s/tile (→ full run ~9min). Currently rows-only; canopy/interrow/waste plug in as A3/A4/Lane-B land. |

---

## Artifacts produced so far

- `pipeline/output/*_annotated.png` — reference annotations drawn on example tiles.
- `pipeline/output/*_segmentation.png` — classical-CV canopy output (RGB | mask | polys).
- `pipeline/output/proof_*.png` — iterative debugging of the color/threshold approach.

---

## PARALLEL-WORK TASK PLANS (for teammates)

> All facts below are verified against `03_docs/*.pdf`. See `20_DECISIONS.md` for the
> quoted sources. Three tasks can be built NOW, in parallel, independent of the NN training.

### Task 6 plan — Waste detection (bboxes)
**Deliverable:** per-tile `waste` boxes `{xtl,ytl,xbr,ybr,vineyard_id}` → into `cvat_writer.py`
(already supports waste) + boxes become route targets.
**Model:** fine-tune a YOLO detector (yolo11n/s detect head) on **DroneWaste** (open, aerial,
CC-verify). SEPARATE training run from the canopy/row seg model.
**Pipeline:**
1. Tile 2048² at imgsz=640 (or 1024 if mem OK) with overlap so edge items aren't cut. Detect per tile.
2. NMS dedupe. **Precision-biased threshold** (docs: false box costs = a miss). Tune conf on the
   2 example tiles to maximise F1 at IoU≥0.3.
3. `vineyard_id`: box centroid inside a block → that id; else nearest block within 10 m (metres,
   EPSG:32635); else empty. (Needs canopy/block polygons — can stub empty until Task 7 exists.)
4. Reuse the `eval_canopy.py` greedy-match pattern but at IoU≥0.3 for a waste-F1 scorer.
**Watch:** IS-waste vs NOT-waste lists (20_DECISIONS). Don't box vine tubes/stakes/hoses/soil.

### Task 9 plan — Route planner (TWO routes)
**Deliverable:** `route.geojson` (ONE LineString, EPSG:32635, blue inspector route, starts+ends at
START within 5 m, `length_m` prop) at repo ROOT. Also `route_farmer.geojson` (red, waste-only) for web.
**Inputs / data flow:**
- Targets (a) waste box centroids → EPSG:32635 points (Task 6).
- Targets (b) inspection points = rows with `row_structure=disrupted` → a target at each gap,
  linked to row_id/vineyard_id (Task 4 + Task 5). NOT written to Marcaj — app output only.
- Walkable surface = `passages.geojson` (MultiPolygon) ⋃ interrow_area polygons (Task 5, reprojected)
  MINUS `forbidden.geojson` and canopy polygons.
**Solver:**
1. Build a nav graph over the walkable surface (medial-axis skeleton or grid; networkx 3.2.1).
2. Pairwise shortest paths START↔target, target↔target — EACH path constrained inside the surface
   (a straight segment through a canopy/forbidden zone = instant 0).
3. TSP over targets (nearest-neighbour + 2-opt), return to START. Stitch ordered paths → 1 LineString.
4. Validate gates: >98% length inside walkable; endpoints within 5 m of START; set `length_m`.
**Two routes:** same graph. Blue targets = waste ∪ inspection points (→ `route.geojson`).
Red targets = waste only (→ `route_farmer.geojson`). Two independent TSP solves.
**START:** `[629504.7, 5220250.75]` EPSG:32635, on tile siret3_r018_c010.tif.

### Task 11 plan — Web interface
**Deliverable:** working interactive map (deploy link in README) showing everything.
**Stack:** Leaflet or MapLibre. Geometry is EPSG:32635 → reproject to WGS84 for display (or CRS-aware).
Basemap = tiles, or source orthomosaic as image overlay.
**Layers (toggleable):** canopy polygons, interrow_area polygons, row polylines, waste boxes,
**blue inspector route**, **red farmer route**, START marker, passages/forbidden (faint context).
**Panels (from `measurements.csv` + route geojsons):** block count, row count, per-row + total row
length (m), canopy area (m² + ha), interrow area (m² + ha), blue & red route lengths.
**Interaction:** filter by vineyard_id/row_id; click object → popup with IDs + attributes.
**Data contract (backend serves static files only):** GeoJSON FeatureCollections
(canopy/row/interrow/waste) + `measurements.csv` + `route.geojson` + `route_farmer.geojson`.

