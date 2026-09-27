/* Vineyard AI — field map. Plain Leaflet, static GeoJSON/CSV from ./data/.
   All geometry is WGS84 (reprojected from EPSG:32635 by pipeline/export_web_data.py). */

const DATA = "data/";

// ── view constraints ─────────────────────────────────────────────────────────
// Esri World Imagery has tiles up to ~z19 in rural areas; past that = blank tiles.
// MAX_ZOOM = hard cap (can't zoom past imagery). To allow zooming further with
// blurry-but-never-blank imagery instead, raise MAX_ZOOM and keep MAX_NATIVE_ZOOM=19.
const MAX_ZOOM = 21; // cap zoom-in at ~5 m scale (z21 = native 5 cm/px, no upscaling)
const MAX_NATIVE_ZOOM = 19; // last zoom level Esri actually has tiles for (upscaled beyond)
const MIN_ZOOM_MARGIN = 0; // levels you may zoom OUT past the data-fit zoom (0 = no further out than the full extent)
const DEFAULT_ZOOM_BOOST = 2; // open this many levels closer than the full-extent fit
const BOUNDS_PAD = 0.3; // pan slack around the data extent (fraction of extent)
const MAX_BOUNDS_VISCOSITY = 0.85; // 0=soft edge, 1=hard wall when panning to the edge

// ── attribute palettes (scored attributes get their own colours) ───────────────
const STRUCTURE_PALETTE = {
  // row_structure — regular = the rows' base blue (matches toggle, distinct from canopy green)
  regular: "#4a9eff",
  disrupted: "#ff851b",
  unassessable: "#aaaaaa",
  "": "#4a9eff",
};
const COVER_PALETTE = {
  // interrow_cover
  bare_soil: "#c2925b",
  vegetation: "#2ecc40",
  mixed: "#ffdc00",
  unassessable: "#888888",
  "": "#ff8c00",
};

// ── basemaps ───────────────────────────────────────────────────────────────
const map = L.map("map", {
  zoomControl: true,
  maxZoom: MAX_ZOOM,
  maxBoundsViscosity: MAX_BOUNDS_VISCOSITY,
}).setView([47.123, 28.707], 16);

const satellite = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  {
    maxZoom: MAX_ZOOM,
    maxNativeZoom: MAX_NATIVE_ZOOM,
    attribution: "Imagery © Esri",
  },
);
const streets = L.tileLayer(
  "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  { maxZoom: MAX_ZOOM, maxNativeZoom: 19, attribution: "© OpenStreetMap" },
);
const blank = L.layerGroup();

// Our own 2.5 cm/px orthomosaic, pre-rendered to an XYZ pyramid by
// pipeline/build_imagery_tiles.py. Transparent outside the survey → sits on top
// of the satellite basemap as an overlay. Sharp well past Esri's z19 ceiling.
const ORTHO_MAXNATIVE = 21; // deepest zoom the pyramid was generated for
const ortho = L.tileLayer("data/imagery/{z}/{x}/{y}.png", {
  maxZoom: MAX_ZOOM,
  maxNativeZoom: ORTHO_MAXNATIVE,
  minNativeZoom: 13,
  zIndex: 250,
  attribution: "Orthomosaic © 3DATA COLLECT (CC BY 4.0)",
});
satellite.addTo(map);
ortho.addTo(map);
L.control
  .layers(
    { Satellite: satellite, Streets: streets, None: blank },
    { "Orthomosaic (2.5 cm)": ortho },
    { position: "topright", collapsed: true },
  )
  .addTo(map);

// scale bar
L.control
  .scale({ metric: true, imperial: false, position: "topright" })
  .addTo(map);

map.attributionControl.setPosition("bottomright");

// ── layer catalogue (order = draw order / legend order) ──────────────────────
// kind: polygon | line | route | point | context
const LAYERS = [
  {
    key: "interrow",
    file: "interrow.geojson",
    kind: "polygon",
    label: "Inter-row areas",
    color: "#ff8c00",
    fill: 0.2,
    filterable: true,
    on: true,
    attrKey: "interrow_cover",
    palette: COVER_PALETTE,
  },
  {
    key: "canopy",
    file: "canopy.geojson",
    kind: "polygon",
    label: "Canopy (vines)",
    color: "#2ecc40",
    fill: 0.45,
    filterable: true,
    on: true,
  },
  // "rows" is a data-only source (hidden from the toggle list) so stats, filters,
  // route targets and the legend keep working off store.rows. The two entries below
  // are the visible, independently-toggleable render layers split by row_structure.
  {
    key: "rows",
    file: "rows.geojson",
    kind: "line",
    label: "Rows",
    color: "#4a9eff",
    weight: 2,
    on: false,
    hidden: true,
    attrKey: "row_structure",
    palette: STRUCTURE_PALETTE,
  },
  {
    key: "rows_regular",
    file: "rows.geojson",
    kind: "line",
    label: "Rows — regular",
    color: "#4a9eff",
    weight: 2,
    filterable: true,
    on: true,
    subFilter: (p) => p.row_structure !== "disrupted",
  },
  {
    key: "rows_disrupted",
    file: "rows.geojson",
    kind: "line",
    label: "Rows — disrupted",
    color: "#ff851b",
    weight: 3,
    filterable: true,
    on: true,
    subFilter: (p) => p.row_structure === "disrupted",
  },
  {
    key: "waste",
    file: "waste.geojson",
    kind: "polygon",
    label: "Waste",
    color: "#ff4136",
    fill: 0.35,
    filterable: true,
    on: true,
  },
  {
    key: "route",
    file: "route.geojson",
    kind: "route",
    label: "Inspector route (blue)",
    color: "#0074d9",
    weight: 4,
    on: true,
  },
  {
    key: "route_farmer",
    file: "route_farmer.geojson",
    kind: "route",
    label: "Farmer route (red)",
    color: "#e0245e",
    weight: 4,
    dash: "6 6",
    on: true,
  },
  {
    key: "passages",
    file: "passages.geojson",
    kind: "context",
    label: "Passages",
    color: "#7fdbff",
    fill: 0.08,
    weight: 1,
    on: false,
  },
  {
    key: "forbidden",
    file: "forbidden.geojson",
    kind: "context",
    label: "Forbidden zones",
    color: "#b10dc9",
    fill: 0.12,
    weight: 1,
    on: false,
  },
  {
    key: "start",
    file: "start.geojson",
    kind: "point",
    label: "START",
    color: "#ffdc00",
    on: true,
  },
];

