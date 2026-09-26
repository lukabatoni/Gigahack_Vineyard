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

// ── attribute palettes (scored attributes get their own colours) ───────────────
const STRUCTURE_PALETTE = {   // row_structure
  regular: "#2ecc40", disrupted: "#ff851b", unassessable: "#aaaaaa", "": "#4a9eff",
};
const COVER_PALETTE = {       // interrow_cover
  bare_soil: "#c2925b", vegetation: "#2ecc40", mixed: "#ffdc00", unassessable: "#888888", "": "#ff8c00",
};

// ── basemaps ───────────────────────────────────────────────────────────────
const map = L.map("map", {
  zoomControl: true,
  maxZoom: MAX_ZOOM,
  maxBoundsViscosity: MAX_BOUNDS_VISCOSITY,
}).setView([47.123, 28.707], 16);

const satellite = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: MAX_ZOOM, maxNativeZoom: MAX_NATIVE_ZOOM, attribution: "Imagery © Esri" }
);
const streets = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  { maxZoom: MAX_ZOOM, attribution: "© OpenStreetMap" });
const blank = L.layerGroup();
satellite.addTo(map);
L.control.layers(
  { "Satellite": satellite, "Streets": streets, "None": blank }, null,
  { position: "topright", collapsed: true }
).addTo(map);

// scale bar
L.control.scale({ metric: true, imperial: false, position: "bottomleft" }).addTo(map);

