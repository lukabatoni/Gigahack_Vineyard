# PROBLEM STATEMENT — Vineyard AI Field Challenge (Marcaj / GigaHack 2026)

> Conceptual plan for a **fresh, end-to-end pipeline**. This is the design doc: read it,
> agree on the shape, then we implement. It captures WHAT we're building, in WHAT priority
> order (driven by the scoring weights), and WHICH existing assets we carry over.
>
> Fixed rules live in `CLAUDE.md`. This file is the *plan*.

---

## 1. The problem in one paragraph

We are given **311 georeferenced GeoTIFF tiles** (2048×2048 px, 2.5 cm/px, 51.2 m each,
EPSG:32635) that together form one vineyard in Moldova. We must build a program that runs
**end-to-end** and produces two things:

1. **Part 1 — Annotation.** For every tile, detect and label four object types per the
   Marcaj schema (canopy polygons, row polylines, waste boxes, inter-row polygons) with the
   required attributes and **globally consistent IDs**, exported as CVAT 1.1 `annotations.xml`.
2. **Part 2 — Interface & calculations.** A Google-Maps-like web app fed by the annotated
   tiles that visualizes every layer, shows measurements (block/row counts, areas, lengths),
   and lets the **user click a START point** from which we compute the **shortest walking
   route** that visits all **waste** and **dead-plant (disrupted-row) targets** and returns
   to START — staying only on walkable ground.

**Main goal: the whole thing works E2E.** A complete, unbroken pipeline beats a perfect
single component. We optimize for coverage of the pipeline, not depth of any one model.

---

## 2. What we are scored on (this drives priority)

From the Marcaj presentation (`03_docs/Marcaj_Vineyard_AI_Visual_Journey.pdf`, p.9) and
`CLAUDE.md`:

| Weight | Category | Cheap to get right? | Our stance |
|--------|----------|---------------------|-----------|
| **25%** | Walking route | **Yes** — geometry + graph, no training | **TOP PRIORITY** |
| **25%** | Canopy segmentation | No — needs a good, slow-to-train model | **DEPRIORITIZE → minimal placeholder** |
| **15%** | Axes + attributes (rows) | **Mostly** — we already extract row polylines | **HIGH PRIORITY** |
| **15%** | Engineering quality | **Yes** — clean E2E pipeline, README, perf | **Earned by finishing E2E** |
| **10%** | Waste detection | Medium — detector, but small + IoU≥0.3 is lenient | **MEDIUM** |
| **10%** | Counts + measurements | **Yes** — pure geometry from annotations | **HIGH PRIORITY (nearly free)** |

### The key insight

Everything **except canopy** is reachable without heavy model work:

```
Route 25% + Axes 15% + Measures 10% + Waste 10% + Engineering 15% = 75%
```

That is the target surface. Canopy's 25% is gated behind a model that takes ~10 h to train
and tune — poor ROI in a hackathon. So **canopy gets a minimal placeholder** (best-effort
polygons from whatever model we have, wired into the pipeline so all four label types are
present and the CVAT export is complete) and **zero tuning time**. If time remains at the
end, we improve it; otherwise we leave the leverage where it pays.

---

## 3. Priority-ordered build plan (E2E first)

The ordering is: **get one thin end-to-end slice working, then widen it.** Never build a
component "ahead" of the slice it feeds.

### P0 — Skeleton E2E slice (must exist before anything is "done")
- `tiles → model → objects_by_tile → annotations.xml + measurements.csv → web/data → map renders`.
- Even with rows-only + empty canopy/waste, the pipeline must run start-to-finish on the
  real 311 tiles and the web app must load the output. **This is the definition of "works".**

### P1 — Route (25%) — highest single-component leverage
- User-selectable START in the web app; organizer's fixed START `[629504.7, 5220250.75]`
  is the **default** used for the scored `route.geojson`.
- Graph over walkable ground = `passages ∪ interrow_area − forbidden − canopy`.
- Targets = **waste centroids** + **disrupted-row inspection points** (dead plants).
- TSP (nearest-neighbour + 2-opt), return to START, emit `length_m`.
- Two routes: **blue** (inspector: waste + inspection) and **red** (farmer: waste only).
- Hard gates: >98% of length inside walkable, ends within 5 m of START (else route scores 0).

### P2 — Rows / axes (15%) + Measurements (10%) — cheap, already largely built
- Row polylines from `vine_row` masks (dominant-angle + perpendicular clustering).
- Global `vineyard_id` / `row_id` stitched in world space (union-find).
- `row_structure` attribute: `disrupted` where a row has a ≥5 m gap (also feeds route targets).
- Measurements: block count, row count, total row length, canopy/inter-row area → `measurements.csv`.

### P3 — Waste (10%) — small, lenient (IoU≥0.3)
- Precision-biased detector (a false box costs as much as a miss). Per-tile boxes.
- Feeds both the `waste` CVAT layer and the route targets.
- Acceptable fallback if the detector underperforms: keep boxes conservative (few, confident).

### P4 — Inter-row (part of Axes/Measures + walkable surface)
- Polygons derived from rows + canopy edges; `interrow_cover` attribute.
- Doubles as the **walkable surface** for the route — so it pays into both Route and Axes.