const store = {}; // key -> { cfg, data, layer, count }
let filterBlock = "";
let filterRow = "";
let savedView = null; // {center, zoom} snapshot of the initial view, for reset/"All"
let dataBounds = null;

// route-start picker state
let defaultStart = null; // {lat,lng} organizer-supplied START (the scored one)
let startMarker = null; // the single yellow START dot (moves when you change it)
let movedStart = false; // true once the user has moved it off the default
let picking = false;
let vineyardGeom = null; // study-area polygon: START must be inside it
let forbiddenFeatures = []; // forbidden zones: START must NOT be inside any
let canopyFeatures = []; // vine canopies: START must NOT be on a vine
let noGoLayer = null; // red overlay of where the START cannot go (shown while picking)
let hintTimer = null;

// nav-graph + in-browser route solver state
let nav = null; // {nodes:[[lng,lat]], edges, start_node}
let navAdj = null; // adjacency: navAdj[i] = [[neighbor, weight_m], ...]
let measRows = []; // cached measurements.csv rows (to re-render route lengths)

// route persona panel
const WALK_KMH = 4; // problem statement's assumed walking speed
let routeMode = "route"; // "route" (inspector) | "route_farmer" (farmer)
let routeStats = null; // { route:{...,nInsp,nWaste}, route_farmer:{...} }