// ── layer catalogue (order = draw order / legend order) ──────────────────────
// kind: polygon | line | route | point | context
const LAYERS = [
  { key: "interrow", file: "interrow.geojson", kind: "polygon", label: "Inter-row areas",
    color: "#ff8c00", fill: 0.2, filterable: true, on: true,
    attrKey: "interrow_cover", palette: COVER_PALETTE },
  { key: "canopy",   file: "canopy.geojson",   kind: "polygon", label: "Canopy (vines)",
    color: "#2ecc40", fill: 0.45, filterable: true, on: true },
  { key: "rows",     file: "rows.geojson",     kind: "line",    label: "Rows",
    color: "#4a9eff", weight: 2, filterable: true, on: true,
    attrKey: "row_structure", palette: STRUCTURE_PALETTE },
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
let dataBounds = null;

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
    return { color, weight: cfg.weight || 3, opacity: 0.95, dashArray: cfg.dash };
  }
  return { color, weight: cfg.weight || 1, fillColor: color,
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
    style: (f) => styleFor(cfg, f),
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

// ── UI: legend (attribute colour keys, with live counts) ─────────────────────
function renderLegend() {
  const box = document.getElementById("legend");
  box.innerHTML = "";
  const section = (title, cfgKey, palette, order) => {
    const s = store[cfgKey];
    if (!s || !s.data || !s.count) return;
    const counts = {};
    for (const f of s.data.features) {
      const v = (f.properties || {})[LAYERS.find((l) => l.key === cfgKey).attrKey] || "(none)";
      counts[v] = (counts[v] || 0) + 1;
    }
    const h = document.createElement("div");
    h.className = "legend-title";
    h.textContent = title;
    box.appendChild(h);
    for (const key of order) {
      if (!(key in counts)) continue;
      const row = document.createElement("div");
      row.className = "legend-row";
      row.innerHTML = `<span class="swatch" style="background:${palette[key] || palette[""]}"></span>` +
                      `<span>${key}</span><span class="count">${counts[key]}</span>`;
      box.appendChild(row);
      delete counts[key];
    }
    for (const key of Object.keys(counts)) {   // any unexpected values
      const row = document.createElement("div");
      row.className = "legend-row";
      row.innerHTML = `<span class="swatch" style="background:${palette[""]}"></span>` +
                      `<span>${key}</span><span class="count">${counts[key]}</span>`;
      box.appendChild(row);
    }
  };
  section("Rows — row_structure", "rows", STRUCTURE_PALETTE,
          ["regular", "disrupted", "unassessable"]);
  section("Inter-row — interrow_cover", "interrow", COVER_PALETTE,
          ["bare_soil", "mixed", "vegetation", "unassessable"]);
  if (!box.children.length) box.innerHTML = '<div class="muted">no attribute layers loaded</div>';
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

// ── stats dashboard ──────────────────────────────────────────────────────────
function tally(cfgKey, attrKey) {
  const s = store[cfgKey];
  const out = {};
  if (!s || !s.data) return out;
  for (const f of s.data.features) {
    const v = (f.properties || {})[attrKey] || "(none)";
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
  for (const k of ["regular", "disrupted", "unassessable"]) add(k, rs[k] || 0);

  const cov = tally("interrow", "interrow_cover");
  head("Inter-row cover");
  for (const k of ["bare_soil", "mixed", "vegetation", "unassessable"]) add(k, cov[k] || 0);

  head("Object counts");
  add("Canopy polygons", (store.canopy && store.canopy.count) || 0);
  add("Rows", (store.rows && store.rows.count) || 0);
  add("Inter-row areas", (store.interrow && store.interrow.count) || 0);
  add("Waste boxes", (store.waste && store.waste.count) || 0);

  // per-block object tallies
  const perBlock = {};   // vid -> {canopy, rows:Set(row_id), interrow, waste}
  const bump = (key, prop) => {
    const s = store[key];
    if (!s || !s.data) return;
    for (const f of s.data.features) {
      const p = f.properties || {};
      const vid = p.vineyard_id || "(none)";
      perBlock[vid] = perBlock[vid] || { canopy: 0, rows: new Set(), interrow: 0, waste: 0 };
      if (key === "rows") perBlock[vid].rows.add(p.row_id);
      else perBlock[vid][prop]++;
    }
  };
  bump("canopy", "canopy"); bump("rows"); bump("interrow", "interrow"); bump("waste", "waste");
  const vids = Object.keys(perBlock).sort();
  if (vids.length) {
    head("Per block (canopy / rows / interrow / waste)");
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

// ── map controls: reset view + zoom indicator ─────────────────────────────────
function addControls() {
  const Reset = L.Control.extend({
    options: { position: "topleft" },
    onAdd() {
      const b = L.DomUtil.create("a", "leaflet-bar reset-view");
      b.href = "#"; b.title = "Reset view"; b.innerHTML = "⤢";
      L.DomEvent.on(b, "click", (e) => {
        L.DomEvent.stop(e);
        if (dataBounds && dataBounds.isValid()) map.fitBounds(dataBounds, { padding: [30, 30] });
      });
      return b;
    },
  });
  map.addControl(new Reset());

  const zoomBox = L.control({ position: "bottomright" });
  zoomBox.onAdd = () => {
    const d = L.DomUtil.create("div", "zoom-indicator");
    const upd = () => { d.textContent = "z " + map.getZoom(); };
    map.on("zoomend", upd); upd();
    return d;
  };
  zoomBox.addTo(map);
}

// ── boot ──────────────────────────────────────────────────────────────────────
async function boot() {
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
  renderLegend();
  populateFilters();
  renderStats();

  const csv = await fetch(DATA + "measurements.csv").then((r) => r.ok ? r.text() : null).catch(() => null);
  renderMeasurements(csv ? parseCSV(csv) : []);

  addControls();

  // fit + lock the view to the site (auto-scales to real data)
  dataBounds = L.geoJSON({ type: "FeatureCollection", features: allFeatures }).getBounds();
  if (dataBounds.isValid()) {
    map.fitBounds(dataBounds, { padding: [30, 30] });
    map.setMaxBounds(dataBounds.pad(BOUNDS_PAD));
    const fitZoom = map.getBoundsZoom(dataBounds);
    map.setMinZoom(Math.max(0, fitZoom - MIN_ZOOM_MARGIN));
  } else {
    document.getElementById("banner").style.display = "block";
  }
}

boot();
