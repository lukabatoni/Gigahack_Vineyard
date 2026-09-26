/* Vineyard AI — field map. Plain Leaflet, static GeoJSON/CSV from ./data/.
   All geometry is WGS84 (reprojected from EPSG:32635 by pipeline/export_web_data.py). */

const DATA = "data/";

// ── view constraints ─────────────────────────────────────────────────────────
// Esri World Imagery has tiles up to ~z19 in rural areas; past that = blank tiles.
// MAX_ZOOM = hard cap (can't zoom past imagery). To allow zooming further with
// blurry-but-never-blank imagery instead, raise MAX_ZOOM and keep MAX_NATIVE_ZOOM=19.
const MAX_ZOOM = 19;          // hard zoom-in limit
const MAX_NATIVE_ZOOM = 19;   // last zoom level Esri actually has tiles for
const MIN_ZOOM_MARGIN = 1;    // how many levels you may zoom out past the data-fit zoom
const BOUNDS_PAD = 0.3;       // pan slack around the data extent (fraction of extent)
const MAX_BOUNDS_VISCOSITY = 0.85; // 0=soft edge, 1=hard wall when panning to the edge

// ── map + basemap ──────────────────────────────────────────────────────────
const map = L.map("map", {
  zoomControl: true,
  maxZoom: MAX_ZOOM,
  maxBoundsViscosity: MAX_BOUNDS_VISCOSITY,
}).setView([47.123, 28.707], 16);

L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: MAX_ZOOM, maxNativeZoom: MAX_NATIVE_ZOOM, attribution: "Imagery © Esri" }
).addTo(map);

// ── layer catalogue (order = draw order / legend order) ──────────────────────
// kind: polygon | line | route | point | context
const LAYERS = [
  { key: "interrow", file: "interrow.geojson", kind: "polygon", label: "Inter-row areas",
    color: "#ff8c00", fill: 0.2, filterable: true, on: true },
  { key: "canopy",   file: "canopy.geojson",   kind: "polygon", label: "Canopy (vines)",
    color: "#2ecc40", fill: 0.45, filterable: true, on: true },
  { key: "rows",     file: "rows.geojson",     kind: "line",    label: "Rows",
    color: "#4a9eff", weight: 2, filterable: true, on: true },
  { key: "waste",    file: "waste.geojson",    kind: "polygon", label: "Waste",
    color: "#ff4136", fill: 0.35, filterable: true, on: true },
  { key: "route",        file: "route.geojson",        kind: "route", label: "Inspector route (blue)",
    color: "#0074d9", weight: 4, on: true },
  { key: "route_farmer", file: "route_farmer.geojson", kind: "route", label: "Farmer route (red)",
    color: "#e0245e", weight: 4, dash: "6 6", on: true },
  { key: "passages",  file: "passages.geojson",  kind: "context", label: "Passages",
    color: "#7fdbff", fill: 0.08, weight: 1, on: false },
  { key: "forbidden", file: "forbidden.geojson", kind: "context", label: "Forbidden zones",
    color: "#b10dc9", fill: 0.12, weight: 1, on: false },
  { key: "start",     file: "start.geojson",     kind: "point",   label: "START",
    color: "#ffdc00", on: true },
];

const store = {};          // key -> { cfg, data, layer, count }
let filterBlock = "";
let filterRow = "";

// ── helpers ──────────────────────────────────────────────────────────────────
async function fetchJSON(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
  } catch (e) { return null; }
}

function matchFilter(cfg, props) {
  if (!cfg.filterable) return true;
  if (filterBlock && props.vineyard_id !== filterBlock) return false;
  // row filter only constrains the rows layer (others carry no row_id)
  if (filterRow && cfg.key === "rows" && props.row_id !== filterRow) return false;
  return true;
}

function popupHTML(cfg, props) {
  const rows = [];
  const add = (k, v) => { if (v !== undefined && v !== null && v !== "") rows.push(`<span class="k">${k}:</span> <b>${v}</b>`); };
  rows.push(`<b>${cfg.label}</b>`);
  add("vineyard_id", props.vineyard_id);
  add("row_id", props.row_id);
  add("row_structure", props.row_structure);
  add("interrow_cover", props.interrow_cover);
  add("length_m", props.length_m ? Number(props.length_m).toFixed(1) : undefined);
  add("tile", props.tile);
  return rows.join("<br>");
}

function styleFor(cfg) {
  if (cfg.kind === "line" || cfg.kind === "route") {
    return { color: cfg.color, weight: cfg.weight || 3, opacity: 0.95, dashArray: cfg.dash };
  }
  return { color: cfg.color, weight: cfg.weight || 1, fillColor: cfg.color,
           fillOpacity: cfg.fill != null ? cfg.fill : 0.3, opacity: 0.9 };
}