// ── helpers ──────────────────────────────────────────────────────────────────
async function fetchJSON(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

function matchFilter(cfg, props) {
  if (!cfg.filterable) return true;
  if (filterBlock && props.vineyard_id !== filterBlock) return false;
  // row filter only constrains the rows layer (others carry no row_id)
  if (filterRow && cfg.key.startsWith("rows") && props.row_id !== filterRow)
    return false;
  return true;
}

// turn snake_case codes ("bare_soil") into readable text ("Bare soil")
function prettyValue(v) {
  if (v === undefined || v === null || v === "") return v;
  return String(v)
    .replace(/_/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());
}

// drop the survey prefix / .tif extension from a tile name so a clicked object
// shows a clean grid ref ("siret3_r021_c012.tif" -> "Row 021, Col 012")
function prettyTile(t) {
  if (!t) return t;
  const m = String(t).match(/r(\d+)_c(\d+)/i);
  return m ? `Row ${m[1]}, Col ${m[2]}` : String(t).replace(/\.tif$/i, "");
}

function popupHTML(cfg, props) {
  const rows = [];
  const add = (label, v, pretty) => {
    if (v !== undefined && v !== null && v !== "")
      rows.push(
        `<span class="k">${label}:</span> <b>${pretty ? prettyValue(v) : v}</b>`,
      );
  };
  rows.push(`<b>${cfg.label}</b>`);
  add("Vineyard block", props.vineyard_id);
  add("Row", props.row_id);
  add("Row structure", props.row_structure, true);
  add("Ground cover", props.interrow_cover, true);
  add(
    "Length",
    props.length_m ? Number(props.length_m).toFixed(1) + " m" : undefined,
  );
  add("Tile", prettyTile(props.tile));
  return rows.join("<br>");
}

// update the floating Selection panel with a clicked object's details and show it
function showInfo(cfg, props) {
  const el = document.getElementById("info");
  const box = document.getElementById("info-box");
  if (el) el.innerHTML = popupHTML(cfg, props);
  if (box) box.style.display = "";
}

function colorFor(cfg, feature) {
  if (cfg.palette && feature) {
    const v = (feature.properties || {})[cfg.attrKey] || "";
    return cfg.palette[v] || cfg.color;
  }
  return cfg.color;
}

function styleFor(cfg, feature) {
  const color = colorFor(cfg, feature);
  if (cfg.kind === "line" || cfg.kind === "route") {
    return {
      color,
      weight: cfg.weight || 3,
      opacity: 0.95,
      dashArray: cfg.dash,
    };
  }
  return {
    color,
    weight: cfg.weight || 1,
    fillColor: color,
    fillOpacity: cfg.fill != null ? cfg.fill : 0.3,
    opacity: 0.9,
  };
}

function buildLayer(cfg, data) {
  if (cfg.kind === "point") {
    // single movable circleMarker (the START dot) — not a geoJSON group, so it
    // can be repositioned with setLatLng by the start picker
    const f = data.features[0];
    const c = f.geometry.coordinates;
    return L.circleMarker([c[1], c[0]], {
      radius: 8,
      color: "#000",
      weight: 2,
      fillColor: cfg.color,
      fillOpacity: 1,
    }).bindPopup(popupHTML(cfg, f.properties || {}));
  }
  return L.geoJSON(data, {
    filter: (f) =>
      matchFilter(cfg, f.properties || {}) &&
      (!cfg.subFilter || cfg.subFilter(f.properties || {})),
    style: (f) => styleFor(cfg, f),
    onEachFeature: (f, l) =>
      l.on("click", () => showInfo(cfg, f.properties || {})),
  });
}

function rebuildFilterable() {
  for (const cfg of LAYERS) {
    if (!cfg.filterable) continue;
    const s = store[cfg.key];
    if (!s || !s.data) continue;
    const wasOn = map.hasLayer(s.layer);
    map.removeLayer(s.layer);
    s.layer = buildLayer(cfg, s.data);
    if (wasOn) s.layer.addTo(map);
  }
}

// ── UI: layer toggles ──────────────────────────────────────────────────────────
function renderToggles() {
  const box = document.getElementById("layer-toggles");
  box.innerHTML = "";
  for (const cfg of LAYERS) {
    if (cfg.hidden) continue;
    const s = store[cfg.key];
    const present = s && s.count > 0;
    const row = document.createElement("label");
    row.className = "toggle" + (present ? "" : " disabled");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!(present && s.layer && map.hasLayer(s.layer));
    cb.disabled = !present;
    cb.onchange = () => {
      if (!s || !s.layer) return;
      if (cb.checked) s.layer.addTo(map);
      else map.removeLayer(s.layer);
    };

    const sw = document.createElement("span");
    sw.className =
      "swatch" + (cfg.kind === "line" || cfg.kind === "route" ? " line" : "");
    sw.style.background = cfg.color;

    const name = document.createElement("span");
    name.textContent = cfg.label;

    const cnt = document.createElement("span");
    cnt.className = "count";
    cnt.textContent = present ? s.count : "0";

    row.append(cb, sw, name, cnt);
    box.appendChild(row);
  }
}

// ── UI: legend (attribute colour keys, with live counts) ─────────────────────
function renderLegend() {
  const box = document.getElementById("legend");
  box.innerHTML = "";
  const section = (title, cfgKey, palette, order) => {
    const s = store[cfgKey];
    if (!s || !s.data || !s.count) return;
    const counts = {};
    for (const f of s.data.features) {
      const v =
        (f.properties || {})[LAYERS.find((l) => l.key === cfgKey).attrKey] ||
        "None";
      counts[v] = (counts[v] || 0) + 1;
    }
    const h = document.createElement("div");
    h.className = "legend-title";
    h.textContent = title;
    box.appendChild(h);
    const addRow = (key, color) => {
      const row = document.createElement("div");
      row.className = "legend-row";
      row.innerHTML =
        `<span class="swatch" style="background:${color}"></span>` +
        `<span>${prettyValue(key)}</span><span class="count">${counts[key]}</span>`;
      box.appendChild(row);
    };
    for (const key of order) {
      if (!(key in counts)) continue;
      addRow(key, palette[key] || palette[""]);
      delete counts[key];
    }
    for (const key of Object.keys(counts)) addRow(key, palette[""]); // unexpected values
  };
  section("Rows", "rows", STRUCTURE_PALETTE, [
    "regular",
    "disrupted",
    "unassessable",
  ]);
  section("Ground cover", "interrow", COVER_PALETTE, [
    "bare_soil",
    "mixed",
    "vegetation",
    "unassessable",
  ]);
  if (!box.children.length)
    box.innerHTML = '<div class="muted">No attribute layers loaded</div>';
}

// ── UI: filters ─────────────────────────────────────────────────────────────
const natSort = (a, b) => a.localeCompare(b, undefined, { numeric: true });

// lightweight custom dropdown with a fixed-height, scrollable menu (native <select>
// popups can't be height-capped). opts = [{value, label}].
function makeDropdown(rootId, onChange) {
  const root = document.getElementById(rootId);
  const btn = root.querySelector(".dd-btn");
  const menu = root.querySelector(".dd-menu");
  let value = "";
  function setOptions(opts) {
    menu.innerHTML = "";
    for (const o of opts) {
      const el = document.createElement("div");
      el.className = "dd-opt" + (o.value === value ? " sel" : "");
      el.textContent = o.label;
      el.onclick = (e) => {
        e.stopPropagation();
        value = o.value;
        btn.textContent = o.label;
        root.classList.remove("open");
        menu
          .querySelectorAll(".dd-opt")
          .forEach((x) => x.classList.toggle("sel", x === el));
        onChange(value);
      };
      menu.appendChild(el);
    }
  }
  btn.onclick = (e) => {
    e.stopPropagation();
    document
      .querySelectorAll(".dd.open")
      .forEach((d) => d !== root && d.classList.remove("open"));
    root.classList.toggle("open");
  };
  return {
    setOptions,
    set(v, label) {
      value = v;
      btn.textContent = label;
    },
  };
}
document.addEventListener("click", () =>
  document
    .querySelectorAll(".dd.open")
    .forEach((d) => d.classList.remove("open")),
);

let ddBlock = null,
  ddRow = null;
function populateFilters() {
  const blocks = new Set();
  const blockRows = {}; // vineyard_id -> Set(row_id)
  for (const key of ["canopy", "rows", "interrow", "waste"]) {
    const s = store[key];
    if (!s || !s.data) continue;
    for (const f of s.data.features) {
      const p = f.properties || {};
      if (p.vineyard_id) blocks.add(p.vineyard_id);
      if (p.vineyard_id && p.row_id)
        (blockRows[p.vineyard_id] = blockRows[p.vineyard_id] || new Set()).add(
          p.row_id,
        );
    }
  }
  const opt = (v) => ({ value: v, label: v || "All" });

  ddBlock = makeDropdown("dd-block", (v) => {
    filterBlock = v;
    filterRow = "";
    ddRow.set("", "All");
    ddRow.setOptions([
      opt(""),
      ...(v && blockRows[v] ? [...blockRows[v]].sort(natSort).map(opt) : []),
    ]);
    rebuildFilterable();
    if (filterBlock) zoomToFeatures((p) => p.vineyard_id === filterBlock);
    else resetView(); // back to "All" → restore the initial view
  });
  ddRow = makeDropdown("dd-row", (v) => {
    filterRow = v;
    rebuildFilterable();
    if (filterRow) zoomToFeatures((p) => p.row_id === filterRow);
    else if (filterBlock) zoomToFeatures((p) => p.vineyard_id === filterBlock);
  });

  ddBlock.setOptions([opt(""), ...[...blocks].sort(natSort).map(opt)]);
  ddRow.setOptions([opt("")]); // stays empty until a vineyard is chosen
}

// pan/zoom the map to the extent of the annotation features matching `pred`
function zoomToFeatures(pred) {
  const feats = [];
  for (const key of ["canopy", "rows", "interrow", "waste"]) {
    const s = store[key];
    if (!s || !s.data) continue;
    for (const f of s.data.features)
      if (f.geometry && pred(f.properties || {})) feats.push(f);
  }
  if (!feats.length) return;
  const b = L.geoJSON({
    type: "FeatureCollection",
    features: feats,
  }).getBounds();
  if (b.isValid()) map.fitBounds(b, { padding: [20, 20] });
}

// restore the exact initial view captured on load (snapshot below)
function resetView() {
  if (savedView) {
    map.setView(savedView.center, savedView.zoom);
    return;
  }
  if (!dataBounds || !dataBounds.isValid()) return;
  map.fitBounds(dataBounds, { padding: [30, 30] });
  const fitZoom = map.getBoundsZoom(dataBounds);
  map.setZoom(Math.min(MAX_ZOOM, fitZoom + DEFAULT_ZOOM_BOOST));
}

function fillSelect(id, values) {
  const sel = document.getElementById(id);
  for (const v of values) {
    const o = document.createElement("option");
    o.value = v;
    o.textContent = v;
    sel.appendChild(o);
  }
}

// ── stats dashboard ──────────────────────────────────────────────────────────
function tally(cfgKey, attrKey) {
  const s = store[cfgKey];
  const out = {};
  if (!s || !s.data) return out;
  for (const f of s.data.features) {
    const v = (f.properties || {})[attrKey] || "None";
    out[v] = (out[v] || 0) + 1;
  }
  return out;
}

function renderStats() {
  const tbody = document.querySelector("#stats tbody");
  tbody.innerHTML = "";
  const add = (label, value, cls = "") => {
    const tr = document.createElement("tr");
    if (cls) tr.className = cls;
    tr.innerHTML = `<td>${label}</td><td>${value}</td>`;
    tbody.appendChild(tr);
  };
  const head = (t) => add(t, "", "head");

  const rs = tally("rows", "row_structure");
  head("Row structure");
  for (const k of ["regular", "disrupted", "unassessable"])
    add(prettyValue(k), rs[k] || 0);

  const cov = tally("interrow", "interrow_cover");
  head("Ground cover");
  for (const k of ["bare_soil", "mixed", "vegetation", "unassessable"])
    add(prettyValue(k), cov[k] || 0);

  head("Object counts");
  add("Canopy polygons", (store.canopy && store.canopy.count) || 0);
  add("Rows", (store.rows && store.rows.count) || 0);
  add("Inter-row areas", (store.interrow && store.interrow.count) || 0);
  add("Waste boxes", (store.waste && store.waste.count) || 0);

  // per-block object tallies
  const perBlock = {}; // vid -> {canopy, rows:Set(row_id), interrow, waste}
  const bump = (key, prop) => {
    const s = store[key];
    if (!s || !s.data) return;
    for (const f of s.data.features) {
      const p = f.properties || {};
      const vid = p.vineyard_id || "None";
      perBlock[vid] = perBlock[vid] || {
        canopy: 0,
        rows: new Set(),
        interrow: 0,
        waste: 0,
      };
      if (key === "rows") perBlock[vid].rows.add(p.row_id);
      else perBlock[vid][prop]++;
    }
  };
  bump("canopy", "canopy");
  bump("rows");
  bump("interrow", "interrow");
  bump("waste", "waste");
  const vids = Object.keys(perBlock).sort();
  if (vids.length) {
    head("Per block (canopy / rows / inter-row / waste)");
    for (const vid of vids) {
      const b = perBlock[vid];
      add(vid, `${b.canopy} / ${b.rows.size} / ${b.interrow} / ${b.waste}`);
    }
  }
}

// ── measurements panel ────────────────────────────────────────────────────────
function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  const header = lines.shift().split(",");
  return lines.map((l) => {
    const c = l.split(",");
    return Object.fromEntries(header.map((h, i) => [h, c[i]]));
  });
}

