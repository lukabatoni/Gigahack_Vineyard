# 20 — DECISIONS LOG (append-only; why we chose what)

> Append a dated entry whenever we make a decision that shapes the pipeline
> (model choice, algorithm, key parameter, scope call). Never delete — if a
> decision is reversed, add a new entry that supersedes it and say so.

---

### 2026-09-26 — Neural-network model is MANDATORY (from challenge docs)
- Source: `03_docs/Vineyard_AI_Field_Challenge_description.pdf`.
- Quote: *"The final deliverable combines a neural-network model, data annotations,
  calculated measurements, route planning and a working web interface."*
- Quote: *"Also provide neural-network model weights or a reproducible way to obtain them."*
- Quote: *"Allowed: any open pretrained models (e.g. SAM, YOLO)..."*
- **Implication:** Our pure-OpenCV canopy approach alone does NOT satisfy the
  deliverable. We must ship a NN + its weights (a downloadable/reproducible file).

### 2026-09-26 — "Weights" clarified
- Weights = a saved model parameter file (e.g. `yolo11n-seg.pt`). We do NOT compute
  weights by hand. Pretrained → file already exists (download). Fine-tune → training
  script writes a new file automatically.

### 2026-09-26 — Model strategy: pretrained-first, fine-tune only if needed
- Rationale: time-sensitive (deadline Sun 15:00). Test the cheapest option first.
- Step 1: run pretrained YOLO11-seg / SAM as-is, measure recall/precision. ~30 min.
- Step 2: review; if insufficient, fine-tune on **Riseholme** (open dataset, already
  annotated, different vineyard). No manual labeling, no from-scratch training, no
  data leakage from the 311 Siret3 test tiles.
- User's data concerns resolved: fine-tuning ≠ huge data ≠ manual labeling ≠ training
  on the images we score on.

### 2026-09-26 — Training config + dataset choice for the NN
- Two Riseholme datasets on disk; NEITHER has canopy polygons (`vineyard` class empty).
  Both have trunk + vine_row + pole. Chose **Dataset B** (COCO, 3 seasons incl. dormant
  March) as primary — 3 seasons should fix dormant-vine recall.
- Converter `convert_riseholme_to_yolo.py`: COCO train+valid→YOLO train, COCO test→YOLO
  val. Kept trunk→0, vine_row→1 (dropped pole; vineyard empty). Result: 684 train / 170
  val images. Class counts: trunk 18126, vine_row 3994.
- Training config (`train_riseholme.py`): yolo11n-seg, **imgsz=640, batch=2** (imgsz=1024
  batch=4 caused OOM / exit137 on M1 Pro), epochs=60, patience=15, device=mps.
- **Measured on M1 Pro: ~15.5 min/epoch.** Expect early-stop finish ~2.5–4 hrs.
- Canopy strategy locked: **trunk detector → SAM point prompt → leaf-outline polygon**
  (replaces failed ExG prompt generator; trunk detection works on dormant vines).

### 2026-09-26 — SAM+ExG baseline measured: INSUFFICIENT (mean canopy F1 = 0.228)
- Ran MobileSAM prompted by ExG green-mask blob centroids on the 2 example tiles.
- Results vs reference (metric = individual-canopy F1 at IoU≥0.5, the scoring metric):
  - r006_c004: pred=101 ref=251 → precision 0.752, recall 0.303, F1 0.432, classIoU 0.215
  - r021_c012: pred=6  ref=399 → precision 0.833, recall 0.013, F1 0.025, classIoU 0.031
  - **mean canopy F1 = 0.228**
- Diagnosis: SAM is accurate WHEN pointed at a vine (precision 0.75–0.83), but the
  ExG prompt generator can't find dormant vines → too few prompts (only 6 on r021).
  Bottleneck is the classical prompt step, not SAM. Same ceiling as pure classical CV.
- **Decision: proceed to fine-tune YOLO11-seg on Riseholme** — a model that finds vines
  directly from pixels, independent of the color mask.
- Scorer lives in `pipeline/eval_canopy.py` (reusable for the fine-tuned model too).

### 2026-09-26 — Route requirements VERIFIED against 03_docs PDFs (no hallucination)
- Source: `Vineyard_AI_Field_Challenge_description.pdf` (p2, p4, p5) + `Vineyard_AI_annotation_rules.pdf` (p5, p6, p7).
- **Output:** `route.geojson` = ONE LineString, EPSG:32635, starts AND ends at START
  `[629504.7, 5220250.75]` within **5 m**, with a `length_m` property. Repo root.
- **Walkable surface:** passable **inter-row areas** ⋃ **authorised passages** ONLY. NOT
  canopies, fences, forbidden zones. (interrow_area is explicitly "the walkable ground the route uses".)
