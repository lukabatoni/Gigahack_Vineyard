# 50 — PARALLEL WORK PROTOCOL (two Claude sessions, no collisions)

> **Read this in full before touching any code if you were pointed here.**
> This file lets TWO Claude sessions (each with its own human driver) build the
> pipeline at the same time without conflicts. It assigns non-overlapping file
> ownership, a branching strategy, block-by-block build steps, milestone→MR
> triggers, and a STOP/NOTIFY protocol for when reality diverges from the plan.
>
> This file is authoritative for *coordination*. `CLAUDE.md` is authoritative for
> *challenge rules*; `docs_state/10_PIPELINE_PROGRESS.md` for *component status*.

**Last updated:** 2026-09-26 (Fri)
**Deadline:** 15:00 Sunday 2026-09-27.

---

## 0. THE GROUND RULES (read once, obey always)

1. **Stay on your branch.** Never commit to `main` directly. Never edit files owned
   by the other lane (see §2 ownership table). If you think you must, STOP (§6).
2. **Pull before you branch, rebase before you MR.** `main` moves under you.
3. **One milestone = one MR.** When you hit a milestone (§4/§5), open a PR, then
   STOP and wait for it to be merged before starting work that depends on it.
4. **When the plan breaks, STOP and NOTIFY (§6).** Do not improvise around a broken
   assumption, a missing dependency, or a merge conflict you didn't expect. Surface
   it to the human so the OTHER lane can be told.
5. **Update the docs as you go** (`10_PIPELINE_PROGRESS.md` status, this file's
   checkboxes). A change that isn't written down didn't happen.
6. **Never touch shared infra without a heads-up:** `main`, the training run
   (`pipeline/runs/`, `resume_riseholme.py`), `requirements.txt`, `.gitignore`,
   `CLAUDE.md`. These are cross-lane. Editing them = STOP/NOTIFY first.

---

## 1. THE TWO LANES

Work is split into two lanes that share almost no files. Each lane is one Claude
session + one human.

| Lane | Owner focus | Tasks | Branch prefix |
|------|-------------|-------|---------------|
| **Lane A — Perception & Annotation** | model output → CVAT + measurements | 3b, 4, 5, 7, 8(done), 10 | `laneA/*` |
| **Lane B — Route & Interface** | route planning + web app | 6, 9, 11 | `laneB/*` |

**Why this split works:** Lane A produces the *data* (GeoJSON layers, measurements.csv,
annotations.xml). Lane B *consumes* that data (route planner reads layers; UI displays
them). They meet ONLY at the **data contract** (§3), never in the same source file.

Waste (Task 6) is in Lane B because its output (`waste.geojson`) is a route target
and a UI layer; it does not touch the perception model. If Lane B is overloaded,
Task 6 can move to Lane A — but decide that BEFORE starting, via §6.

---

## 2. FILE OWNERSHIP (do not edit across the line)

| Path | Owner | Notes |
|------|-------|-------|
| `pipeline/segment_canopy*.py`, `eval_canopy.py` | A | canopy |
| `pipeline/train_riseholme.py`, `resume_riseholme.py`, `pipeline/runs/` | A + SHARED | training is shared infra — coordinate (§6) |
| `pipeline/convert_riseholme_to_yolo.py` | A | |
| `pipeline/rows_postproc.py` (NEW) | A | Task 4 post-proc |
| `pipeline/interrow.py` (NEW) | A | Task 5 |
| `pipeline/assign_ids.py` (NEW) | A | Task 7 |
| `pipeline/cvat_writer.py`, `pipeline/measurements.py` | A | done; A owns edits |
| `pipeline/run_pipeline.py` (NEW, orchestrator) | A | ties model→CVAT→measurements |
| `pipeline/waste_detect.py` (NEW) | B | Task 6 |
| `pipeline/route_planner.py` (NEW) | B | Task 9 |
| `pipeline/export_web_data.py` | B | already exists (UI branch) |
| `web/**` | B | entire web app |
| `docs_state/40_INTERFACE.md` | B | |
| `docs_state/10_PIPELINE_PROGRESS.md` | BOTH | edit ONLY your own task's row |
| `docs_state/00_STATUS.md`, `20_DECISIONS.md`, `30_FINDINGS.md` | BOTH | append-only; append, don't rewrite others' lines |
| `CLAUDE.md`, `.gitignore`, `requirements.txt`, `weights/` | SHARED | STOP/NOTIFY before editing |

**Rule of thumb:** if a file has your task number in §2, it's yours. If it's marked
BOTH, only append/edit your own rows. If it's SHARED, coordinate first.

---

## 3. THE DATA CONTRACT (the ONE interface between lanes)

Lane A writes these; Lane B reads them. **Neither lane may change these shapes
without a STOP/NOTIFY (§6)** — a silent field rename breaks the other lane.

All geometry that the pipeline produces internally is **pixel coords per tile**
(CVAT convention, 0,0 top-left). Conversion to EPSG:32635 / WGS84 happens in
`measurements.py` (metres) and `export_web_data.py` (WGS84 for the map).