function routeLength(key) {
  const s = store[key];
  if (!s || !s.data || !s.data.features || !s.data.features.length) return null;
  const p = s.data.features[0].properties || {};
  if (p.length_m != null) return Number(p.length_m);
  return null;
}

function renderMeasurements(rows) {
  const tbody = document.querySelector("#measurements tbody");
  tbody.innerHTML = "";
  const get = (m) => rows.find((r) => r.metric === m);
  const num = (v, d = 0) =>
    v == null
      ? "—"
      : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

  const add = (label, value, cls = "") => {
    const tr = document.createElement("tr");
    if (cls) tr.className = cls;
    tr.innerHTML = `<td>${label}</td><td>${value}</td>`;
    tbody.appendChild(tr);
  };
  const head = (t) => add(t, "", "head");

  if (rows.length) {
    const blocks = get("block_count"),
      rc = get("row_count");
    const rowlen = get("total_row_length"),
      can = get("total_canopy_area"),
      inter = get("total_interrow_area");
    head("Totals");
    add("Blocks", num(blocks && blocks.value), "big");
    add("Rows", num(rc && rc.value), "big");
    add("Total row length", num(rowlen && rowlen.value) + " m");
    add(
      "Canopy area",
      num(can && can.value) +
        " m² (" +
        num((can && can.value) / 1e4, 3) +
        " ha)",
    );
    add(
      "Inter-row area",
      num(inter && inter.value) +
        " m² (" +
        num((inter && inter.value) / 1e4, 3) +
        " ha)",
    );

    const perBlock = rows.filter((r) => r.metric === "canopy_area");
    if (perBlock.length) {
      head("Per block — canopy m²");
      for (const r of perBlock) add(r.vineyard_id || "None", num(r.value));
    }
  } else {
    add("measurements.csv not found", "");
  }
  // route lengths now live in the "Route" section (renderRoutePanel)
}

// ── map controls: reset view + zoom indicator ─────────────────────────────────
function addControls() {
  const Reset = L.Control.extend({
    options: { position: "topleft" },
    onAdd() {
      const b = L.DomUtil.create("a", "leaflet-bar reset-view");
      b.href = "#";
      b.title = "Reset view";
      b.innerHTML = "⤢";
      L.DomEvent.on(b, "click", (e) => {
        L.DomEvent.stop(e);
        resetView();
      });
      return b;
    },
  });
  map.addControl(new Reset());

  // floating legend on the map (renderLegend fills #legend)
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const d = L.DomUtil.create("div", "map-legend");
    d.innerHTML =
      '<div class="map-legend-title">Legend</div><div id="legend"></div>';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.disableScrollPropagation(d);
    return d;
  };
  legend.addTo(map);

  // floating selection info — hidden until an object is clicked, closable (added
  // after legend → sits above it in the corner)
  const info = L.control({ position: "bottomright" });
  info.onAdd = () => {
    const d = L.DomUtil.create("div", "map-info");
    d.id = "info-box";
    d.style.display = "none";
    d.innerHTML =
      '<div class="map-info-head"><span class="map-legend-title">Selection</span>' +
      '<button type="button" class="map-info-close" title="Close">✕</button></div>' +
      '<div id="info" class="info"></div>';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.disableScrollPropagation(d);
    d.querySelector(".map-info-close").onclick = () => {
      d.style.display = "none";
    };
    return d;
  };
  info.addTo(map);

  // floating Route-start panel (bottom-left; zoom indicator prepends above it)
  const startCtl = L.control({ position: "bottomleft" });
  startCtl.onAdd = () => {
    const d = L.DomUtil.create("div", "map-start");
    d.innerHTML =
      '<button id="pick-start" class="btn">📍 Change start point</button>' +
      '<div id="start-hint" class="hint" style="display:none">Click inside the vineyard to place the start · Esc to cancel</div>' +
      '<div id="start-coords" class="coords"></div>' +
      '<button id="reset-start" class="btn btn-sub" style="display:none">↺ Reset to default</button>';
    L.DomEvent.disableClickPropagation(d);
    L.DomEvent.disableScrollPropagation(d);
    return d;
  };
  startCtl.addTo(map);

  const zoomBox = L.control({ position: "bottomleft" });
  zoomBox.onAdd = () => {
    const d = L.DomUtil.create("div", "zoom-indicator");
    const upd = () => {
      d.textContent = "Zoom " + map.getZoom();
    };
    map.on("zoomend", upd);
    upd();
    return d;
  };
  zoomBox.addTo(map);
}

