# 40 — WEB INTERFACE (Task 11) — build log & handoff

> **Self-contained handoff.** A fresh Claude fed `CLAUDE.md` + `docs_state/*.md`
> (this file included) must be able to continue the web interface with zero
> knowledge loss. If it can't, this file is incomplete — fix it.
>
> ### 🔴 THE UPDATE RULE (same as the rest of docs_state)
> **Every change to the interface or its data pipeline MUST be written back here
> before the task is considered done.** New feature → mark its step done below.
> New decision (stack, layer, styling, deploy target) → "Decisions" section.
> New gotcha → "Findings" section. Changed plan → "Next steps".

**Last updated:** 2026-09-26 (Fri)
**Owner of this component:** (interface)
**Related:** `10_PIPELINE_PROGRESS.md` Task 11 plan · `20_DECISIONS.md` (two-routes decision).

---

## 1. Goal (what the interface must be)

An **admission-gate deliverable**: a working interactive map (link goes in
`README.md`). Missing/broken interface → whole submission disqualified. It must
show every produced object over the vineyard and report the measurements.

**Layers (all toggleable):**
- `canopy` — vine-canopy polygons (green), one per plant
- `rows` — row centre polylines (blue-ish)
- `interrow` — inter-row area polygons (orange)
- `waste` — waste bounding boxes (red)
- **blue route** — government-inspector route (visits dead/missing vines + waste) = scored `route.geojson`
- **red route** — farmer route (waste-only) = `route_farmer.geojson` (display only)
- START marker; `passages` + `forbidden` zones as faint context

**Panels (from `measurements.csv` + route files):**
- block count, row count
- per-row length + total row length (m)
- canopy area (m² and ha), inter-row area (m² and ha)
- blue & red route lengths (m)

**Interaction:**
- filter by `vineyard_id` and `row_id`
- click any object → popup / info panel with its IDs + attributes
  (`row_structure`, `interrow_cover`)

---

## 2. Stack decision (LOCKED)

**Plain HTML / CSS / JS + Leaflet 1.9.4 (CDN). No build step, no framework.**

Why (see also 20_DECISIONS): data is static files (GeoJSON + CSV) → no server
logic needed; static folder deploys anywhere in seconds (GitHub Pages / Netlify /
`python -m http.server`) with no build that can fail under the Sunday deadline;
engineering-quality score rewards the *pipeline* architecture, not the FE
framework. Next.js/Vite were considered and rejected as unnecessary risk.

- **Basemap:** Esri World Imagery (satellite) via Leaflet tileLayer.
- **CRS handling:** all geometry is reprojected EPSG:32635 → WGS84 (lon/lat) at
  export time, so Leaflet renders it directly over the satellite basemap. No
  in-browser reprojection, no custom CRS.
- Optional later: overlay the source orthomosaic as an image layer.

---

## 3. Directory layout

```
web/
├── index.html      map + sidebar (layer toggles, filter, measurements, info)
├── style.css       layout + colours
├── app.js          load GeoJSON/CSV, styling, popups, filters, panels
└── data/           <-- produced by pipeline/export_web_data.py (git-ignore or commit small)
    ├── canopy.geojson
    ├── rows.geojson
    ├── interrow.geojson
    ├── waste.geojson
    ├── passages.geojson      (reprojected context)
    ├── forbidden.geojson      (reprojected context)
    ├── start.geojson          (reprojected context)
    ├── study_area.geojson      (reprojected context)
    ├── measurements.csv
    ├── route.geojson          (optional; from Task 9 route planner)
    └── route_farmer.geojson   (optional; from Task 9 route planner)
```

---

## 4. Data contract (exact schemas the frontend expects)

All GeoJSON is **WGS84 (lon/lat)**, `FeatureCollection`.

| File | Geometry | Feature properties |
|------|----------|--------------------|
| `canopy.geojson` | Polygon | `vineyard_id`, `tile` |
| `rows.geojson` | LineString | `vineyard_id`, `row_id`, `row_structure`, `tile` |
| `interrow.geojson` | Polygon | `vineyard_id`, `interrow_cover`, `tile` |
| `waste.geojson` | Polygon (bbox as 4 corners) | `vineyard_id`, `tile` |
| `passages/forbidden/start/study_area.geojson` | as source | passthrough |
| `route.geojson` | LineString | `length_m` (blue / scored) |
| `route_farmer.geojson` | LineString | `length_m` (red / display) |

`measurements.csv` columns: `metric,vineyard_id,row_id,value,unit`
Rows emitted: `block_count`, `row_count`, `total_row_length`(m),
`total_canopy_area`(m2), `total_interrow_area`(m2), then per-block
`canopy_area`/`interrow_area`(m2), then per-row `row_length`(m).

**Frontend must degrade gracefully when any file is missing** (routes/waste may
be absent early). Absent layer → toggle disabled, panel shows "pending".

---

## 5. The exporter (data producer) — DONE