### P5 — Canopy (25%) — MINIMAL PLACEHOLDER ONLY
- Emit best-effort canopy polygons from the current model so CVAT has all four types.
- **No training, no tuning now.** Wire the code path; run it; accept whatever F1 we get.
- Stretch goal only: re-run against a better model if one is ready before the deadline.

### P6 — Engineering (15%) — earned by the above
- Single-command run, pinned deps, README (install/run/weights/perf/hardware), clean
  architecture, the working web app + deploy link. Mostly a byproduct of finishing E2E cleanly.

---

## 4. Part 2 — the routing feature (design)

The user's headline feature: **click a START, get the shortest inspection route to all waste
and dead plants.** Recommended approach (open to alternatives):

1. **Build the walkable graph once** from `passages ∪ interrow − forbidden − canopy`. A grid
   or medial-axis nav-graph over that surface, edges only between walkable cells (networkx).
2. **Snap START and every target** to the nearest graph node.
3. **All-pairs shortest paths** (START↔target, target↔target) constrained to the graph — a
   straight line that crosses canopy/forbidden is never used.
4. **TSP** over the targets (nearest-neighbour seed + 2-opt), returning to START.
5. Stitch the ordered shortest paths into one `LineString`; validate the hard gates.

**Why a graph:** the route must physically stay on walkable ground and avoid canopy/forbidden
zones — a Euclidean/straight-line solver would cut through vines and score 0. The graph
encodes "where a person can actually walk."

**User-selectable START:** the same graph serves any START — we just re-snap and re-solve.
The web app exposes this interactively; the scored `route.geojson` uses the fixed default.

---

## 5. Reusable assets from prior work (carry these over)

The earlier effort already produced working, verified modules that fit this plan directly.
"Start over" means a clean plan and structure — **not** discarding proven code. Reuse:

| Asset | File | Reuse verdict |
|-------|------|---------------|
| Row extraction (masks→polylines, dominant-angle + clustering) | `pipeline/rows_postproc.py` | **Reuse as-is.** Verified on 2 example tiles (14 rows, 370.6 m). |
| Global ID stitching (world-space union-find) | `pipeline/assign_ids.py` | **Reuse.** Algorithm sound; re-verify counts on a better model. |
| Orchestrator (all-311 driver) | `pipeline/run_pipeline.py` | **Reuse as the E2E spine.** Add canopy/waste/interrow lists as they land. |
| CVAT 1.1 XML writer | `pipeline/cvat_writer.py` | **Reuse as-is.** Round-trip validated, correct label block. |
| Measurements (pixel→EPSG:32635, areas, lengths) | `pipeline/measurements.py` | **Reuse as-is.** Validated physically sane on reference. |
| Route planner (grid nav-graph + TSP, two routes) | `pipeline/route_planner.py` | **Reuse.** Mock engine done; swap mock for real interrow/targets via `--interrow --targets`. |
| Web exporter (CVAT+tiles → WGS84 GeoJSON + CSV) | `pipeline/export_web_data.py` | **Reuse as-is.** |
| Web app (Leaflet map, layers, panels, filters) | `web/{index.html,app.js,style.css}` + `web/data/*` | **Reuse.** Add the interactive START-picker → route call. |
| Tile explorer / georef sanity | `pipeline/explore_tiles.py` | **Reuse for verification.** |
| Route/context inputs | `web/data/{passages,forbidden,start,study_area}.geojson`, root `route*.geojson` | **Reuse.** Real inputs already on disk. |

**Canopy code exists but is deprioritized:** `pipeline/segment_canopy.py` (classical, weak),
`pipeline/segment_canopy_sam.py` + `pipeline/eval_canopy.py` (SAM path), `train_riseholme.py`
/ `convert_riseholme_to_yolo.py` (training). Keep for the **placeholder** + optional stretch;
do not invest tuning time.

---

## 6. Data contract (the one interface everything agrees on)

Internal per-tile dict (model output → CVAT / measurements / route targets), pixel coords,
0,0 top-left:

```
objects_by_tile["siret3_r021_c012.tif"] = {
  "width": 2048, "height": 2048,
  "vineyard":      [ {points:[(x,y)...], vineyard_id} ],                       # placeholder OK
  "row":           [ {points:[(x,y)...], vineyard_id, row_id, row_structure} ],
  "interrow_area": [ {points:[(x,y)...], vineyard_id, interrow_cover} ],
  "waste":         [ {xtl,ytl,xbr,ybr, vineyard_id} ],
}
```

Outputs:
- `annotations.xml` (CVAT 1.1), `measurements.csv` (`metric,vineyard_id,row_id,value,unit`).
- `web/data/*.geojson` (WGS84) for the map; `route.geojson` + `route_farmer.geojson`
  (EPSG:32635, `length_m`) at repo root for the scored deliverable.
- Route targets: waste centroids + disrupted-row inspection points as EPSG:32635 Points.

---

## 7. Definition of done (E2E)

1. `python pipeline/run_pipeline.py` processes all 311 tiles → `annotations.xml` +
   `measurements.csv`, no crashes.
2. Exporter produces `web/data/*` and the web app renders every layer with populated panels.
3. User can pick a START in the app and get a valid route back; the default-START
   `route.geojson` passes the hard gates (inside walkable, returns within 5 m).
4. README lets a stranger install, run, and find the weights + performance numbers.
5. Canopy present as a (placeholder) layer so all four label types exist in the CVAT export.

Ship the full pipeline first; deepen components only after the E2E slice is green.