// ── route-start picker ────────────────────────────────────────────────────────
// Point-in-polygon (ray casting) on [lng,lat] to keep the START inside the
// vineyard/study area. Handles Polygon + MultiPolygon with holes.
function pointInRing(pt, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0],
      yi = ring[i][1],
      xj = ring[j][0],
      yj = ring[j][1];
    if (
      yi > pt[1] !== yj > pt[1] &&
      pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi
    )
      inside = !inside;
  }
  return inside;
}
function pointInPolygon(pt, poly) {
  if (!pointInRing(pt, poly[0])) return false;
  for (let k = 1; k < poly.length; k++)
    if (pointInRing(pt, poly[k])) return false;
  return true;
}
function geomContains(geom, pt) {
  if (!geom) return false;
  if (geom.type === "Polygon") return pointInPolygon(pt, geom.coordinates);
  if (geom.type === "MultiPolygon")
    return geom.coordinates.some((p) => pointInPolygon(pt, p));
  return false;
}
// valid = inside the study area, NOT in a forbidden zone, NOT on a vine canopy
function inVineyard(latlng) {
  const pt = [latlng.lng, latlng.lat];
  if (vineyardGeom && !geomContains(vineyardGeom, pt)) return false;
  for (const f of forbiddenFeatures)
    if (geomContains(f.geometry, pt)) return false;
  for (const f of canopyFeatures)
    if (geomContains(f.geometry, pt)) return false;
  return true;
}

// red overlay of everywhere the START may NOT go: the world outside the study
// area (study area punched out as a hole) + the forbidden zones on top.
function buildNoGoLayer() {
  const group = L.layerGroup();
  const holes = [];
  if (vineyardGeom && vineyardGeom.type === "Polygon") {
    holes.push(vineyardGeom.coordinates[0].map((c) => [c[1], c[0]]));
  } else if (vineyardGeom && vineyardGeom.type === "MultiPolygon") {
    for (const poly of vineyardGeom.coordinates)
      holes.push(poly[0].map((c) => [c[1], c[0]]));
  }
  const world = [
    [-89, -179],
    [-89, 179],
    [89, 179],
    [89, -179],
  ];
  L.polygon([world, ...holes], {
    stroke: false,
    fillColor: "#ff2d2d",
    fillOpacity: 0.3,
    interactive: false,
  }).addTo(group);
  const fd = store.forbidden && store.forbidden.data;
  if (fd) {
    L.geoJSON(fd, {
      style: {
        color: "#ff2d2d",
        weight: 1,
        fillColor: "#ff2d2d",
        fillOpacity: 0.45,
      },
      interactive: false,
    }).addTo(group);
  }
  const cd = store.canopy && store.canopy.data;
  if (cd) {
    L.geoJSON(cd, {
      style: { stroke: false, fillColor: "#ff2d2d", fillOpacity: 0.55 },
      interactive: false,
    }).addTo(group);
  }
  return group;
}

// While picking, hide every annotation layer (keep only imagery + the START dot)
// so the view is clean and a click can't land on an annotation popup. The layers
// that were visible are restored on exit.
let hiddenDuringPick = [];
function hideAnnotationsForPick() {
  hiddenDuringPick = [];
  for (const cfg of LAYERS) {
    if (cfg.key === "start") continue;
    const s = store[cfg.key];
    if (s && s.layer && map.hasLayer(s.layer)) {
      map.removeLayer(s.layer);
      hiddenDuringPick.push(cfg.key);
    }
  }
}
function restoreAnnotationsAfterPick() {
  for (const key of hiddenDuringPick) {
    const s = store[key];
    if (s && s.layer) s.layer.addTo(map);
  }
  hiddenDuringPick = [];
}

function flashHint(msg) {
  const h = document.getElementById("start-hint");
  h.textContent = msg;
  h.style.display = "block";
  h.classList.add("warn");
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => {
    h.classList.remove("warn");
    if (picking)
      h.textContent =
        "Click inside the vineyard to place the start · Esc to cancel";
    else h.style.display = "none";
  }, 1900);
}

function updateStartReadout() {
  const el = document.getElementById("start-coords");
  const ll = startMarker ? startMarker.getLatLng() : defaultStart;
  if (!ll) {
    el.textContent = "";
    return;
  }
  const tag = movedStart ? "Start point (moved)" : "Start point (default)";
  el.innerHTML = `<span class="k">${tag}</span><br>Lat ${ll.lat.toFixed(6)}, Lon ${ll.lng.toFixed(6)}`;
}

function onStartChanged() {
  updateStartReadout();
  document.getElementById("reset-start").style.display = movedStart
    ? ""
    : "none";
  solveRoutes(); // recompute blue/red routes from the new START (client-side)
}

// move the single yellow START dot; returns false if outside the vineyard
function moveStart(latlng, isReset) {
  if (!isReset && !inVineyard(latlng)) {
    flashHint("⚠ Place the start inside the vineyard area");
    return false;
  }
  startMarker.setLatLng(latlng);
  movedStart = !isReset;
  onStartChanged();
  return true;
}

