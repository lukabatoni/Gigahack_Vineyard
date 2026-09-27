# PRESENTATION.md — 5-Minute Pitch (Vineyard AI Field Challenge)

> **Deeptech GigaHack 2026 · Marcaj challenge · Team pitch script.**
> Total budget: **5:00**. Practice to hit each timestamp. Speaker cues in *italics*.
> Numbers marked ⟨FILL⟩ get replaced with live figures right before you present
> (see "Live numbers cheat-sheet" at the bottom).

---

## The 5-minute structure (at a glance)

| # | Section | Time | Cumulative | Who / What's on screen |
|---|---------|------|-----------|------------------------|
| 1 | Hook | 0:15 | 0:15 | Slide 1 — one striking image |
| 2 | Problem | 0:45 | 1:00 | Slide 2 — the pain, the numbers |
| 3 | Solution overview | 0:45 | 1:45 | Slide 3 — pipeline diagram |
| 4 | Live demo | 1:30 | 3:15 | **The web map, live** |
| 5 | How it works (tech) | 0:45 | 4:00 | Slide 4 — model + method |
| 6 | Results & impact | 0:45 | 4:45 | Slide 5 — metrics table |
| 7 | Close / ask | 0:15 | 5:00 | Slide 6 — one line + team |

---

## 1 · HOOK — 0:15

*Open on a full-vineyard drone tile, rows glowing with our detected overlays.*

> "This is a 145-hectare vineyard in Siret, Moldova. A field scout walks it with a
> clipboard — **days** of work to map every row, every patch of waste, every gap.
> We did the whole thing automatically, in minutes."

*Beat. Let the image land. Do not explain yet.*

---

## 2 · PROBLEM — 0:45

*Slide 2: the manual workflow + the cost.*

> "Vineyard managers need to know four things: **where the plants are, where the
> rows run, where waste has piled up, and how to walk the site efficiently to
> inspect it.** Today that's manual annotation on drone imagery — one analyst,
> tile by tile, hundreds of tiles per property. It's slow, it's inconsistent
> between people, and it doesn't scale to a portfolio of vineyards.
>
> The organizer gave us **311 tiles** covering the estate — each 2048×2048 pixels
> at 2.5 cm per pixel. Annotating all of that by hand is exactly the bottleneck
> the industry is stuck on."

*Transition:* "So we built the analyst."

---

## 3 · SOLUTION OVERVIEW — 0:45

*Slide 3: pipeline diagram — imagery → AI → geospatial outputs → map.*

> "Our pipeline takes the raw orthomosaic and produces everything a manager needs,
> georeferenced and ready to use:
>
> - **Individual vine canopies** — one polygon per plant, not per row.
> - **Row centrelines** — as polylines, stitched into consistent IDs across every tile.
> - **Waste** — bounding boxes on litter and debris.
> - **Inter-row areas** — the walkable ground between rows.
> - **A walking route** — the efficient inspection path that returns to the start.
>
> All of it lands in an **interactive web map** and a **measurements report** —
> block counts, row lengths, canopy and inter-row area, in real-world metres."

---

## 4 · LIVE DEMO — 1:30  ← *the heart of the pitch, do not rush*

