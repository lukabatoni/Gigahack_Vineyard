"""
Task 10: Measurements module.

Converts per-tile pixel geometries into EPSG:32635 (metres) and computes the
scored measurements:
  - block count (distinct vineyard_id)
  - row count (distinct row_id)
  - total row length (m)          per row_id, summed across tiles
  - canopy area (m²)              UNION of vineyard polygons per block (no double-count)
  - inter-row area (m²)           sum of interrow_area polygons per block

All geometry math uses the tile's own GeoTIFF affine transform, so it is exact
per tile and needs no global assumptions.

Output: measurements.csv
"""
import csv
from pathlib import Path
from collections import defaultdict

import rasterio
from rasterio.transform import xy
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union


def pixels_to_world(points, transform):
    """[(col,row/px_x,px_y), ...] -> [(easting, northing), ...] in tile CRS.
    NOTE: annotation points are (x=col, y=row) in pixel space."""
    out = []
    for px, py in points:
        # rasterio.xy takes (row, col) = (y, x)
        e, n = xy(transform, py, px)
        out.append((e, n))
    return out


def tile_transform(tif_path):
    with rasterio.open(tif_path) as src:
        return src.transform, str(src.crs)


def world_polygon(points_px, transform):
    world = pixels_to_world(points_px, transform)
    if len(world) < 3:
        return None
    p = Polygon(world)
    if not p.is_valid:
        p = p.buffer(0)
    return p if (p.is_valid and not p.is_empty) else None


def world_line(points_px, transform):
    world = pixels_to_world(points_px, transform)
    if len(world) < 2:
        return None
    return LineString(world)


def compute_measurements(objects_by_tile, tiles_dir):
    """
    objects_by_tile: { tile_filename: {
        'vineyard':      [ {points, vineyard_id}, ... ],
        'row':           [ {points, vineyard_id, row_id}, ... ],
        'interrow_area': [ {points, vineyard_id}, ... ],
    } }
    tiles_dir: folder to resolve tile filename -> geotiff path.
    Returns dict of aggregate measurements.
    """
    tiles_dir = Path(tiles_dir)
    canopy_by_block = defaultdict(list)      # vineyard_id -> [Polygon]
    interrow_by_block = defaultdict(list)    # vineyard_id -> [Polygon]
    row_lines = defaultdict(list)            # row_id -> [LineString]
    row_block = {}                           # row_id -> vineyard_id
    blocks = set()

    for tile_name, objs in objects_by_tile.items():
        tif = tiles_dir / tile_name
        if not tif.exists():
            # try recursive search
            found = list(tiles_dir.rglob(tile_name))
            if not found:
                continue
            tif = found[0]
        transform, _ = tile_transform(tif)

        for o in objs.get("vineyard", []):
            poly = world_polygon(o["points"], transform)
            if poly:
                vid = o.get("vineyard_id", "")
                canopy_by_block[vid].append(poly)
                blocks.add(vid)

        for o in objs.get("interrow_area", []):
            poly = world_polygon(o["points"], transform)
            if poly:
                vid = o.get("vineyard_id", "")
                interrow_by_block[vid].append(poly)
                blocks.add(vid)

        for o in objs.get("row", []):
            line = world_line(o["points"], transform)
            if line:
                rid = o.get("row_id", "")
                row_lines[rid].append(line)
                row_block[rid] = o.get("vineyard_id", "")
                blocks.add(o.get("vineyard_id", ""))

    # aggregate
    per_block = {}
    for vid in blocks:
        canopy_union = unary_union(canopy_by_block.get(vid, []))
        interrow_area = sum(p.area for p in interrow_by_block.get(vid, []))
        per_block[vid] = {
            "canopy_area_m2": canopy_union.area if not canopy_union.is_empty else 0.0,
            "interrow_area_m2": interrow_area,
        }

    per_row = {rid: sum(l.length for l in lines) for rid, lines in row_lines.items()}

    total_canopy = sum(b["canopy_area_m2"] for b in per_block.values())
    total_interrow = sum(b["interrow_area_m2"] for b in per_block.values())
    total_row_len = sum(per_row.values())

    return {
        "block_count": len([b for b in blocks if b != ""]) or len(blocks),
        "row_count": len(per_row),
        "total_row_length_m": total_row_len,
        "total_canopy_area_m2": total_canopy,
        "total_interrow_area_m2": total_interrow,
        "per_block": per_block,
        "per_row": per_row,
        "row_block": row_block,
    }


def write_csv(measurements, out_path):
    out_path = Path(out_path)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "vineyard_id", "row_id", "value", "unit"])
        w.writerow(["block_count", "", "", measurements["block_count"], "count"])
        w.writerow(["row_count", "", "", measurements["row_count"], "count"])
        w.writerow(["total_row_length", "", "",
                    round(measurements["total_row_length_m"], 2), "m"])
        w.writerow(["total_canopy_area", "", "",
                    round(measurements["total_canopy_area_m2"], 2), "m2"])
        w.writerow(["total_interrow_area", "", "",
                    round(measurements["total_interrow_area_m2"], 2), "m2"])
        for vid, b in sorted(measurements["per_block"].items()):
            w.writerow(["canopy_area", vid, "", round(b["canopy_area_m2"], 2), "m2"])
            w.writerow(["interrow_area", vid, "", round(b["interrow_area_m2"], 2), "m2"])
        for rid, length in sorted(measurements["per_row"].items()):
            vid = measurements["row_block"].get(rid, "")
            w.writerow(["row_length", vid, rid, round(length, 2), "m"])
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    # Self-test on the reference example annotations (uses real tile transforms).
    from explore_tiles import parse_annotations
    ex = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat")
    ann = parse_annotations(ex / "annotations.xml")

    objects_by_tile = {}
    for name, d in ann.items():
        objs = {"vineyard": [], "row": [], "interrow_area": []}
        for o in d["objects"]["vineyard"]:
            objs["vineyard"].append({"points": o["points"],
                                     "vineyard_id": o["attrs"].get("vineyard_id", "")})
        for o in d["objects"]["row"]:
            objs["row"].append({"points": o["points"],
                                "vineyard_id": o["attrs"].get("vineyard_id", ""),
                                "row_id": o["attrs"].get("row_id", "")})
        for o in d["objects"]["interrow_area"]:
            objs["interrow_area"].append({"points": o["points"],
                                          "vineyard_id": o["attrs"].get("vineyard_id", "")})
        objects_by_tile[name] = objs

    m = compute_measurements(objects_by_tile, ex / "images")
    print("block_count        :", m["block_count"])
    print("row_count          :", m["row_count"])
    print("total_row_length_m :", round(m["total_row_length_m"], 1))
    print("total_canopy_m2    :", round(m["total_canopy_area_m2"], 1))
    print("total_interrow_m2  :", round(m["total_interrow_area_m2"], 1))
    write_csv(m, "/Users/luka-sap/Desktop/Gigahack/pipeline/output/measurements_example.csv")