function enterPick() {
  picking = true;
  const b = document.getElementById("pick-start");
  b.textContent = "✕ Cancel";
  b.classList.add("active");
  const h = document.getElementById("start-hint");
  h.style.display = "block";
  h.textContent =
    "Click inside the vineyard to place the start · Esc to cancel";
  map.closePopup();
  map.getContainer().classList.add("picking");
  hideAnnotationsForPick();
  renderToggles(); // uncheck the boxes to match the hidden layers
  if (noGoLayer) noGoLayer.addTo(map); // red = can't place here
  map.on("click", onPickClick);
  document.addEventListener("keydown", onPickKey);
}
function exitPick() {
  picking = false;
  const b = document.getElementById("pick-start");
  b.textContent = "📍 Change start point";
  b.classList.remove("active");
  document.getElementById("start-hint").style.display = "none";
  map.getContainer().classList.remove("picking");
  if (noGoLayer) map.removeLayer(noGoLayer);
  restoreAnnotationsAfterPick();
  renderToggles(); // re-sync toggle checkboxes to the restored layer state
  map.off("click", onPickClick);
  document.removeEventListener("keydown", onPickKey);
}
function onPickKey(e) {
  if (e.key === "Escape") exitPick();
}
function onPickClick(e) {
  if (!inVineyard(e.latlng)) {
    flashHint("⚠ Place the start inside the vineyard area");
    return;
  }
  exitPick(); // restore layers first, then recompute so toggles stay in sync
  moveStart(e.latlng, false);
}

function resetStart() {
  if (defaultStart) moveStart(defaultStart, true);
}

async function setupStartPicker() {
  const sd = store.start && store.start.data;
  if (sd && sd.features && sd.features.length) {
    const c = sd.features[0].geometry.coordinates;
    defaultStart = L.latLng(c[1], c[0]);
  } else {
    defaultStart = L.latLng(47.1230335, 28.7073776);
  }
  const sa = await fetchJSON(DATA + "study_area.geojson");
  if (sa && sa.features && sa.features.length)
    vineyardGeom = sa.features[0].geometry;
  const fd = store.forbidden && store.forbidden.data;
  forbiddenFeatures = fd && fd.features ? fd.features : [];
  const cd = store.canopy && store.canopy.data;
  canopyFeatures = cd && cd.features ? cd.features : [];
  noGoLayer = buildNoGoLayer();

  // the ONE start marker = the yellow dot the user already saw (store.start.layer)
  startMarker = (store.start && store.start.layer) || null;
  document.getElementById("pick-start").onclick = () =>
    picking ? exitPick() : enterPick();
  document.getElementById("reset-start").onclick = () => resetStart();
  updateStartReadout();
}

// ── in-browser route solver ───────────────────────────────────────────────────
// Loads the pre-exported nav-graph (pipeline/export_navgraph.py) and re-solves the
// walking route for any START, entirely client-side: snap START + targets to graph
// nodes → Dijkstra → nearest-neighbour + 2-opt TSP → stitch. Mirrors the Python
// planner's algorithm so the interactive route matches the scored one. When Lane A's
// inter-row lands, only navgraph.json is regenerated — no code change here.
async function loadNavGraph() {
  const g = await fetchJSON(DATA + "navgraph.json");
  if (!g || !g.nodes || !g.edges) return;
  nav = g;
  navAdj = Array.from({ length: g.nodes.length }, () => []);
  for (const [i, j, w] of g.edges) {
    navAdj[i].push([j, w]);
    navAdj[j].push([i, w]);
  }
}

// binary min-heap of (node, dist) for Dijkstra
class MinHeap {
  constructor() {
    this.a = [];
  }
  get size() {
    return this.a.length;
  }
  push(node, d) {
    const a = this.a;
    a.push([d, node]);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p][0] <= a[i][0]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop() {
    const a = this.a,
      top = a[0],
      last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      const n = a.length;
      for (;;) {
        let l = 2 * i + 1,
          r = l + 1,
          s = i;
        if (l < n && a[l][0] < a[s][0]) s = l;
        if (r < n && a[r][0] < a[s][0]) s = r;
        if (s === i) break;
        [a[s], a[i]] = [a[i], a[s]];
        i = s;
      }
    }
    return top; // [d, node]
  }
}

function dijkstra(src) {
  const n = nav.nodes.length;
  const dist = new Float64Array(n).fill(Infinity);
  const prev = new Int32Array(n).fill(-1);
  dist[src] = 0;
  const h = new MinHeap();
  h.push(src, 0);
  while (h.size) {
    const [du, u] = h.pop();
    if (du > dist[u]) continue;
    for (const [v, w] of navAdj[u]) {
      const nd = du + w;
      if (nd < dist[v]) {
        dist[v] = nd;
        prev[v] = u;
        h.push(v, nd);
      }
    }
  }
  return { dist, prev };
}

function nodePath(prev, dst) {
  // node indices dst..src via prev
  const out = [];
  let u = dst;
  while (u !== -1) {
    out.push(u);
    u = prev[u];
  }
  return out.reverse();
}

