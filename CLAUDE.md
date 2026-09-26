# CLAUDE.md — Vineyard AI Field Challenge (Deeptech GigaHack 2026)

> **Read this first in every new chat.** It is the single source of truth for the challenge rules,
> data layout, scoring, and what we still need to build.

---

## ⚡ START HERE — reading order for a fresh chat

This file (`CLAUDE.md`) holds the **fixed challenge rules** (they never change).
The **live project state** lives in `docs_state/`. Read them in this order:

1. `CLAUDE.md` (this file) — challenge rules, schema, scoring.
2. `docs_state/00_STATUS.md` — **where we are right now** + immediate next actions.
3. `docs_state/10_PIPELINE_PROGRESS.md` — per-component build status.
4. `docs_state/20_DECISIONS.md` — why we chose what (append-only log).
5. `docs_state/30_FINDINGS.md` — data facts, gotchas, hard-won knowledge.

### 🔴 THE UPDATE RULE (mandatory for EVERY chat, including this one)

> **Every change we make and every achievement we reach MUST be written back into
> the `docs_state/*.md` files before the task is considered done.**
> - New component finished / status changed → `10_PIPELINE_PROGRESS.md` + `00_STATUS.md`.
> - A decision made (model, algorithm, param, scope) → append to `20_DECISIONS.md`.
> - A data fact or gotcha learned → `30_FINDINGS.md`.
> - Plan or next-steps changed → update `00_STATUS.md`.
>
> Goal: a brand-new chat fed only `CLAUDE.md` + `docs_state/*.md` can continue the
> work with the same context. If it can't, the docs are incomplete — fix them.
> Keep `CLAUDE.md` for rules that don't change; keep evolving state in `docs_state/`.

---

## Event Facts

| Field | Value |
|-------|-------|
| Event | Deeptech GigaHack 2026 |
| Dates | 25–27 September 2026, Tekwill, Chișinău |
| Challenge provider | Marcaj |
| Prize | MDL 30,000 cash (1 winning team) |
| **Hard deadline** | **15:00 Sunday 27 September 2026 (Chișinău time)** |

---

## Current Status (as of start of hackathon, 25 Sep 2026)

- Mentor is **creating Marcaj accounts and the team project** — waiting for credentials by email.
- All local data is already present on disk (tiles, route files, examples).
- No code written yet — everything from model to web interface is still to be built.
- **We can work on the entire pipeline right now without Marcaj access.** Marcaj is only needed for the final upload + manual correction step.

### What we can do while waiting for Marcaj

1. **Explore & understand the tiles** — load example tiles, inspect georeferencing, visualise.
2. **Build the AI pipeline** — canopy segmentation, waste detection, row extraction, inter-row derivation.
3. **Write the CVAT XML generator** — produce `annotations.xml` from model output in the exact format.
4. **Route planning** — implement the TSP/walking-route solver over inter-row areas.
5. **Measurements module** — compute canopy area, inter-row area, row lengths in EPSG:32635.
6. **Web interface** — build the interactive map frontend.
7. **Study the example annotations** in `05_examples/siret3_examples_cvat/annotations.xml` to understand exact output format.

---

## Repository / Project Layout

```
/Users/luka-sap/Desktop/Gigahack/
├── 01_tiles/
│   ├── siret3_challenge_tiles_part1of5/   74 tiles  (r005–r... c...)
│   ├── siret3_challenge_tiles_part2of5/   71 tiles
│   ├── siret3_challenge_tiles_part3of5/   78 tiles
│   ├── siret3_challenge_tiles_part4of5/   76 tiles
│   └── siret3_challenge_tiles_part5of5/   12 tiles
│       TOTAL: 311 tiles, grid r005–r039, c000–c033
├── 02_route/
│   ├── start.geojson          START point: [629504.7, 5220250.75] EPSG:32635
│   │                          lon=28.7073776, lat=47.1230335, tile=siret3_r018_c010.tif
│   ├── passages.geojson       MultiPolygon — walkable areas (OSM roads + 5 manual passages)
│   ├── forbidden.geojson      MultiPolygon — forbidden zones (village core, buildings, compounds)
│   └── study_area.geojson     Full study area polygon
├── 03_docs/                   PDFs (annotation rules, challenge description, quick-start)
├── 04_source/
│   └── siret3_source_orthomosaic_EPSG4326.tif   Full ~145 ha orthomosaic (EPSG:4326)
├── 05_examples/
│   └── siret3_examples_cvat/
│       ├── annotations.xml    Reference CVAT 1.1 annotations (2 example tiles, not scored)
│       └── images/
│           ├── siret3_r006_c004.tif
│           └── siret3_r021_c012.tif
└── CLAUDE.md                  This file
```

