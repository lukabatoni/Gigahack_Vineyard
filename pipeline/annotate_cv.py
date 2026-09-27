"""
CV-based annotation of clean vineyard tiles (used where the trained NN is
unavailable). For a list of tiles it produces the four label types with global,
world-stitched IDs and attributes, in the per-tile dict shape cvat_writer /
measurements expect:

    objects_by_tile["siret3_r021_c013.tif"] = {
        "width","height",
        "vineyard":[{points,vineyard_id}],
        "row":[{points,vineyard_id,row_id,row_structure}],
        "interrow_area":[{points,vineyard_id,interrow_cover}],
        "waste":[{xtl,ytl,xbr,ybr,vineyard_id}],
    }

Method (no fixed-angle assumption; angle derived per block):
  canopy  = adaptive ExG green mask → drop oversized blobs (trees/roofs) →
            distance-transform watershed → one polygon per vine.
  rows    = canopy centroids → per-tile dominant angle (structure tensor) →
            cluster centroids by perpendicular offset → centreline polyline.
  IDs     = rows reprojected to EPSG:32635; grouped by (global angle, perp
            offset) so a row crossing a tile edge keeps one row_id. One block.
  interrow= strip between consecutive rows, inset to canopy edges.
  attrs   = row_structure (disrupted if a >=5 m along-row gap), interrow_cover
            (green fraction: bare_soil/mixed/vegetation).
"""
import argparse
from pathlib import Path

import numpy as np
import cv2
import rasterio
from scipy.ndimage import label as nd_label
from scipy.ndimage import gaussian_filter1d

REPO = Path(__file__).resolve().parent.parent
TILES_DIR = REPO / "01_tiles"
PX_M = 0.025
BLOCK_ID = "V01"

# canopy params (tuned against the reference tile — see scratchpad/canopy_tune)
CANOPY = dict(exg_pct=86, exg_floor=12, close_k=3, open_k=2,
              min_area=130, max_area=9000, peak_frac=0.38, min_peak=12)
ROW_SPACING_PX = 105   # perpendicular row spacing (~2.6 m; measured on reference)
ROW_INSET_PX = 20      # canopy half-width; inter-row runs inset from row axes
DISRUPT_GAP_M = 5.0    # along-row gap >= this → row_structure "disrupted"


# ── IO ────────────────────────────────────────────────────────────────────────
def load_rgb(tif):
    with rasterio.open(tif) as ds:
        rgb = ds.read([1, 2, 3]).transpose(1, 2, 0)
        transform = ds.transform
        h, w = ds.height, ds.width
    return rgb, transform, (w, h)


# ── canopy ──────────────────────────────────────────────────────────────────
def segment_canopy(rgb, exg_pct, exg_floor, close_k, open_k,
                   min_area, max_area, peak_frac, min_peak):
    R, G, B = [rgb[:, :, i].astype(np.int16) for i in range(3)]
    exg = (2 * G - R - B).astype(np.float32)
    h, w = exg.shape
    bh, bw = h // 8, w // 8
    mask = np.zeros((h, w), np.uint8)
    for r in range(8):
        for c in range(8):
            r0, r1 = r * bh, (r + 1) * bh if r < 7 else h
            c0, c1 = c * bw, (c + 1) * bw if c < 7 else w
            blk = exg[r0:r1, c0:c1]
            thr = np.percentile(blk, exg_pct)
            mask[r0:r1, c0:c1] = ((blk > thr) & (blk > exg_floor)).astype(np.uint8) * 255
    if close_k:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k)))
    if open_k:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k)))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        if cv2.contourArea(c) > max_area:
            cv2.drawContours(mask, [c], -1, 0, cv2.FILLED)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    nz = dist[dist > 0]
    if len(nz) == 0:
        return [], mask
    adist = int(np.clip(np.median(nz) * 0.6, min_peak, 50))
    dil = cv2.dilate(dist, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (adist * 2 + 1, adist * 2 + 1)))
    localmax = (dist == dil) & (dist > dist.max() * peak_frac) & (mask > 0)
    markers, n = nd_label(localmax)
    if n == 0:
        return [], mask
    topo = cv2.cvtColor(cv2.bitwise_not(rgb[:, :, 1].astype(np.uint8)), cv2.COLOR_GRAY2BGR)
    mk = markers.astype(np.int32); mk[mask == 0] = -1
    cv2.watershed(topo, mk)
    polys = []
    for lid in range(1, n + 1):
        region = ((mk == lid) & (mask > 0)).astype(np.uint8) * 255
        area = int(region.sum()) // 255
        if area < min_area or area > max_area:
            continue
        cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        cnt = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(cnt) < min_area:
            continue
        ap = cv2.approxPolyDP(cnt, 0.008 * cv2.arcLength(cnt, True), True)
        if len(ap) < 3:
            continue
        polys.append([(float(p[0][0]), float(p[0][1])) for p in ap])
    return polys, mask