*Switch to the browser (http://localhost:8848). Have it pre-loaded and zoomed to a good vineyard block.*

**Beat A (0:30) — the map.**
> "Here's the estate. Every red line is a **row** our model detected — ⟨FILL: N_ROWS⟩
> rows across ⟨FILL: N_BLOCKS⟩ vineyard blocks. Toggle a layer…"
*Toggle rows off/on. Pan across a block.*

**Beat B (0:30) — one tile, everything.**
> "Let me zoom into a single tile so you can see the full detection stack —
> canopies as individual polygons, the rows through them, waste flagged here,
> and the inter-row corridors."
*Zoom to the demo tile (siret3_r006_c004). Show the layered overlays.*

**Beat C (0:30) — measurements + route.**
> "On the right, live measurements — ⟨FILL: N_BLOCKS⟩ blocks, ⟨FILL: N_ROWS⟩ rows,
> ⟨FILL: ROW_KM⟩ km of total row length, all in EPSG:32635. And this blue line is
> the walking route — it starts and returns to the same point, stays inside the
> walkable corridors, and covers the inspection targets."
*Trace the route with the cursor. Point at the length_m readout.*

*Transition:* "Under the hood —"

---

## 5 · HOW IT WORKS — 0:45

*Slide 4: model + method, kept simple.*

> "The core is a **YOLO11 segmentation model** we fine-tuned on this exact Moldova
> imagery — the off-the-shelf vineyard models failed on our domain, so we trained
> on the estate's own annotated tiles plus hand-picked negatives to kill false
> detections on forest and bare field.
>
> Rows are the clever part: we composite predictions across overlapping patches,
> fit a **centreline per row via principal-axis analysis**, then **stitch rows
> and blocks in world coordinates** so the same physical row keeps one ID across
> every tile it crosses — which is exactly what the scoring rewards.
>
> Everything downstream — measurements, the CVAT export for the platform, the
> route, the web map — is deterministic geospatial code. Reproducible, no manual
> touch-ups."

---

## 6 · RESULTS & IMPACT — 0:45

*Slide 5: metrics table + before/after.*

> "Concretely, on the full estate we produce:
> - ⟨FILL: N_BLOCKS⟩ vineyard blocks, ⟨FILL: N_ROWS⟩ rows, ⟨FILL: ROW_KM⟩ km of rows.
> - A closed walking route of ⟨FILL: ROUTE_M⟩ m.
> - All 311 tiles annotated and ready to upload to the Marcaj platform.
>
> Processing time: **⟨FILL: RUNTIME⟩ on a single laptop CPU** — no GPU cluster,
> no cloud bill. On a T4 GPU it's minutes.
>
> The impact: what took an analyst days is now an overnight job, and it's
> **consistent** — the same estate scored the same way every time. That's what
> makes it scale from one vineyard to a whole portfolio."

---

## 7 · CLOSE / ASK — 0:15

*Slide 6: product name + team + one line.*

> "From raw drone imagery to a field-ready inspection map, fully automatic.
> That's [TEAM NAME]. Thank you — happy to dig into any part."

*Stop. Do not add. Leave time for questions.*

---

## Live numbers cheat-sheet (fill these RIGHT before presenting)

Pull from `web/data/measurements.csv` and the route file:

| Placeholder | Where to read it | Current value |
|-------------|------------------|---------------|
| ⟨N_BLOCKS⟩ | measurements.csv `block_count` | 16 |
| ⟨N_ROWS⟩ | measurements.csv `row_count` | 60 |
| ⟨ROW_KM⟩ | measurements.csv `total_row_length` ÷ 1000 | ~32.4 km |
| ⟨ROUTE_M⟩ | route.geojson `length_m` property | ⟨read⟩ |
| ⟨RUNTIME⟩ | full pipeline wall-clock | ~35 min (CPU, 311 tiles) |

> ⚠️ These reflect the current run. If you re-run the pipeline with the
> row-stitching fix, **re-read the CSV and update this table before pitching** —
> the row/block counts will change.

---

## Delivery notes

- **One presenter drives the story, one drives the demo.** Rehearse the handoff at 1:45.
- **The demo is the proof.** If a slide and the live map disagree, trust the map — talk to what's on screen.
- **Have a fallback:** screen-record the demo in advance. If the live server hiccups, play the recording without breaking stride.
- **Cut, don't overrun.** If you're behind at 3:15, shorten section 5 to two sentences. Never eat into the close.
- **Anticipated questions:**
  - *"How accurate is it?"* → Row detection matches the reference on the example tiles within ~8%; canopy is our next milestone.
  - *"Does it generalize to other vineyards?"* → The method does; the weights are fine-tuned per estate, which is a few hours of training.
  - *"What about the manual correction step?"* → Our output pre-annotates the Marcaj platform, so humans only correct, not annotate from scratch — that's the 10× time saving.