**Tile spec:** 2048×2048 px GeoTIFF, 2.5 cm/px → 51.2 m on the ground, EPSG:32635.

---

## Annotation Schema — MANDATORY (exact names, lowercase, no deviations)

### Four labels

| Label | Geometry | Attributes |
|-------|----------|------------|
| `vineyard` | polygon | `vineyard_id` |
| `waste` | rectangle (bounding box) | `vineyard_id` |
| `row` | polyline | `vineyard_id`, `row_id`, `row_structure` |
| `interrow_area` | polygon | `vineyard_id`, `interrow_cover` |

### Attribute allowed values (use exactly these strings)

```
row_structure  →  regular | disrupted | unassessable
interrow_cover →  bare_soil | vegetation | mixed | unassessable
```

### Attribute meaning

| Attribute | On | Meaning |
|-----------|----|---------|
| `vineyard_id` | every object | Block name (e.g. `V01`). Must be identical across all tiles for the same physical block. |
| `row_id` | `row` | Row name within block (e.g. `V01-R01`). Same in every tile the row crosses. |
| `row_structure` | `row` | `regular` = no gap ≥5 m; `disrupted` = gap ≥5 m; `unassessable` = row invisible |
| `interrow_cover` | `interrow_area` | `bare_soil` <¼ vegetated; `mixed` ¼–¾; `vegetation` >¾; `unassessable` = ground hidden |

---

## Six Golden Rules — Never Violate

1. **One canopy = one plant.** Never one polygon over a whole row.
2. **Grapevines only.** Fruit trees, shrubs, weeds, grass are NOT `vineyard`.
3. **A row is one polyline per tile**, first to last vine (or tile edge), straight through any gap.
4. **Canopies and inter-row areas never overlap.** Inter-row runs canopy-edge to canopy-edge.
5. **IDs survive tile edges.** Same block → same `vineyard_id`. Same row → same `row_id` everywhere.
6. **Every tile gets an answer.** Annotate it or mark "No objects in this frame". Blank = blocked job.

---

## Detailed Annotation Rules

### `vineyard` canopy
- Polygon around ONE plant's foliage, trace leaves within ~10 cm.
- Exclude bare soil, plant shadow, weeds around it.
- Touching canopies: split at visible narrowing, or at planting distance (1.0–1.5 m) if no visible narrowing.
- Plant cut by tile edge: trace to edge; other half is a separate polygon in the neighbouring tile.
- Entirely in deep shadow and invisible: skip.
- Weeds/clumps < ~0.2 m² not part of a vine: skip.
- White tubes/stakes next to young vines: neither canopy nor waste.
- Trees inside vineyard: NOT `vineyard`; vines around them annotated normally.
- Garden vineyard: annotate only if ≥ 3 rows; single vine or arbour: skip.

### `waste`
- Tight axis-aligned bounding box around clearly visible litter.
- Anywhere on the tile (vineyard area and surroundings).
- Separate objects → separate boxes. Inseparable cluster → one box.
- `vineyard_id`: block it lies in, or nearest block within 10 m; empty if farther.
- **IS waste:** bags, plastic film, bottles, cans, packaging, tyres, construction debris, rubbish heaps.
- **NOT waste:** vine tubes, stakes, trellis posts, wires, irrigation hoses, stones, bare/pale soil, flowering shrubs, pruning residue, vehicles.
- Doubt? Leave it out. False positive costs as much as a miss.