def centroid(poly):
    a = np.array(poly, np.float64)
    return a.mean(axis=0)


# ── rows (Radon-style: angle search + periodic peaks on the green mask) ────────
def detect_rows(mask, spacing=ROW_SPACING_PX):
    """Find row centrelines from the green mask. Searches the angle that makes the
    perpendicular projection most banded, then finds the periodic row peaks.
    Returns list of dicts {p0,p1,along(np),d,n,offset}."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 500:
        return []
    if len(xs) > 40000:
        i = np.random.default_rng(0).choice(len(xs), 40000, replace=False)
        xs, ys = xs[i], ys[i]
    xs = xs.astype(np.float32); ys = ys.astype(np.float32)
    best = (0.0, -1.0)
    for deg in np.arange(-90, 90, 0.5):
        a = np.radians(deg)
        proj = xs * (-np.sin(a)) + ys * np.cos(a)
        hist, _ = np.histogram(proj, bins=np.arange(proj.min(), proj.max() + 6, 6))
        if hist.var() > best[1]:
            best = (deg, hist.var())
    a = np.radians(best[0])
    d = np.array([np.cos(a), np.sin(a)]); n = np.array([-np.sin(a), np.cos(a)])
    perp = xs * n[0] + ys * n[1]
    along = xs * d[0] + ys * d[1]
    edges = np.arange(perp.min(), perp.max() + 2, 2)
    hist, edges = np.histogram(perp, bins=edges)
    prof = gaussian_filter1d(hist.astype(float), sigma=2)
    centers = (edges[:-1] + edges[1:]) / 2
    thr = prof.max() * 0.13
    minsep = int(spacing * 0.55 / 2)
    peaks = []
    for i in range(1, len(prof) - 1):
        if prof[i] >= prof[i-1] and prof[i] > prof[i+1] and prof[i] > thr:
            if peaks and (i - peaks[-1]) < minsep:
                if prof[i] > prof[peaks[-1]]:
                    peaks[-1] = i
                continue
            peaks.append(i)
    rows = []
    for pi in peaks:
        o = float(centers[pi])
        sel = np.abs(perp - o) < spacing * 0.35
        if sel.sum() < 20:
            continue
        t = np.sort(along[sel])
        t0, t1 = np.percentile(t, 1), np.percentile(t, 99)
        rows.append({
            "p0": tuple(d * t0 + n * o), "p1": tuple(d * t1 + n * o),
            "along": t, "d": d, "n": n, "offset": o,
        })
    return rows


# ── inter-row ─────────────────────────────────────────────────────────────────
def clip_poly(poly, w, h):
    return [(float(np.clip(x, 0, w)), float(np.clip(y, 0, h))) for x, y in poly]


def build_interrows(rows, w, h, inset=ROW_INSET_PX, spacing=ROW_SPACING_PX):
    """Strip between consecutive rows, inset from each axis toward the canopy edges.
    Only between adjacent rows of the same block (skip gaps wider than ~1.6× spacing,
    e.g. a track between plantings)."""
    if len(rows) < 2:
        return []
    rs = sorted(rows, key=lambda r: r["offset"])
    out = []
    for a, b in zip(rs, rs[1:]):
        if b["offset"] - a["offset"] > spacing * 1.6:   # track/gap, not an inter-row
            continue
        n = a["n"]
        a0, a1 = np.array(a["p0"]) + n * inset, np.array(a["p1"]) + n * inset
        b0, b1 = np.array(b["p0"]) - n * inset, np.array(b["p1"]) - n * inset
        poly = [tuple(a0), tuple(a1), tuple(b1), tuple(b0)]
        out.append(clip_poly(poly, w, h))
    return out


# ── attributes ────────────────────────────────────────────────────────────────
def row_structure(along):
    """disrupted if a >=DISRUPT_GAP_M gap in vine coverage along the row."""
    t = np.sort(along)
    if len(t) < 2:
        return "unassessable"
    gaps = np.diff(t) * PX_M
    return "disrupted" if gaps.max() >= DISRUPT_GAP_M else "regular"


def interrow_cover(rgb, poly):
    mask = np.zeros(rgb.shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.array(poly, np.int32).reshape(-1, 1, 2)], 1)
    if mask.sum() == 0:
        return "unassessable"
    R, G, B = [rgb[:, :, i].astype(np.int16) for i in range(3)]
    exg = (2 * G - R - B)
    green = ((exg > 25) & (mask > 0)).sum()
    frac = green / mask.sum()
    if frac < 0.25:
        return "bare_soil"
    if frac > 0.75:
        return "vegetation"
    return "mixed"


# ── global IDs (world-space stitch) ───────────────────────────────────────────
def to_world(transform, pts):
    return [tuple(transform * (x, y)) for x, y in pts]


def assign_global_row_ids(per_tile):
    """per_tile: list of dicts with 'rows'=[(poly_px, members, d, n, world_pts)].
    Groups rows across tiles by (global angle, perp offset in metres)."""
    all_rows = []
    for ti, pt in enumerate(per_tile):
        for ri, r in enumerate(pt["rows_world"]):
            all_rows.append((ti, ri, r))          # r = world midpoint + world angle
    if not all_rows:
        return
    angs = [np.arctan2(*(np.array(r[2]["p1"]) - np.array(r[2]["p0"]))[::-1]) for r in all_rows]
    gang = np.median(np.unwrap(sorted(angs)))
    perp = np.array([-np.sin(gang), np.cos(gang)])
    # offset in metres for each row
    items = []
    for (ti, ri, r) in all_rows:
        mid = (np.array(r["p0"]) + np.array(r["p1"])) / 2
        items.append((ti, ri, float(mid @ perp)))
    items.sort(key=lambda x: x[2])
    # cluster offsets with ~half-spacing tolerance (2.6 m spacing → 1.3 m)
    rid = 0
    groups = []
    cur = [items[0]]
    for prev, it in zip(items, items[1:]):
        if abs(it[2] - prev[2]) > 1.3:
            groups.append(cur); cur = [it]
        else:
            cur.append(it)
    groups.append(cur)
    for gi, g in enumerate(groups):
        name = f"{BLOCK_ID}-R{gi + 1:02d}"
        for (ti, ri, _) in g:
            per_tile[ti]["row_ids"][ri] = name


# ── per-tile ──────────────────────────────────────────────────────────────────
def annotate_tile(tif):
    rgb, transform, (w, h) = load_rgb(tif)
    canopy, mask = segment_canopy(rgb, **CANOPY)
    rows = rows_from_canopy(canopy, mask)
    interrows = build_interrows(rows, w, h)
    result = {
        "rgb": rgb, "transform": transform, "wh": (w, h),
        "canopy": canopy, "rows": rows, "interrows": interrows,
    }
    return result


def build_objects(tif, res):
    w, h = res["wh"]
    rgb, transform = res["rgb"], res["transform"]
    vineyard = [{"points": p, "vineyard_id": BLOCK_ID} for p in res["canopy"]]
    row_objs, rows_world, row_ids = [], [], []
    for (poly, members, d, n) in res["rows"]:
        struct = row_structure(members, d)
        wp = to_world(transform, poly)
        rows_world.append({"p0": wp[0], "p1": wp[1]})
        row_ids.append(None)
        row_objs.append({"points": poly, "vineyard_id": BLOCK_ID,
                         "row_id": None, "row_structure": struct})
    interrow_objs = [{"points": poly, "vineyard_id": BLOCK_ID,
                      "interrow_cover": interrow_cover(rgb, poly)}
                     for (poly, _) in res["interrows"]]
    return {
        "name": Path(tif).name, "width": w, "height": h,
        "vineyard": vineyard, "row": row_objs,
        "interrow_area": interrow_objs, "waste": [],
        "rows_world": rows_world, "row_ids": row_ids, "_row_objs": row_objs,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tiles", nargs="+", help="tile stems e.g. siret3_r020_c012")
    ap.add_argument("--overlay-dir", default=None)
    args = ap.parse_args()

    per_tile = []
    for stem in args.tiles:
        stem = stem.replace(".tif", "")
        tif = TILES_DIR / f"{stem}.tif"
        res = annotate_tile(tif)
        obj = build_objects(tif, res)
        obj["_res"] = res
        per_tile.append(obj)
        print(f"{stem}: canopy={len(obj['vineyard'])} rows={len(obj['row'])} "
              f"interrow={len(obj['interrow_area'])}")

    assign_global_row_ids(per_tile)
    # write row_ids back
    for pt in per_tile:
        for r, rid in zip(pt["_row_objs"], pt["row_ids"]):
            r["row_id"] = rid or ""
    n_rows = len({rid for pt in per_tile for rid in pt["row_ids"] if rid})
    print(f"\nglobal: 1 block, {n_rows} distinct rows across {len(per_tile)} tiles")
    return per_tile


if __name__ == "__main__":
    main()
