# 00 — PROJECT STATUS (the "where are we right now" file)

> **READ THIS FIRST in every new chat, right after `CLAUDE.md`.**
> This is the live heartbeat of the project. If anything here is stale, the whole
> chat starts from a wrong assumption. Keep it accurate.

**Last updated:** 2026-09-27 (Sun) — `main` branch made submission-ready: all four root deliverables present + reproducible. See "Current stage".
**Deadline:** 15:00 Sunday 2026-09-27 (Chișinău time)

---

## 2026-09-27 — main branch submission prep (DONE)

Made `main` a self-contained, reproducible submission per the organizer checklist:
- **`route.geojson`** (root): closed LineString, EPSG:32635, start==end within 5 m of
  START `[629663.8, 5220195.3]` (organizer pre-test point — supersedes the old
  `[629504.7,5220250.75]`), `length_m=3456.3`. `route_farmer.geojson` also present (3200.8 m).
  Both PASS the hard gates (100% inside walkable, ends_ok, 0 unreachable).
- **`measurements.csv`** (root): promoted from the verified 9-tile demo region
  (`measurements_demo9.csv`) — 3 blocks, 131 rows, 6263.96 m row length, 855.29 m² canopy,
  15267.68 m² inter-row. Chosen over the stale `measurements_all.csv` (pre-fix inflated
  counts 335/428, zero canopy).
- **`README.md`** (root): run steps (tiles → route + measurements + web), processing
  time + hardware (Apple M1 Pro/16 GB, MPS; ~4–6 s/tile, full 311 ~30–45 min), weights location.
- **`Dockerfile`** (root): python:3.9-slim + GDAL/GEOS/PROJ apt libs + pinned requirements.
- **Weights fix:** the tracked `weights/canopy_row_best.pt` (md5 7666f1) was NOT the model
  the pipeline uses. Copied the real negatives-trained rows model to `weights/rows_best.pt`
  (md5 0c713ac2) and repointed `rows_postproc.BEST` to a repo-relative path (env `ROWS_WEIGHTS`
  override). Previously `BEST` hard-coded an absolute gitignored `pipeline/runs/` path.
- **Fixed pipeline onto main:** brought `assign_ids.py` (row-stitch `_same_rowline` fix +
  MIN_ROWS_PER_BLOCK prune + canopy vineyard_id), `run_pipeline.py` (canopy+interrow wiring,
  `--tiles-list`), and new `interrow.py` from `laneA/full-stack-demo9`. main previously had
  the OLD over-merging stitch (`di <= ROW_MERGE_M`). Imports + weights load verified.

---

## THE UPDATE RULE (mandatory for every chat)

> **Every change we make and every achievement we reach MUST be written back into
> these `docs_state/*.md` files before the chat ends or the task is considered done.**
>
> - Finished a component? → update `10_PIPELINE_PROGRESS.md` + this file's "Current stage".
> - Made a decision (model choice, algorithm, param)? → append to `20_DECISIONS.md`.
> - Learned something about the data / hit a gotcha? → `30_FINDINGS.md`.
> - Changed the plan / next steps? → update "Next actions" below.
>
> A fresh chat fed only `CLAUDE.md` + `docs_state/*.md` must be able to continue
> the work with the same context. If it can't, the docs are incomplete — fix them.

---

## Current stage

**Phase:** Canopy + rows — YOLO11-seg RESUMED training RUNNING in background.

Resumed run (`pipeline/resume_riseholme.py`, bg id `bp67b2phx`): reloads epoch-22
`last.pt` and re-targets 40 epochs (counter restarts 1/40, refining on top of the 22
already learned). imgsz=640, batch=2, patience=15 on Apple M1 Pro (MPS).
Measured ~15.5 min/epoch → expect finish in ~4-10 hrs (or earlier if patience triggers).
Outputs overwrite `pipeline/runs/segment/riseholme/weights/best.pt`.

This one run produces BOTH:
- a **vine_row detector** → Task 4 (rows)
- a **trunk detector** → per-plant seeder for canopy-via-SAM (Task 3)

**While training runs, build model-independent pipeline pieces** (see Next actions).

**Baseline to beat:** SAM+ExG canopy mean F1 = 0.228.

**Key clarifications locked in (so we don't re-litigate):**
- "Weights" = a saved model parameter file (e.g. `yolo11n-seg.pt`). No manual math.
- Pretrained models (SAM, YOLO) are explicitly allowed by the challenge docs.
- We train on Riseholme, we RUN on our 311 Siret3 tiles. Training on the test tiles
  would be data leakage — we do NOT do that.
- Fine-tuning needs only hundreds–thousands of labeled examples (pretrained model
  already knows generic shapes); Riseholme's 40k annotations is plenty.

---

## Next actions (immediate)

1. [~] Training running (bg; ~epoch 9/60 at last check, best.pt already written). Wait for finish.
2. [ ] PARALLEL, model-independent — three plans now written in `10_PIPELINE_PROGRESS.md`
   ("PARALLEL-WORK TASK PLANS"), teammates can pick up:
   - **Task 6 Waste detection** — YOLO detector on DroneWaste, precision-biased, IoU≥0.3.
   - **Task 9 Route planner** — TWO routes (blue inspector = dead vines + waste; red farmer =
     waste only). `route.geojson`=blue, one LineString, return to START ≤5m, `length_m`.
   - **Task 11 Web interface** — Leaflet/MapLibre, all layers + both routes + panels.
3. [ ] When training done: run `best.pt` on our 2 tiles; check trunk + row detections.
4. [ ] Wire trunk detections → SAM prompts → canopy polygons; re-score vs F1 0.228.
5. [ ] Build row post-proc: vine_row instance masks → centreline polylines.

**Route facts are VERIFIED against 03_docs PDFs** (see 20_DECISIONS.md). Key gates:
route >2% outside passages⋃interrow OR not returning to START (5 m) → route score 0.
Targets = inspection locations (disrupted rows / gaps) + waste; inspection targets go in
APP OUTPUT, never into Marcaj.

---

## Environment (quick facts)

- Working dir: `/Users/luka-sap/Desktop/Gigahack/`
- Python: 3.9.6 (system; no newer available on this machine)
- venv at `./venv/`, deps pinned in `./requirements.txt`
- Key deps: rasterio, shapely, geopandas, numpy 1.26, opencv, scipy, torch 2.8,
  torchvision 0.23, ultralytics 8.3, networkx 3.2.1, pyproj, matplotlib
- Activate: `source venv/bin/activate`