### `row`
- One polyline per physical row per tile, within 0.2 m of vine centre line.
- 2 points for straight rows; add point where it bends.
- Gaps do NOT split a row — polyline runs straight through missing plants.
- Rows stop at edge of planting (NOT at road centre, NOT past headland).
- `row_id` recommended format: `<vineyard_id>-R<nn>` zero-padded (e.g. `V03-R017`).
- Row crossing tile edge → two polylines, one `row_id`.
- Distinct `row_id` count = scored row count; do NOT renumber from R01 in each tile.

### `interrow_area`
- Ground between canopy edges of two neighbouring rows in the same block.
- Long sides: along canopy edges (not row axes).
- Short sides: where rows end (headlands, roads, exterior land excluded; end at shorter row).
- Holes: cut out trees/buildings inside inter-row.
- One polygon per inter-row per tile; cut at tile edges.
- None outside the outermost rows of a block.

### Vineyard blocks (`vineyard_id`)
- Connected planting area; two plantings are the same block if they touch or gap < 5 m.
- **A road or track always separates blocks.**
- Every object must carry `vineyard_id`. Waste within 10 m of a block uses that block's ID.
- Same block → same `vineyard_id` everywhere. Values are free text; only grouping is scored.

### What NOT to annotate
- Inter-row axes (only inter-row areas)
- Roads, tracks, passages, forbidden zones, inspection targets
- Orchards, trees, shrubs, buildings, fences, crops other than grapevine
- Anything in the black area outside imagery on edge tiles

---

## CVAT for Images 1.1 Upload Format

### ZIP structure
```
team_upload.zip
├── annotations.xml
└── images/
    └── siret3_r021_c012.tif   (unchanged originals, original names, .tif only)
```

### `annotations.xml` label block (copy verbatim into `<meta><task><labels>`)
```xml
<label><name>vineyard</name><type>polygon</type><attributes>
  <attribute><name>vineyard_id</name><input_type>text</input_type></attribute></attributes></label>
<label><name>waste</name><type>rectangle</type><attributes>
  <attribute><name>vineyard_id</name><input_type>text</input_type></attribute></attributes></label>
<label><name>row</name><type>polyline</type><attributes>
  <attribute><name>vineyard_id</name><input_type>text</input_type></attribute>
  <attribute><name>row_id</name><input_type>text</input_type></attribute>
  <attribute><name>row_structure</name><input_type>select</input_type>
  <values>regular
disrupted
unassessable</values></attribute></attributes></label>
<label><name>interrow_area</name><type>polygon</type><attributes>
  <attribute><name>vineyard_id</name><input_type>text</input_type></attribute>
  <attribute><name>interrow_cover</name><input_type>select</input_type>
  <values>bare_soil
vegetation
mixed
unassessable</values></attribute></attributes></label>
```

### Per-image annotation block example
```xml
<image id="0" name="siret3_r021_c012.tif" width="2048" height="2048">
  <polyline label="row" points="112.0,1830.5;1990.4,402.7" occluded="0">
    <attribute name="vineyard_id">V03</attribute>
    <attribute name="row_id">V03-R02</attribute>
    <attribute name="row_structure">disrupted</attribute>
  </polyline>
  <polygon label="interrow_area" points="..." occluded="0">
    <attribute name="vineyard_id">V03</attribute>
    <attribute name="interrow_cover">bare_soil</attribute>
  </polygon>
  <polygon label="vineyard" points="..." occluded="0">
    <attribute name="vineyard_id">V03</attribute>
  </polygon>
  <rectangle label="waste" xtl="100" ytl="200" xbr="130" ybr="240" occluded="0">
    <attribute name="vineyard_id">V03</attribute>
  </rectangle>
</image>
```

**Rules:**
- Coordinates are in **pixels** (0,0 = top-left of tile).
- JPEG/PNG not accepted — only original GeoTIFFs.
- Keep each ZIP under 90 MB; split into parts if needed (5 parts already provided).
- `vineyard_id` and `row_id` must be assigned **globally across the whole orthomosaic before cutting per tile**.