`pipeline/export_web_data.py` — reads a CVAT-1.1 `annotations.xml` + the per-tile
GeoTIFFs, converts pixels → EPSG:32635 (each tile's affine transform) → WGS84,
writes the GeoJSON contract + `measurements.csv` into `web/data/`. Reprojects the
`02_route/*.geojson` context files, and `route*.geojson` from repo root if present.

Run (defaults to the 2 example tiles):
```bash
python3 pipeline/export_web_data.py
# real run later:
python3 pipeline/export_web_data.py \
  --annotations <model_output.xml> --tiles 01_tiles --out web/data
```
**Verified output on example tiles:** canopy 650, rows 51, interrow 49, waste 0;
measurements blocks=2 rows=51 canopy=536m² interrow=4064m² row_len=1942m — matches
the reference numbers validated in `measurements.py`. Same script is reused on the
real 311-tile model output — no rewrite.

**Reuse contract:** the AI pipeline must emit a CVAT-1.1 `annotations.xml` (see
`pipeline/cvat_writer.py`) covering all annotated tiles; then this exporter turns
it into web data. Nothing frontend-specific leaks into the model code.

---

## 6. STEP-BY-STEP BUILD PLAN (mark each as you go)

Status keys: `[ ]` todo · `[~]` in progress · `[x]` done

- [x] **S0. Decide stack** → plain HTML/CSS/JS + Leaflet (section 2).
- [x] **S1. Exporter** `pipeline/export_web_data.py` → `web/data/*` (section 5).
- [x] **S2. HTML shell** `web/index.html` — map div + sidebar (layers, filter,
      measurements table, selection info). Leaflet via CDN.
- [x] **S3. CSS** `web/style.css` — dark sidebar + full-height map split layout.
- [x] **S4. app.js core** — init map, Esri satellite basemap, fetch all `data/*`
      with graceful 404 (returns null → layer "pending"), fitBounds to loaded data.
- [x] **S5. Layer rendering + styling** — interrow(orange)/canopy(green)/rows(blue)/
      waste(red)/inspector route(blue solid)/farmer route(red dashed)/START(yellow dot)/
      passages(faint cyan)/forbidden(faint purple).
- [x] **S6. Layer toggles** — checkbox + colour swatch + feature count per layer;
      absent layers shown disabled as "pending".
- [x] **S7. Popups** — click object → label + vineyard_id/row_id/row_structure/
      interrow_cover/length_m/tile (only non-empty fields).
- [x] **S8. Filters** — vineyard_id + row_id dropdowns populated from data; block
      filter constrains all filterable layers, row filter constrains the rows layer.
- [x] **S9. Measurements panel** — parses `measurements.csv`, renders totals
      (blocks, rows, row length, canopy m²+ha, interrow m²+ha) + per-block canopy +
      route lengths (blue/red, "pending" until route planner emits them).
- [x] **S10. Serve + verify** — `python3 -m http.server 8765` in `web/`; all routes
      200; coords confirmed WGS84 at the site (lon≈28.709, lat≈47.122).
- [ ] **S11. Visual screenshot in a browser** (do on a machine with a display).
- [~] **S12. Deploy** — GitHub Actions workflow `.github/workflows/pages.yml` added
      (deploys `web/` on push to main/user-interface). **One-time manual step remains:**
      repo Settings → Pages → Source = "GitHub Actions". Then the run publishes and
      prints the live URL → put it in `README.md`. If the `github-pages` environment
      is restricted to the default branch, merge to `main` or run the workflow from
      `main` (workflow_dispatch).
- [ ] **S13. Swap to real data** — rerun exporter on model output + 311 tiles;
      re-verify; interface needs no code change.

**How to run locally:** `cd web && python3 -m http.server 8765` → open
`http://localhost:8765/`.

---

## 7. Decisions (append-only)

- **2026-09-26** Stack = plain HTML/CSS/JS + Leaflet (no build). Basemap = Esri
  World Imagery. Reproject to WGS84 at export time (not in browser).
- **2026-09-26** Two routes rendered (blue inspector = scored `route.geojson`,
  red farmer = `route_farmer.geojson`), per mentor Q&A in `20_DECISIONS.md`.
- **2026-09-26** Build & demo against the 2 reference example tiles' annotations
  (only georeferenced data present on this machine); exporter reused as-is on the
  real 311-tile model output.
- **2026-09-26** View constraints (app.js top-of-file constants):
  - **Hard zoom cap** `MAX_ZOOM=19` (Esri imagery runs out past ~z19). Soft
    alternative: raise `MAX_ZOOM`, keep `MAX_NATIVE_ZOOM=19` → blurry-but-never-blank.
  - **Pan/zoom-out lock:** `setMaxBounds(bounds.pad(0.3))` + `minZoom = fitZoom-1`,
    both derived from the loaded data extent → **auto-expands** when real 311-tile
    data replaces the examples (no code change). `maxBoundsViscosity=0.85`.
    Rationale: single-vineyard field tool — no reason to pan to the rest of the world.

---

## 8. Findings / gotchas (append-only)

- On THIS machine the 311 tiles (`01_tiles/`) and source orthomosaic (`04_source/`)
  are NOT present — only the 2 example tiles in `05_examples/...`. Full-dataset
  export must run where the tiles live.
- System Python 3.9.6 has rasterio 1.4.3 / shapely 2.0.7 / pyproj 3.6.1 installed
  (no venv on this machine). `explore_tiles.py` has an import-time `mkdir` on a
  hardcoded `/Users/luka-sap/...` path → do NOT `import explore_tiles`; the
  exporter re-implements CVAT parsing standalone.
- Example tiles contain 0 waste → `waste.geojson` is an empty FeatureCollection;
  frontend must handle empty layers.

---

## 9. Next steps (keep current)

1. **S11** — open in a browser on a machine with a display; screenshot for README.
2. **S12** — deploy (GitHub Pages) and put the live link in `README.md`.
3. **S13** — when model output + routes exist, rerun the exporter — no frontend change.
4. Route layers currently show "pending" (Task 9 not built). They light up
   automatically once `route.geojson` / `route_farmer.geojson` land at repo root
   and the exporter is rerun.

## 10. Status: FRONTEND BUILT & VERIFIED (data-serving, 2026-09-26)

`web/{index.html,style.css,app.js}` + `web/data/*` complete. Verified against the
2 example tiles: canopy 650, rows 51, interrow 49, waste 0 features; all files
serve HTTP 200; geometry is correct WGS84 at the site. Remaining: visual
screenshot, deploy, and swap in real model output.