function buildLayer(cfg, data) {
  if (cfg.kind === "point") {
    return L.geoJSON(data, {
      pointToLayer: (f, latlng) => L.circleMarker(latlng,
        { radius: 8, color: "#000", weight: 2, fillColor: cfg.color, fillOpacity: 1 }),
      onEachFeature: (f, l) => l.bindPopup(popupHTML(cfg, f.properties || {})),
    });
  }
  return L.geoJSON(data, {
    filter: (f) => matchFilter(cfg, f.properties || {}),
    style: () => styleFor(cfg),
    onEachFeature: (f, l) => l.bindPopup(popupHTML(cfg, f.properties || {})),
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
    const s = store[cfg.key];
    const present = s && s.count > 0;
    const row = document.createElement("label");
    row.className = "toggle" + (present ? "" : " disabled");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!(present && cfg.on && s.layer && map.hasLayer(s.layer));
    cb.disabled = !present;
    cb.onchange = () => {
      if (!s || !s.layer) return;
      if (cb.checked) s.layer.addTo(map); else map.removeLayer(s.layer);
    };

    const sw = document.createElement("span");
    sw.className = "swatch" + (cfg.kind === "line" || cfg.kind === "route" ? " line" : "");
    sw.style.background = cfg.color;

    const name = document.createElement("span");
    name.textContent = cfg.label;

    const cnt = document.createElement("span");
    cnt.className = "count";
    cnt.textContent = present ? s.count : "pending";

    row.append(cb, sw, name, cnt);
    box.appendChild(row);
  }
}

// ── UI: filters ─────────────────────────────────────────────────────────────
function populateFilters() {
  const blocks = new Set(), rowsIds = new Set();
  for (const key of ["canopy", "rows", "interrow", "waste"]) {
    const s = store[key];
    if (!s || !s.data) continue;
    for (const f of s.data.features) {
      const p = f.properties || {};
      if (p.vineyard_id) blocks.add(p.vineyard_id);
      if (p.row_id) rowsIds.add(p.row_id);
    }
  }
  fillSelect("filter-block", [...blocks].sort());
  fillSelect("filter-row", [...rowsIds].sort());

  document.getElementById("filter-block").onchange = (e) => { filterBlock = e.target.value; rebuildFilterable(); };
  document.getElementById("filter-row").onchange   = (e) => { filterRow   = e.target.value; rebuildFilterable(); };
}

function fillSelect(id, values) {
  const sel = document.getElementById(id);
  for (const v of values) {
    const o = document.createElement("option");
    o.value = v; o.textContent = v;
    sel.appendChild(o);
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
  const num = (v, d = 0) => v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

  const add = (label, value, cls = "") => {
    const tr = document.createElement("tr");
    if (cls) tr.className = cls;
    tr.innerHTML = `<td>${label}</td><td>${value}</td>`;
    tbody.appendChild(tr);
  };
  const head = (t) => add(t, "", "head");

  if (rows.length) {
    const blocks = get("block_count"), rc = get("row_count");
    const rowlen = get("total_row_length"), can = get("total_canopy_area"), inter = get("total_interrow_area");
    head("Totals");
    add("Blocks", num(blocks && blocks.value), "big");
    add("Rows", num(rc && rc.value), "big");
    add("Total row length", num(rowlen && rowlen.value) + " m");
    add("Canopy area", num(can && can.value) + " m² (" + num((can && can.value) / 1e4, 3) + " ha)");
    add("Inter-row area", num(inter && inter.value) + " m² (" + num((inter && inter.value) / 1e4, 3) + " ha)");

    const perBlock = rows.filter((r) => r.metric === "canopy_area");
    if (perBlock.length) {
      head("Per block — canopy m²");
      for (const r of perBlock) add(r.vineyard_id || "(none)", num(r.value));
    }
  } else {
    add("measurements.csv not found", "");
  }

  head("Routes");
  const rb = routeLength("route"), rf = routeLength("route_farmer");
  add("Inspector (blue)", rb == null ? "pending" : num(rb) + " m");
  add("Farmer (red)", rf == null ? "pending" : num(rf) + " m");
}

// ── boot ──────────────────────────────────────────────────────────────────────
async function boot() {
  // load all layer data
  const allFeatures = [];
  for (const cfg of LAYERS) {
    const data = await fetchJSON(DATA + cfg.file);
    const count = data && data.features ? data.features.length : 0;
    const layer = data ? buildLayer(cfg, data) : null;
    store[cfg.key] = { cfg, data, layer, count };
    if (layer && cfg.on && count > 0) layer.addTo(map);
    if (data && data.features) for (const f of data.features) if (f.geometry) allFeatures.push(f);
  }

  renderToggles();
  populateFilters();

  // measurements
  const csv = await fetch(DATA + "measurements.csv").then((r) => r.ok ? r.text() : null).catch(() => null);
  renderMeasurements(csv ? parseCSV(csv) : []);

  // fit to loaded geometry, then lock the view to the site (auto-scales to real data)
  const bounds = L.geoJSON({ type: "FeatureCollection", features: allFeatures }).getBounds();
  if (bounds.isValid()) {
    map.fitBounds(bounds, { padding: [30, 30] });
    // can't pan away from the field, can't zoom out to the whole world
    map.setMaxBounds(bounds.pad(BOUNDS_PAD));
    const fitZoom = map.getBoundsZoom(bounds);
    map.setMinZoom(Math.max(0, fitZoom - MIN_ZOOM_MARGIN));
  }
}

boot();