function snapNode(ll) {
  const cs = Math.cos((ll.lat * Math.PI) / 180);
  let best = -1,
    bd = Infinity;
  for (let i = 0; i < nav.nodes.length; i++) {
    const dlng = (nav.nodes[i][0] - ll.lng) * cs;
    const dlat = nav.nodes[i][1] - ll.lat;
    const d = dlng * dlng + dlat * dlat;
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return best;
}

function haversine(a, b) {
  // a,b = [lat,lng] → metres
  const R = 6371000,
    rad = Math.PI / 180;
  const dlat = (b[0] - a[0]) * rad,
    dlng = (b[1] - a[1]) * rad;
  const s =
    Math.sin(dlat / 2) ** 2 +
    Math.cos(a[0] * rad) * Math.cos(b[0] * rad) * Math.sin(dlng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

// nearest-neighbour + 2-opt over an (n×n) distance matrix; index 0 = START, returns
// visiting order with START first and last
function tspOrder(D) {
  const n = D.length;
  if (n <= 1) return [0, 0];
  const seen = new Set([0]);
  const order = [0];
  let cur = 0;
  while (seen.size < n) {
    let best = -1,
      bd = Infinity;
    for (let j = 0; j < n; j++)
      if (!seen.has(j) && D[cur][j] < bd) {
        bd = D[cur][j];
        best = j;
      }
    order.push(best);
    seen.add(best);
    cur = best;
  }
  order.push(0);
  const len = (o) => {
    let s = 0;
    for (let i = 0; i < o.length - 1; i++) s += D[o[i]][o[i + 1]];
    return s;
  };
  let improved = true;
  while (improved) {
    improved = false;
    for (let i = 1; i < order.length - 2; i++)
      for (let k = i + 1; k < order.length - 1; k++) {
        const cand = order
          .slice(0, i)
          .concat(order.slice(i, k + 1).reverse(), order.slice(k + 1));
        if (len(cand) + 1e-9 < len(order)) {
          order.splice(0, order.length, ...cand);
          improved = true;
        }
      }
  }
  return order;
}

// solve one route: START + target latlngs → {latlngs:[[lat,lng]], length_m, visited}
function computeRoute(startLL, targetLLs) {
  if (!nav) return null;
  const termLL = [startLL, ...targetLLs];
  const termNode = termLL.map(snapNode);
  // dedupe terminals sharing a node (keep START at 0)
  const uniq = [];
  const seenNode = new Set();
  for (let i = 0; i < termNode.length; i++) {
    if (seenNode.has(termNode[i])) continue;
    seenNode.add(termNode[i]);
    uniq.push(i);
  }
  const nodes = uniq.map((i) => termNode[i]);
  const solved = nodes.map((s) => dijkstra(s));
  // reachable-from-START subset
  const d0 = solved[0].dist;
  const keep = [0];
  for (let a = 1; a < nodes.length; a++)
    if (isFinite(d0[nodes[a]])) keep.push(a);
  if (keep.length <= 1)
    return { latlngs: [[startLL.lat, startLL.lng]], length_m: 0, visited: 0, naive_m: 0 };

  const m = keep.length;
  const D = Array.from({ length: m }, () => new Float64Array(m));
  for (let a = 0; a < m; a++)
    for (let b = 0; b < m; b++) D[a][b] = solved[keep[a]].dist[nodes[keep[b]]];
  // "separate return trips" baseline (Visual Journey p.7): visit each target from
  // START and come back individually → 2 × Σ dist(START→target)
  let naive_m = 0;
  for (let a = 1; a < m; a++) naive_m += 2 * D[0][a];
  const order = tspOrder(D); // indices into keep

  // stitch node paths between consecutive terminals
  const seq = [];
  for (let i = 0; i < order.length - 1; i++) {
    const a = keep[order[i]],
      b = keep[order[i + 1]];
    let seg = nodePath(solved[a].prev, nodes[b]);
    if (seq.length && seg.length && seq[seq.length - 1] === seg[0])
      seg = seg.slice(1);
    for (const nd of seg) seq.push(nd);
  }
  const latlngs = [[startLL.lat, startLL.lng]];
  for (const nd of seq) latlngs.push([nav.nodes[nd][1], nav.nodes[nd][0]]);
  latlngs.push([startLL.lat, startLL.lng]); // return to START
  let length = 0;
  for (let i = 0; i < latlngs.length - 1; i++)
    length += haversine(latlngs[i], latlngs[i + 1]);
  return { latlngs, length_m: length, visited: m - 1, naive_m };
}

// targets from data already on the map
function midOfLine(coords) {
  const m = coords[Math.floor(coords.length / 2)];
  return L.latLng(m[1], m[0]);
}
function inspectionTargets() {
  const s = store.rows,
    out = [];
  if (!s || !s.data) return out;
  for (const f of s.data.features) {
    if ((f.properties || {}).row_structure !== "disrupted") continue;
    const g = f.geometry;
    if (!g) continue;
    const c =
      g.type === "LineString"
        ? g.coordinates
        : g.type === "MultiLineString"
          ? g.coordinates[0]
          : null;
    if (c && c.length) out.push(midOfLine(c));
  }
  return out;
}
function wasteTargets() {
  const s = store.waste,
    out = [];
  if (!s || !s.data) return out;
  for (const f of s.data.features) {
    const g = f.geometry;
    if (!g) continue;
    const ring =
      g.type === "Polygon"
        ? g.coordinates[0]
        : g.type === "MultiPolygon"
          ? g.coordinates[0][0]
          : null;
    if (!ring) continue;
    let x = 0,
      y = 0;
    for (const c of ring) {
      x += c[0];
      y += c[1];
    }
    out.push(L.latLng(y / ring.length, x / ring.length));
  }
  return out;
}

function drawComputedRoute(key, result) {
  const cfg = LAYERS.find((l) => l.key === key);
  const s = store[key];
  const wasOn = s && s.layer ? map.hasLayer(s.layer) : !!cfg.on;
  if (s && s.layer && map.hasLayer(s.layer)) map.removeLayer(s.layer);
  let layer = null,
    length = 0;
  if (result && result.latlngs.length >= 2 && result.length_m > 0) {
    layer = L.polyline(result.latlngs, styleFor(cfg));
    length = result.length_m;
  }
  s.layer = layer;
  s.data = {
    features: [{ properties: { length_m: Math.round(length * 100) / 100 } }],
  };
  s.count = layer ? 1 : 0;
  if (layer && wasOn) layer.addTo(map);
}

function solveRoutes() {
  if (!nav) return;
  const startLL = startMarker ? startMarker.getLatLng() : defaultStart;
  const insp = inspectionTargets();
  const waste = wasteTargets();
  const blue = computeRoute(startLL, insp.concat(waste)); // inspector
  const red = computeRoute(startLL, waste); // farmer
  routeStats = {
    route: { ...blue, nInsp: insp.length, nWaste: waste.length },
    route_farmer: { ...red, nInsp: 0, nWaste: waste.length },
  };
  drawComputedRoute("route", blue);
  drawComputedRoute("route_farmer", red);
  applyRouteMode(); // show the active persona's route, hide the other
  renderMeasurements(measRows);
  renderRoutePanel();
  renderToggles();
}

// show only the active persona's route on the map
function applyRouteMode() {
  for (const key of ["route", "route_farmer"]) {
    const s = store[key];
    if (!s || !s.layer) continue;
    const show = key === routeMode;
    if (show && !map.hasLayer(s.layer)) s.layer.addTo(map);
    if (!show && map.hasLayer(s.layer)) map.removeLayer(s.layer);
  }
}

// trip summary for the active route (distance, walking time, targets, efficiency)
function renderRoutePanel() {
  const el = document.getElementById("route-summary");
  if (!el) return;
  const st = routeStats && routeStats[routeMode];
  if (!st || !(st.length_m > 0)) {
    el.innerHTML =
      routeMode === "route_farmer"
        ? '<div class="muted">No waste to collect — farmer route is empty.</div>'
        : '<div class="muted">No reachable targets yet.</div>';
    return;
  }
  const km = st.length_m / 1000;
  const mins = Math.max(1, Math.round((km / WALK_KMH) * 60));
  const row = (k, v, sub) =>
    `<div class="rs-row"><span class="rs-k">${k}</span>` +
    `<span class="rs-v">${v}${sub ? ` <span class="rs-sub">${sub}</span>` : ""}</span></div>`;
  const tgt =
    routeMode === "route"
      ? `${st.nInsp + st.nWaste} <span class="rs-sub">(${st.nInsp} insp · ${st.nWaste} waste)</span>`
      : `${st.nWaste} <span class="rs-sub">waste</span>`;
  const rows = [
    row("Distance", km.toFixed(2) + " km"),
    row("Walking time", "~" + mins + " min", "@ 4 km/h"),
    row("Targets", tgt),
  ];
  if (st.naive_m > st.length_m && st.visited >= 2) {
    const pct = Math.round(((st.naive_m - st.length_m) / st.naive_m) * 100);
    rows.push(
      `<div class="rs-save"><b>Saves ${pct}%</b> vs. separate trips` +
        `<div class="rs-sub">${Math.round(st.naive_m)} m → ${Math.round(st.length_m)} m</div></div>`,
    );
  }
  el.innerHTML = rows.join("");
}

function setRouteMode(mode) {
  routeMode = mode;
  document.querySelectorAll("#mode-seg .seg-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode),
  );
  applyRouteMode();
  renderRoutePanel();
  renderToggles();
}

// ── export ──────────────────────────────────────────────────────────────────
function downloadBlob(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function exportRoute() {
  const st = routeStats && routeStats[routeMode];
  if (!st || !(st.length_m > 0)) return;
  const name = routeMode === "route" ? "inspector" : "farmer";
  const fc = {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: { name, length_m: Math.round(st.length_m * 100) / 100 },
      geometry: { type: "LineString", coordinates: st.latlngs.map(([lat, lng]) => [lng, lat]) },
    }],
  };
  downloadBlob(`${name}_route.geojson`, JSON.stringify(fc), "application/geo+json");
}
function exportCSV() {
  const a = document.createElement("a");
  a.href = DATA + "measurements.csv";
  a.download = "measurements.csv";
  a.click();
}

// ── welcome / onboarding ──────────────────────────────────────────────────────
function showWelcome() {
  const w = document.getElementById("welcome");
  if (w) w.classList.add("show");
}
function hideWelcome() {
  const w = document.getElementById("welcome");
  if (w) w.classList.remove("show");
  try { localStorage.setItem("vineyard_welcomed", "1"); } catch (e) {}
}

function setupRoutePanel() {
  document.querySelectorAll("#mode-seg .seg-btn").forEach((b) => {
    b.onclick = () => setRouteMode(b.dataset.mode);
  });
  const dr = document.getElementById("dl-route");
  if (dr) dr.onclick = exportRoute;
  const dc = document.getElementById("dl-csv");
  if (dc) dc.onclick = exportCSV;
  const hb = document.getElementById("help-btn");
  if (hb) hb.onclick = showWelcome;
  const ws = document.getElementById("welcome-start");
  if (ws) ws.onclick = hideWelcome;
}

// ── boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  const allFeatures = [];
  for (const cfg of LAYERS) {
    const data = await fetchJSON(DATA + cfg.file);
    const count =
      !data || !data.features
        ? 0
        : cfg.subFilter
          ? data.features.filter((f) => cfg.subFilter(f.properties || {}))
              .length
          : data.features.length;
    const layer = data ? buildLayer(cfg, data) : null;
    store[cfg.key] = { cfg, data, layer, count };
    if (layer && cfg.on && count > 0 && !cfg.hidden) layer.addTo(map);
    if (data && data.features)
      for (const f of data.features) if (f.geometry) allFeatures.push(f);
  }

  renderToggles();
  populateFilters();
  renderStats();

  const csv = await fetch(DATA + "measurements.csv")
    .then((r) => (r.ok ? r.text() : null))
    .catch(() => null);
  measRows = csv ? parseCSV(csv) : [];
  renderMeasurements(measRows);

  addControls();
  renderLegend(); // #legend lives in the floating map control created above
  setupRoutePanel();
  await setupStartPicker();
  await loadNavGraph();
  solveRoutes(); // compute the routes for the default START on load

  // fit + lock the view to the site (auto-scales to real data)
  dataBounds = L.geoJSON({
    type: "FeatureCollection",
    features: allFeatures,
  }).getBounds();
  if (dataBounds.isValid()) {
    map.fitBounds(dataBounds, { padding: [30, 30] });
    map.setMaxBounds(dataBounds.pad(BOUNDS_PAD));
    const fitZoom = map.getBoundsZoom(dataBounds);
    map.setMinZoom(Math.max(0, fitZoom - MIN_ZOOM_MARGIN));
    // open a bit closer than the full-extent fit (keeps the fit's centre)
    map.setZoom(Math.min(MAX_ZOOM, fitZoom + DEFAULT_ZOOM_BOOST));
    // snapshot the settled initial view so reset / vineyard→All return to exactly it
    setTimeout(() => {
      savedView = { center: map.getCenter(), zoom: map.getZoom() };
    }, 800);
  } else {
    document.getElementById("banner").style.display = "block";
  }

  // dismiss the loading splash (brief min-show so it doesn't flash), then show
  // the welcome modal on first visit
  const splash = document.getElementById("splash");
  if (splash) {
    setTimeout(() => {
      splash.classList.add("hide");
      setTimeout(() => splash.remove(), 600);
      let seen = false;
      try { seen = !!localStorage.getItem("vineyard_welcomed"); } catch (e) {}
      if (!seen) showWelcome();
    }, 350);
  }
}

boot();
