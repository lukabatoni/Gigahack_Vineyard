"""
Task 11 support: export model/annotation output to the web-interface data contract.

Reads a CVAT-1.1 annotations.xml + the per-tile GeoTIFFs, converts every object
from pixel space -> EPSG:32635 (via each tile's own affine transform) -> WGS84
(lon/lat), and writes GeoJSON FeatureCollections + measurements.csv that the
Leaflet frontend consumes as static files.

The SAME script is reused on the real model output later: point --annotations and
--tiles at the model's emitted CVAT XML + the 311 tiles instead of the 2 examples.

Output (web/data/):
  canopy.geojson    Polygon    props: vineyard_id
  rows.geojson      LineString props: vineyard_id, row_id, row_structure
  interrow.geojson  Polygon    props: vineyard_id, interrow_cover
  waste.geojson     Polygon    props: vineyard_id   (bbox as 4-corner polygon)
  passages.geojson / forbidden.geojson / start.geojson  (reprojected context)
  measurements.csv

Route files (route.geojson / route_farmer.geojson) are produced by the route
planner (Task 9); if present at repo root they are reprojected too. The frontend
degrades gracefully when any layer file is absent.
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import rasterio
from rasterio.transform import xy
from pyproj import Transformer

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from measurements import compute_measurements, write_csv  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# ── CVAT parsing (self-contained; explore_tiles has import-time side effects) ──

def parse_points(s):
    return [tuple(map(float, p.split(","))) for p in s.split(";")]


def parse_annotations(xml_path):
    root = ET.parse(xml_path).getroot()
    images = {}
    for img in root.findall("image"):
        objects = {"vineyard": [], "row": [], "interrow_area": [], "waste": []}
        for elem in img:
            label = elem.attrib.get("label")
            if label not in objects:
                continue
            attrs = {a.attrib["name"]: (a.text or "") for a in elem.findall("attribute")}
            if label in ("vineyard", "interrow_area", "row"):
                objects[label].append({"points": parse_points(elem.attrib["points"]),
                                       "attrs": attrs})
            elif label == "waste":
                objects[label].append({
                    "xtl": float(elem.attrib["xtl"]), "ytl": float(elem.attrib["ytl"]),
                    "xbr": float(elem.attrib["xbr"]), "ybr": float(elem.attrib["ybr"]),
                    "attrs": attrs})
        images[img.attrib["name"]] = {"objects": objects}
    return images


# ── pixel -> WGS84 ─────────────────────────────────────────────────────────────

def make_to_wgs84(crs):
    """Transformer from a tile CRS (EPSG:32635) to lon/lat (EPSG:4326)."""
    return Transformer.from_crs(crs, "EPSG:4326", always_xy=True)


def px_ring_to_lonlat(points_px, transform, to_wgs84, close=False):
    ring = []
    for px, py in points_px:
        e, n = xy(transform, py, px)          # rasterio.xy wants (row, col) = (y, x)
        lon, lat = to_wgs84.transform(e, n)
        ring.append([lon, lat])
    if close and ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def feature(geom_type, coords, props):
    return {"type": "Feature",
            "geometry": {"type": geom_type, "coordinates": coords},
            "properties": props}


# ── main export ────────────────────────────────────────────────────────────────

def resolve_tile(tiles_dir, name):
    p = tiles_dir / name
    if p.exists():
        return p
    found = list(tiles_dir.rglob(name))
    return found[0] if found else None


def export(annotations_xml, tiles_dir, out_dir):
    tiles_dir, out_dir = Path(tiles_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ann = parse_annotations(annotations_xml)

    canopy, rows, interrow, waste = [], [], [], []
    objects_by_tile = {}

    for tile_name, d in ann.items():
        tif = resolve_tile(tiles_dir, tile_name)
        if tif is None:
            print(f"  WARN: tile not found for {tile_name}, skipping")
            continue
        with rasterio.open(tif) as src:
            transform, crs = src.transform, src.crs
        to_wgs84 = make_to_wgs84(crs)
        objs = d["objects"]

        # keep pixel geometry for the (metre-accurate) measurements module
        m_objs = {"vineyard": [], "row": [], "interrow_area": []}

        for o in objs["vineyard"]:
            vid = o["attrs"].get("vineyard_id", "")
            ring = px_ring_to_lonlat(o["points"], transform, to_wgs84, close=True)
            canopy.append(feature("Polygon", [ring], {"vineyard_id": vid, "tile": tile_name}))
            m_objs["vineyard"].append({"points": o["points"], "vineyard_id": vid})

        for o in objs["interrow_area"]:
            vid = o["attrs"].get("vineyard_id", "")
            ring = px_ring_to_lonlat(o["points"], transform, to_wgs84, close=True)
            interrow.append(feature("Polygon", [ring], {
                "vineyard_id": vid,
                "interrow_cover": o["attrs"].get("interrow_cover", ""),
                "tile": tile_name}))
            m_objs["interrow_area"].append({"points": o["points"], "vineyard_id": vid})

        for o in objs["row"]:
            vid = o["attrs"].get("vineyard_id", "")
            rid = o["attrs"].get("row_id", "")
            line = px_ring_to_lonlat(o["points"], transform, to_wgs84, close=False)
            rows.append(feature("LineString", line, {
                "vineyard_id": vid, "row_id": rid,
                "row_structure": o["attrs"].get("row_structure", ""),
                "tile": tile_name}))
            m_objs["row"].append({"points": o["points"], "vineyard_id": vid, "row_id": rid})

        for o in objs["waste"]:
            vid = o["attrs"].get("vineyard_id", "")
            corners_px = [(o["xtl"], o["ytl"]), (o["xbr"], o["ytl"]),
                          (o["xbr"], o["ybr"]), (o["xtl"], o["ybr"])]
            ring = px_ring_to_lonlat(corners_px, transform, to_wgs84, close=True)
            waste.append(feature("Polygon", [ring], {"vineyard_id": vid, "tile": tile_name}))

        objects_by_tile[tile_name] = m_objs

    def fc(feats):
        return {"type": "FeatureCollection", "features": feats}

    for name, feats in [("canopy", canopy), ("rows", rows),
                        ("interrow", interrow), ("waste", waste)]:
        (out_dir / f"{name}.geojson").write_text(json.dumps(fc(feats)))
        print(f"  wrote {name}.geojson  ({len(feats)} features)")

    # measurements (metre-accurate, from pixel coords + tile transforms)
    m = compute_measurements(objects_by_tile, tiles_dir)
    write_csv(m, out_dir / "measurements.csv")
    print(f"  blocks={m['block_count']} rows={m['row_count']} "
          f"canopy={m['total_canopy_area_m2']:.0f}m2 "
          f"interrow={m['total_interrow_area_m2']:.0f}m2 "
          f"row_len={m['total_row_length_m']:.0f}m")

    export_context(out_dir)


# ── reproject the EPSG:32635 context/route files -> WGS84 ────────────────────────

def reproject_geojson_file(src_path, dst_path):
    gj = json.loads(Path(src_path).read_text())
    # detect source CRS: these files are documented EPSG:32635
    to_wgs84 = Transformer.from_crs("EPSG:32635", "EPSG:4326", always_xy=True)

    def conv(coords, depth):
        if depth == 0:
            lon, lat = to_wgs84.transform(coords[0], coords[1])
            return [lon, lat]
        return [conv(c, depth - 1) for c in coords]

    depth_by_type = {"Point": 0, "LineString": 1, "MultiLineString": 2,
                     "Polygon": 2, "MultiPolygon": 3}
    for feat in gj.get("features", []):
        g = feat.get("geometry")
        if not g:
            continue
        g["coordinates"] = conv(g["coordinates"], depth_by_type[g["type"]])
    Path(dst_path).write_text(json.dumps(gj))
    print(f"  reprojected {Path(dst_path).name}")


def export_context(out_dir):
    """Reproject route context + (if present) the route outputs into web/data/."""
    route_dir = REPO / "02_route"
    for name in ["passages", "forbidden", "start", "study_area"]:
        src = route_dir / f"{name}.geojson"
        if src.exists():
            reproject_geojson_file(src, out_dir / f"{name}.geojson")
    for name in ["route", "route_farmer"]:      # produced by Task 9, optional
        src = REPO / f"{name}.geojson"
        if src.exists():
            reproject_geojson_file(src, out_dir / f"{name}.geojson")
        else:
            print(f"  note: {name}.geojson not present yet (route planner pending)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations",
                    default=str(REPO / "05_examples/siret3_examples_cvat/annotations.xml"))
    ap.add_argument("--tiles",
                    default=str(REPO / "05_examples/siret3_examples_cvat/images"))
    ap.add_argument("--out", default=str(REPO / "web/data"))
    args = ap.parse_args()
    print(f"Exporting web data from {args.annotations}")
    export(args.annotations, args.tiles, args.out)
    print("Done ->", args.out)