- **Targets = inspection locations + detected waste.**
  - Inspection locations = "visible row gaps or potentially missing planting", each with an
    ID, coordinates, links to `vineyard_id`/`row_id`. Derived from rows w/ `row_structure=disrupted`.
  - These go into the APP OUTPUT, **NOT into Marcaj** (rules p7: "your inspection targets go
    into your application's output, not into Marcaj").
- **Objective:** minimise length while visiting every reachable target; must return to START.
- **Scoring (25%):** up to 15% coverage (route passes within **2 m** of each target);
  up to 10% efficiency L_ref/L, awarded from 90% coverage, scaled by coverage. L_ref = shorter
  of organizer route and shortest admitted team route.
- **Hard zero:** >2% of route length outside passable areas, OR not returning to START (5 m) → 0.
- Verified geojson files (all EPSG:32635, all FeatureCollection w/ 1 feature):
  - `start.geojson` Point, props name/description/crs/lon/lat/tile=siret3_r018_c010.tif
  - `passages.geojson` MultiPolygon, props type=passage
  - `forbidden.geojson` MultiPolygon, props type=forbidden
  - `study_area.geojson` Polygon, props name

### 2026-09-26 — TWO routes for the web interface (mentor Q&A)
- Solution has two user types; display two routes:
  - **Blue = government inspector:** visits BOTH inspection locations (dead/missing vines)
    AND waste on the plot.
  - **Red = farmer:** optimal path to collect waste only (based on inspection results).
- **Reconciliation with scoring:** the SCORED `route.geojson` is ONE LineString and the
  reference targets = inspection locations + waste → the scored route = the **blue inspector**
  route (superset of targets). Emit `route.geojson` from blue. Additionally emit
  `route_farmer.geojson` (red, waste-only) as a web-display-only layer. Same walkable graph,
  two target sets, two independent TSP solves.

### 2026-09-26 — Waste detection facts VERIFIED (03_docs)
- Label `waste`, axis-aligned bbox, attribute `vineyard_id` only.
- Anywhere on tile (vineyard + surrounding zone). Separate items → separate boxes;
  inseparable cluster → one box. Bbox area ≠ waste area.
- IS: bags, plastic film/sheets, bottles, cans, packaging, tyres, construction debris, rubbish heaps.
- NOT: vine tubes/stakes, trellis posts/wires, irrigation hoses, stones, bare/pale soil,
  flowering shrubs, pruning residue/cut branches, vehicles/machinery.
- `vineyard_id` = block it lies in, or nearest block within 10 m, else empty.
- **"When in doubt, leave it out — a false box costs as much as a miss."** → precision-biased.
- **Scoring (10%):** bbox F1, one-to-one matching at **IoU ≥ 0.3**.
- Plan: fine-tune YOLO detector on **DroneWaste** (open, aerial). Separate run from seg model.

### 2026-09-26 — Route planner engine (Lane B, Task 9, mock-first)
- **Method:** regular grid over the walkable polygon (nodes = grid points inside;
  edges = 4-neighbour segments `shapely.covers`-tested to stay fully inside) →
  `networkx` single-source Dijkstra between START+targets → nearest-neighbour + 2-opt
  TSP returning to START → stitch node paths into one LineString. Vectorised
  `shapely.contains_xy` / `covers` for speed (whole 4 ha passages graph builds in ~13 s
  at 2 m resolution: ~10k nodes / ~22k edges).
- **Walkable:** passages ⋃ interrow − forbidden (− canopy when available). Mock run
  uses passages only (interrow comes from Lane A A4).
- **Two routes, same graph:** blue = waste ∪ inspection targets → `route.geojson`
  (scored); red = waste only → `route_farmer.geojson`. Both EPSG:32635 w/ `length_m`.
- **Gate validation:** inside-fraction measured PER SEGMENT (a global
  `intersection().length` merges repeated traversals of the same thin corridor and
  under-reports; per-segment `covers` is correct). Resolution 2 m → target snap error
  ≤1.41 m < the 2 m coverage tolerance; route literally begins/ends at START so the
  5 m return gate is exact. Mock verify: blue 3459 m / red 2951 m, both 100% inside, PASS.
- **Integration contract:** `--interrow interrow.geojson --targets targets.geojson`
  (targets = Points w/ props id, kind∈{inspection,waste}, vineyard_id, row_id; EPSG:32635).

### 2026-09-26 — No row-angle assumptions (user directive, earlier)
- Do NOT assume rows are at 45° or any fixed angle. Solutions must generalize across
  all tile orientations, not be tuned to one example image.

### 2026-09-26 — Row centreline method: per-tile dominant angle, NOT per-mask PCA
- **Tried first, FAILED:** per-instance PCA (major axis of each vine_row mask). The
  epoch-22 model outputs short, near-round blobs (~300×200px, ratio ~0.6), so a single
  mask carries no reliable direction — polylines came out perpendicular to the true rows
  on the diagonal tile (r021). Correct-by-luck only when rows are already vertical (r006).
- **Adopted:** estimate ONE dominant row angle per tile via a structure tensor on the
  union of all vine_row masks (rows appear as parallel ridges; their shared orientation
  is robust). Project each mask centroid onto along/across axes, cluster by perpendicular
  offset (spacing ~45px) → one polyline per physical row along the dominant angle.
- Still honors "no fixed-angle assumption" — the angle is derived per tile from content.
- **Known limit:** coverage = model recall. Sparse/dormant rows get no mask → no line.
  Re-run when the 40-epoch model lands. If a tile has two blocks at different angles
  (road between), one-angle-per-tile may be too crude → revisit at Task 7 (global IDs).
- Code: `pipeline/rows_postproc.py`. E2E verified: 14 rows / 370.6m on the 2 example tiles.

### 2026-09-26 — Classical CV canopy method (baseline, likely superseded)
- ExG (Excess Green = 2G−R−B) chosen over VARI/GLI/NGRDI/local-contrast (best F1
  ~0.727/0.631 on the two example tiles).
- Adaptive local thresholding (8×8 grid per tile) for uneven illumination.
- Watershed (distance transform + local-maxima seeds) to split touching canopies.
- Tree/bush false-positives removed via contour-area filter (>MAX_AREA_PX).
- **Limitation:** cannot reliably separate dormant yellow-brown vines from brown soil
  at 2.5cm/px. This is why we move to a NN.