---

## Marcaj Platform Workflow

```
1. Sign in       credentials emailed Friday evening (check spam)
2. Prepare ZIPs  5 ZIPs (one per supplied part), each ≤ 90 MB
3. Upload        all 5 parts into the DRAFT project
4. Check         Data card must show exactly 311 files
5. Publish       ONCE — irreversible; creates 63 jobs of 5 tiles each
6. Correct       each team member takes jobs from "Start labeling"
7. Submit        every job before 15:00 Sunday — In review = scored
```

**Three things that kill the score:**
1. Publishing before all 5 parts are uploaded (pre-annotations locked out).
2. Jobs left unsubmitted at deadline (counts as unannotated).
3. Deleting/renaming tiles or labels after publishing (reference matched by file name + label name).

**Editor shortcuts:** P = polygon, L = polyline, R = rectangle, V = pointer, D/F = prev/next tile, Ctrl+Z/Y = undo/redo.

---

## Required Submission Deliverables

| File / Item | Spec |
|-------------|------|
| `route.geojson` | LineString, EPSG:32635, starts AND ends within 5 m of START point `[629504.7, 5220250.75]`, has `length_m` property |
| `measurements.csv` | Block count, row count, row lengths, canopy area (m²/ha), inter-row area (m²/ha) by `vineyard_id`/`row_id` |
| `README.md` | Install + run steps; pinned dependencies; Dockerfile (plus); model weights location; processing time + hardware; any paid APIs/LLMs used |
| Application code | Full processing pipeline source |
| Web interface | Working interactive map (link in README). Show: map with all objects, IDs, measurements, route with length. |
| Marcaj project | Published, all jobs submitted before 15:00 Sunday |

---

## Scoring (85% automated + 15% expert)

| Weight | Category | Detail |
|--------|----------|--------|
| **25%** | Canopy segmentation | 0.6 × class IoU + 0.4 × individual canopy F1 (IoU ≥ 0.5 match). False canopies on non-vineyard tiles: −0.5 × share of tile covered. |
| **25%** | Walking route | Up to 15% coverage (pass within 2 m of each target); up to 10% efficiency (L_ref / L, awarded from 90% coverage). Route outside passages/inter-rows (>2%) or not returning to start → 0 on this criterion. |
| **15%** | Axes + attributes | 8% row-axis F1 (0.4 m tolerance, 80% mutual coverage); 5% attribute accuracy (row_structure, interrow_cover); 2% vineyard_id grouping consistency. |
| **15%** | Engineering quality | Architecture (5), robustness (4), scalability (3), measured performance (3). |
| **10%** | Waste detection | Bounding-box F1, one-to-one matching at IoU ≥ 0.3. |
| **10%** | Counts + measurements | 2% each: block count, row count, canopy area, inter-row area, total row length. Tolerance 15% for counts/areas, 10% for length. Score = max(0, 1 − relative_error/tolerance). |

**Admission gate:** working web interface + published Marcaj project with submitted jobs + correct formats + EPSG:32635 georeferencing. Missing any → disqualified.

Tie-breaker order: walking route → canopy segmentation → jury vote.

---

## Technical Constraints

- **All output geometries in EPSG:32635** (WGS 84 / UTM zone 35N, metres).
- Measurements: horizontal, no terrain correction.
- Canopy area = union of canopy polygons (not sum; no double-counting overlaps).
- Walking route: passable inter-row areas + authorised passages ONLY; no canopies, fences, forbidden zones.
- START point: `[629504.7, 5220250.75]` EPSG:32635 (lon 28.7073776, lat 47.1230335), tile `siret3_r018_c010.tif`.
- `passages.geojson`: MultiPolygon of walkable ground (OSM roads buffered + 5 manual passages).
- `forbidden.geojson`: MultiPolygon of forbidden zones (village core, OSM buildings +1 m, compounds).

---

## Pipeline Components to Build