### Internal per-tile dict (model output → cvat_writer / measurements)
```
objects_by_tile = {
  "siret3_r021_c012.tif": {
    "width": 2048, "height": 2048,
    "vineyard":      [ {points:[(x,y)...], vineyard_id} ],
    "row":           [ {points:[(x,y)...], vineyard_id, row_id, row_structure} ],
    "interrow_area": [ {points:[(x,y)...], vineyard_id, interrow_cover} ],
    "waste":         [ {xtl,ytl,xbr,ybr, vineyard_id} ],
  }, ...
}
```

### Web layers (EPSG:4326 / WGS84 GeoJSON FeatureCollections in `web/data/`)
- `canopy.geojson`, `rows.geojson`, `interrow.geojson`, `waste.geojson`
- `route.geojson` (blue inspector, scored), `route_farmer.geojson` (red, display)
- properties carry `vineyard_id` / `row_id` / `row_structure` / `interrow_cover`
- `measurements.csv` columns: `metric,vineyard_id,row_id,value,unit`

### Route targets (Lane A → Lane B, EPSG:32635 points)
- waste centroids (from `waste.geojson`)
- inspection points: from rows with `row_structure=disrupted` → `{id, x, y, vineyard_id, row_id}`

If you need a field that isn't here, that's a contract change → §6.

---

## 4. LANE A — BLOCK-BY-BLOCK BUILD

> Build one block, verify it, tick it, move on. Do NOT build ahead of a milestone.

### Block A1 — Rows E2E slice (highest value, do first)
- [ ] `laneA/rows-postproc` branch off `main`.
- [ ] `pipeline/rows_postproc.py`: load `best.pt`, predict `vine_row` masks on a tile,
      convert each instance mask → centreline polyline (skeletonize or PCA-major-axis;
      NO fixed-angle assumption — see 20_DECISIONS). Output per-tile `row` dicts (§3).
- [ ] Verify on the 2 example tiles: overlay polylines on the tile, eyeball vs reference.
- [ ] Feed into `cvat_writer.py` → valid `annotations.xml` (round-trip parses).
- [ ] Feed into `measurements.py` → real row_count + total row length.
- [ ] **MILESTONE A-1 → open MR** "Lane A: rows postproc → CVAT + measurements".
      Then STOP; wait for merge.

### Block A2 — Orchestrator + all-311 dry run
- [ ] `laneA/orchestrator` off updated `main`.
- [ ] `pipeline/run_pipeline.py`: iterate all 311 tiles, run model, assemble
      `objects_by_tile`, write `annotations.xml` + `measurements.csv`.
- [ ] Run on a 5-tile sample; confirm no crashes, sane counts.
- [ ] **MILESTONE A-2 → open MR.** STOP.

### Block A3 — Canopy via SAM (mandatory NN deliverable)
- [ ] `laneA/canopy-sam` off `main`. Needs final-ish `best.pt` (trunk detections).
- [ ] trunk detections → SAM point prompts → canopy polygons; re-score vs F1 0.228 baseline.
- [ ] **MILESTONE A-3 → open MR.** STOP.

### Block A4 — Inter-row (Task 5) + Global IDs (Task 7)
- [ ] `laneA/interrow-ids` off `main`. Derive interrow polygons from rows+canopy edges;
      classify `interrow_cover`. Assign `vineyard_id`/`row_id` globally, then clip per tile.
- [ ] **MILESTONE A-4 → open MR.** STOP.

### Lane A DEPENDENCY NOTE
- A1 works on the model we HAVE NOW (rows already detect). Do it immediately.
- A3 wants the finished 40-epoch model. If training isn't done, build the code path
  against current `best.pt` and re-run at the end — do NOT block on training.

---

## 5. LANE B — BLOCK-BY-BLOCK BUILD

### Block B1 — Web interface finalize (already built, wire real data)
- [ ] `laneB/web-finalize` off `main`. UI exists (`web/`). Confirm it loads the
      example-tile data; add any missing layer toggles (blue/red routes).
- [ ] Verify locally (open `web/index.html`, all layers render, panels populate).
- [ ] **MILESTONE B-1 → open MR** "Lane B: web loads full layer set + both routes".
      STOP.

### Block B2 — Waste detector (Task 6)  ⚠️ BLOCKED — see note
- [ ] BEFORE coding: is DroneWaste on disk + are mentor Qs answered (§7 in
      30_FINDINGS / open questions)? If NO → this block is BLOCKED, do B3 first.
- [ ] `laneB/waste` off `main`. `pipeline/waste_detect.py`: precision-biased detector,
      per-tile boxes (§3). Score at IoU≥0.3 (reuse eval_canopy greedy match).
- [ ] Output `web/data/waste.geojson` + route targets.
- [ ] **MILESTONE B-2 → open MR.** STOP.

### Block B3 — Route planner (Task 9)  ⚠️ partial dependency
- [ ] `laneB/route` off `main`. Build solver against `passages.geojson` + MOCK
      interrow + MOCK targets first (real interrow = Lane A Block A4).
