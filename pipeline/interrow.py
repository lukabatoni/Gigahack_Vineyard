"""
Flow A: inter-row area derivation.

Schema (CLAUDE.md): `interrow_area` is the ground between the canopy edges of two
neighbouring rows in the SAME block — one polygon per inter-row per tile, cut at
tile edges, never overlapping canopy (Golden Rule 4).

Approach (per tile, in pixel space so the output drops straight into the CVAT /
measurements dicts):
  1. Group the tile's rows by vineyard_id (block).
  2. Order rows within a block by perpendicular offset along the block's cross-axis.
  3. Between each adjacent row pair, build a quad strip (the two polylines + their
     end caps), then subtract that block's canopy polygons so the strip runs
     canopy-edge to canopy-edge, not over the plants.
  4. Classify interrow_cover from the ExG green fraction inside the strip:
     bare_soil (<1/4 green) | mixed (1/4-3/4) | vegetation (>3/4).

Rows are single polylines spanning the planting, so a strip between two adjacent
rows approximates the inter-row corridor well without needing the true canopy
edges as long sides — subtracting canopy keeps them off the vines.
"""
from collections import defaultdict
from pathlib import Path

import numpy as np
import cv2
import rasterio
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union

# green-fraction thresholds for interrow_cover
BARE_MAX = 0.25
VEG_MIN = 0.75


def _read_rgb(tif_path):
    with rasterio.open(tif_path) as s:
        arr = np.transpose(s.read()[:3], (1, 2, 0))
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return arr


def _cross_axis_key(rows):
    """Return a function ordering rows by perpendicular offset.

    Rows share one planting angle; project each row's centroid onto the axis
    perpendicular to that angle so adjacent rows sort next to each other.
    """
    angs = []
    for r in rows:
        p = np.array(r["points"], float)
        v = p[-1] - p[0]
        angs.append(np.arctan2(v[1], v[0]) % np.pi)
    ang = float(np.median(angs)) if angs else 0.0
    nx, ny = -np.sin(ang), np.cos(ang)

    def key(r):
        p = np.array(r["points"], float)
        c = p.mean(axis=0)
        return c[0] * nx + c[1] * ny
    return key


def _strip_polygon(r_a, r_b):
    """Quad between two adjacent row polylines: a[0..]->b[reversed]."""
    a = [tuple(p) for p in r_a["points"]]
    b = [tuple(p) for p in r_b["points"]]
    ring = a + b[::-1]
    if len(ring) < 3:
        return None
    poly = Polygon(ring)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if (not poly.is_empty and poly.is_valid) else None


def _cover_class(rgb, poly, w, h):
    """ExG green fraction inside the polygon -> interrow_cover string."""
    mask = np.zeros((h, w), np.uint8)
    pts = np.array(poly.exterior.coords, np.int32)
    cv2.fillPoly(mask, [pts], 1)
    area = int(mask.sum())
    if area < 50:
        return "unassessable"
    R = rgb[:, :, 0].astype(np.int16)
    G = rgb[:, :, 1].astype(np.int16)
    B = rgb[:, :, 2].astype(np.int16)
    exg = (2 * G - R - B)
    green = ((exg > 20) & (mask > 0)).sum()
    frac = green / area
    if frac < BARE_MAX:
        return "bare_soil"
    if frac > VEG_MIN:
        return "vegetation"
    return "mixed"


def derive_interrow(objects_by_tile, tiles_dir):
    """Fill objects_by_tile[tile]['interrow_area'] in place. Returns total count."""
    tiles_dir = Path(tiles_dir)
    total = 0
    for tile_name, objs in objects_by_tile.items():
        rows = [r for r in objs.get("row", []) if len(r.get("points", [])) >= 2]
        if len(rows) < 2:
            objs["interrow_area"] = []
            continue

        tif = tiles_dir / tile_name
        if not tif.exists():
            found = list(tiles_dir.rglob(tile_name))
            if not found:
                objs["interrow_area"] = []
                continue
            tif = found[0]
        rgb = _read_rgb(tif)
        h, w = rgb.shape[:2]

        canopy_by_block = defaultdict(list)
        for c in objs.get("vineyard", []):
            if len(c.get("points", [])) >= 3:
                p = Polygon(c["points"])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    canopy_by_block[c.get("vineyard_id", "")].append(p)

        by_block = defaultdict(list)
        for r in rows:
            by_block[r.get("vineyard_id", "")].append(r)

        interrows = []
        for vid, brows in by_block.items():
            if len(brows) < 2:
                continue
            brows = sorted(brows, key=_cross_axis_key(brows))
            canopy_union = unary_union(canopy_by_block.get(vid, [])) if canopy_by_block.get(vid) else None
            for r_a, r_b in zip(brows, brows[1:]):
                strip = _strip_polygon(r_a, r_b)
                if strip is None or strip.area < 200:
                    continue
                if canopy_union is not None and not canopy_union.is_empty:
                    strip = strip.difference(canopy_union)
                # difference may split into pieces; keep each sizable part
                parts = list(strip.geoms) if strip.geom_type == "MultiPolygon" else [strip]
                for part in parts:
                    if part.is_empty or part.area < 200 or part.geom_type != "Polygon":
                        continue
                    pts = [(float(x), float(y)) for x, y in part.exterior.coords[:-1]]
                    if len(pts) < 3:
                        continue
                    interrows.append({
                        "points": pts,
                        "vineyard_id": vid,
                        "interrow_cover": _cover_class(rgb, part, w, h),
                    })
        objs["interrow_area"] = interrows
        total += len(interrows)
    return total