### 1. AI/ML Model
- **Canopy segmentation** — instance segmentation of individual grapevine canopies (polygon per plant).
- **Waste detection** — object detection with axis-aligned bounding boxes.
- **Row extraction** — line detection / skeletonisation to get row centre polylines.
- **Inter-row derivation** — computed from row positions + canopy edges (can be post-processing).
- **Attribute classification** — `row_structure` and `interrow_cover` from image patches.
- **Block detection** — clustering rows/canopies into vineyard blocks, assign consistent `vineyard_id`.

Suggested models: SAM (segmentation), YOLO (detection), Hough/RANSAC or deep line detector (rows). Open datasets: Riseholme (855 UAV images, 40k COCO annotations), DroneWaste.

### 2. ID Assignment (Critical)
- Assign `vineyard_id` and `row_id` **globally over the full orthomosaic** before splitting per tile.
- Use the tile grid coordinates (r, c) to stitch row lines across tile boundaries.
- Recommended: process source orthomosaic (`04_source/`) as a whole, then clip annotations per tile.

### 3. CVAT XML Generator
- Converts model output (polygons, polylines, boxes in pixel coords) → `annotations.xml` in CVAT 1.1.
- Must produce the exact label block shown above.
- Must group annotations correctly by image filename.

### 4. Route Planner
- Targets: waste detections + inspection locations (row gaps / disrupted rows).
- Graph: inter-row areas + passages as walkable edges.
- Algorithm: TSP or nearest-neighbour heuristic; must return to START.
- Output: `route.geojson` LineString with `length_m`.

### 5. Measurements Module
- Reproject pixel coords → EPSG:32635 using tile GeoTIFF transform.
- Canopy area: union of all `vineyard` polygons per block.
- Inter-row area: sum of `interrow_area` polygons per block.
- Row length: sum of polyline lengths per row (across tiles).
- Output: `measurements.csv`.

### 6. Web Interface
- Interactive map (Leaflet / MapLibre / Deck.gl) showing tiles as basemap.
- Layers: canopy polygons, waste boxes, row polylines, inter-row areas, walking route.
- Panels: block/row counts, area table, route length.
- Filter by `vineyard_id` / `row_id`.

---

## Common Mistakes — Avoid These

| Mistake | Consequence |
|---------|-------------|
| Rows renumbered R01…Rn in every tile | Distinct `row_id` count inflated; cross-tile rows look different |
| New `vineyard_id` per tile for same block | Block count wrong; grouping score drops |
| Any attribute left empty | Counts as wrong answer |
| Wrong case: `Regular`, `Bare_Soil`, `bare soil` | Invalid value; wrong answer |
| `interrow_cover` set on a `row` | Ignored by scorer |
| One polygon over a whole row (not individual plants) | Canopy count wrong; IoU penalised |
| Publishing Marcaj project before 311 files confirmed | Pre-annotations cannot be imported afterwards |
| Job not submitted before deadline | Counts as unannotated |
| `route.geojson` not returning to START within 5 m | Route score = 0 |
| Route passing through forbidden zones or canopies | Route score = 0 if >2% outside passable areas |

---

## Open Datasets for Training

| Dataset | Contents |
|---------|----------|
| Riseholme | 855 UAV RGB images, 40,215 COCO segmentation annotations (canopy + row). Best fit. |
| UOPNOA | ~34,000 RGB aerial images + land-use masks (block-level, not individual canopy) |
| DroneWaste | Annotated aerial waste — use for waste detection fine-tuning |

Verify licences before use. Adapt for differences in resolution, season, vine variety appearance.

---

## Coordinate System Quick Reference

| Context | CRS | Notes |
|---------|-----|-------|
| Tiles on disk | EPSG:32635 | Already reprojected; annotate in pixels |
| Source orthomosaic | EPSG:4326 | Reproject to 32635 before use |
| All submission outputs | EPSG:32635 | Mandatory |
| Marcaj annotation | pixels | Platform handles geo conversion |
| Tile pixel → metres | × 0.025 | 2.5 cm/px |
| Tile ground footprint | 51.2 m × 51.2 m | 2048 px × 0.025 m/px |