- [ ] Graph over walkable surface; TSP; return-to-START; `length_m`; both routes.
- [ ] Validate hard gates (>98% inside walkable, ends within 5m of START).
- [ ] **MILESTONE B-3 → open MR** (mock-data version OK; note it in the PR). STOP.
- [ ] Later: swap mock interrow/targets for Lane A real outputs → follow-up MR.

### Lane B DEPENDENCY NOTE
- B1 has no dependency — do it now.
- B3 can start now on mocks; it only NEEDS Lane A's `interrow.geojson` + targets to
  produce the FINAL route. Build the engine now, integrate real data after A4.

---

## 6. STOP / NOTIFY PROTOCOL (when the plan diverges)

**A Claude following this file MUST STOP and hand back to its human when ANY of:**
- A file it needs is owned by the other lane (§2) and must change.
- A data-contract shape (§3) needs to change.
- A merge conflict appears that isn't a trivial docs-append.
- A dependency it assumed is missing/broken (e.g. DroneWaste absent, training
  unfinished, `best.pt` produces garbage).
- The milestone's assumption turned out false (e.g. rows postproc doesn't work,
  interrow can't be derived the planned way).
- Anything that would force it to edit SHARED infra (§0.6).

**When you STOP, produce a NOTIFY block** — a short message the human copies to the
other lane's human/Claude:
```
NOTIFY [Lane X → Lane Y]
- What I hit: <one line>
- Why it affects you: <one line — e.g. "row_id field renamed", "route targets shape changed">
- What I need / propose: <one line>
- Blocking? <yes/no> — <what I'm doing meanwhile>
```
Then WAIT. Do not work around it silently. The whole point of two lanes is that
neither surprises the other.

**Milestone → MR is also a STOP.** After opening the MR, do not start dependent work;
wait for merge (or explicit "keep going on an independent block").

---

## 7. BRANCHING & MR MECHANICS (exact commands)

Branch naming: `laneA/<short>` or `laneB/<short>` (matches §1).

Start a block:
```
git checkout main && git pull --ff-only origin main
git checkout -b laneA/rows-postproc
```
During work: commit small, often, on your branch. Never on `main`.

At a milestone, open the MR (Claude may run this — it's a shared/remote action, so
confirm with the human first):
```
git push -u origin laneA/rows-postproc
gh pr create --base main --title "Lane A: rows postproc -> CVAT + measurements" \
  --body "Milestone A-1. <what/why>. Data contract untouched. Verified on 2 example tiles."
```
Before opening: `git fetch origin && git rebase origin/main` (resolve on your side).
If rebase hits a conflict outside your ownership → STOP/NOTIFY (§6).

Merging is a human decision. After merge, both lanes `git pull --ff-only` on `main`.

---

## 8. MILESTONE LEDGER (tick when MERGED to main)

| ID | Lane | Milestone | MR | Merged |
|----|------|-----------|----|--------|
| A-1 | A | rows postproc → CVAT + measurements | e556ca4 | [x] |
| A-2 | A | orchestrator, all-311 dry run | 66d2a32 | [x] |
| A-3 | A | canopy via SAM, re-scored | — | [ ] |
| A-4 | A | interrow + global IDs | — | [ ] |
| B-1 | B | web loads full layers + both routes | on main | [x] (UI built; blue/red route toggles present; loads example data) |
| B-2 | B | waste detector (IoU≥0.3) | — | [ ] BLOCKED — DroneWaste not on disk |
| B-3 | B | route planner (mock → real) | laneB/route | [~] mock engine done & verified; MR pending |

---

## 9. SHARED-STATE SNAPSHOT (keep current; both lanes read this)

- **Training:** resume run to 40 epochs is IN BACKGROUND (bg id `bp67b2phx`, started 2026-09-26 ~14:52). Reloads `last.pt` (epoch-22 weights) and re-targets 40 epochs, so the counter restarts at 1/40 — it does 40 refinement epochs on top of the 22 already learned. `results.csv` in the run dir is overwritten with the new run.
  Current usable weights: `pipeline/runs/segment/riseholme/weights/best.pt`
  (git-committed snapshot at `weights/canopy_row_best.pt`, older). Model detects
  `vine_row` well; `trunk` weak at low epochs. Do not restart training without §6.
- **Merged so far on main:** pipeline code (canopy/rows converter, cvat_writer,
  measurements, eval), web interface (Task 11), resume script.
- **Blocked:** Task 6 waste (no DroneWaste on disk, no local ground truth, mentor
  Qs open).
- **Task 9 route:** mock engine DONE (`pipeline/route_planner.py`, branch `laneB/route`)
  — grid nav-graph + TSP, both routes 100% inside & return to START. Needs Lane A
  `interrow.geojson` (walkable fields) + real targets (waste centroids + disrupted-row
  inspection points) for the FINAL efficient route. Integrate via `--interrow --targets`.
  NOTE for Lane A: targets file = FeatureCollection of Points, props `{id, kind:
  "inspection"|"waste", vineyard_id, row_id}`, EPSG:32635 (see route_planner.load_targets).
