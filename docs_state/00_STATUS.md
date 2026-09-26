# 00 — PROJECT STATUS (the "where are we right now" file)

> **READ THIS FIRST in every new chat, right after `CLAUDE.md`.**
> This is the live heartbeat of the project. If anything here is stale, the whole
> chat starts from a wrong assumption. Keep it accurate.

**Last updated:** 2026-09-26 (Fri) — web interface (Task 11) built & data-verified; see `40_INTERFACE.md`.
**Deadline:** 15:00 Sunday 2026-09-27 (Chișinău time)

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

**Phase:** Canopy + rows — YOLO11-seg training RUNNING in background.

Training `yolo11n-seg` on the converted Riseholme dataset (trunk + vine_row,
imgsz=640, batch=2, 60 epochs w/ patience=15) on Apple M1 Pro (MPS).
Measured ~15.5 min/epoch → expect early-stop finish in ~2.5–4 hrs.
Outputs: `pipeline/runs/segment/riseholme/weights/best.pt`.

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
