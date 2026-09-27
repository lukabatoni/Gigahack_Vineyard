"""
Flow A / Task 4: row post-processing.

Turns YOLO11-seg `vine_row` instance masks into centreline polylines, in the
per-tile `row` dict shape the rest of the pipeline expects (see cvat_writer /
measurements / 50_PARALLEL_WORK §3):

    {"points": [(x, y), ...], "vineyard_id": "", "row_id": "", "row_structure": "regular"}

Coordinates are pixels (x=col, y=row, 0,0 top-left) — CVAT convention.

Centreline method: **per-instance PCA major axis** — NO fixed-angle assumption
(see 20_DECISIONS 2026-09-26). We take the mask's foreground pixels, find the
principal axis via the covariance eigenvectors, project pixels onto it, and
sample a polyline along that axis. Bends are captured by binning along the axis
and taking the perpendicular-mean per bin, so a curved row yields a bent
polyline rather than a single straight chord.

vineyard_id / row_id / row_structure are left as placeholders here — global ID
assignment (Task 7) and disrupted-gap detection (Task 5 context) fill them later.
This module's job is purely geometry: mask -> polyline.
"""
from pathlib import Path
import os

import numpy as np
import cv2
from ultralytics import YOLO

# Trained single-class 'row' model (negatives-augmented, md5 0c713ac2). Committed
# under weights/ so a fresh clone / Docker build works without the training-runs dir.
# Override with the ROWS_WEIGHTS env var if the checkpoint lives elsewhere.
_REPO = Path(__file__).resolve().parent.parent
BEST = Path(os.environ.get("ROWS_WEIGHTS", _REPO / "weights" / "rows_best.pt"))
# The Riseholme model was 2-class {0: trunk, 1: vine_row}; the Moldova-trained
# rows model is single-class {0: row}. Pick the row class by NAME at runtime so
# either checkpoint works without a code edit.
VINE_ROW_CLS = 1  # fallback if names are unavailable


def _rdp(points, eps):
    """Ramer-Douglas-Peucker simplification. points: list[(x,y)] -> list[(x,y)]."""
    if len(points) < 3:
        return points
    a = np.array(points[0], dtype=np.float64)
    b = np.array(points[-1], dtype=np.float64)
    ab = b - a
    nab = np.hypot(*ab)
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        p = np.array(points[i], dtype=np.float64)
        if nab < 1e-9:
            d = np.hypot(*(p - a))
        else:
            d = abs(ab[0] * (a[1] - p[1]) - (a[0] - p[0]) * ab[1]) / nab
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = _rdp(points[:idx + 1], eps)
        right = _rdp(points[idx:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def _dominant_angle(mask_union):
    """Estimate the dominant row direction (radians) from the union of all
    vine_row masks in a tile. Rows show up as parallel ridges; their common
    orientation is the structure tensor's principal direction over the mask.

    Returns angle in radians of the row direction (unit vector = (cos,sin)).
    No fixed-angle assumption: derived from the image content per tile.
    """
    m = (mask_union > 0).astype(np.float32)
    # Smooth so per-plant gaps along a row don't dominate the gradient.
    m = cv2.GaussianBlur(m, (0, 0), sigmaX=9)
    gx = cv2.Sobel(m, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(m, cv2.CV_32F, 0, 1, ksize=5)
    # Structure tensor components, summed over the whole tile.
    Jxx = float((gx * gx).sum())
    Jyy = float((gy * gy).sum())
    Jxy = float((gx * gy).sum())
    # Principal gradient direction; the ROW runs perpendicular to the gradient.
    grad_ang = 0.5 * np.arctan2(2 * Jxy, Jxx - Jyy)
    row_ang = grad_ang + np.pi / 2.0
    return row_ang


def _assemble_rows(masks, orig_shape, row_spacing_px=45, min_pts=3):
    """Group per-plant masks into physical rows using one dominant angle.

    masks: list of binary masks (H,W uint8), one per vine_row instance.
    Returns list of polylines (list[(x,y)]).
    """
    h, w = orig_shape
    if not masks:
        return []

    union = np.zeros((h, w), np.uint8)
    for m in masks:
        union |= m
    ang = _dominant_angle(union)
    d = np.array([np.cos(ang), np.sin(ang)])       # along-row unit vector
    n = np.array([-np.sin(ang), np.cos(ang)])      # across-row (perpendicular)

    # Represent each mask by its centroid; project onto along (t) and across (s).
    cents = []
    for m in masks:
        ys, xs = np.nonzero(m)
        if xs.size == 0:
            continue
        cents.append(np.array([xs.mean(), ys.mean()]))
    if not cents:
        return []
    cents = np.array(cents)
    s = cents @ n          # perpendicular offset -> which row
    t = cents @ d          # position along the row

    # Cluster by perpendicular offset: sort by s, split where the gap > spacing.
    order = np.argsort(s)
    clusters, cur = [], [order[0]]
    for prev, idx in zip(order, order[1:]):
        if s[idx] - s[prev] > row_spacing_px:
            clusters.append(cur)
            cur = [idx]
        else:
            cur.append(idx)
    clusters.append(cur)

    polylines = []
    for cl in clusters:
        if len(cl) < 2:
            continue
        # Order the cluster's centroids along the row and build a polyline.
        cl = sorted(cl, key=lambda i: t[i])
        pts = [tuple(cents[i]) for i in cl]
        pts = [(float(x), float(y)) for x, y in pts]
        if len(pts) >= min_pts:
            pts = _rdp(pts, 8.0)
        if len(pts) >= 2:
            polylines.append(pts)
    return polylines


def rows_from_prediction(result, min_area_px=400):
    """A single Ultralytics result (one tile) -> list of row dicts.

    Two-stage: (1) collect vine_row instance masks; (2) assemble them into
    physical rows using one dominant per-tile angle + perpendicular clustering.
    The row direction comes from the collective mask pattern, not any single
    mask (a single blob is too round to carry direction).
    """
    rows = []
    if result.masks is None:
        return rows
    cls = result.boxes.cls.cpu().numpy().astype(int)
    # Resolve which class index is the row, by name if possible.
    names = getattr(result, "names", None) or {}
    row_idx = {i for i, nm in names.items()
               if str(nm).lower() in ("row", "vine_row")}
    if not row_idx:
        row_idx = {VINE_ROW_CLS}
    orig_h, orig_w = result.orig_shape
    masks = []
    for i, m in enumerate(result.masks.data.cpu().numpy()):
        if cls[i] not in row_idx:
            continue
        mask = (m > 0.5).astype(np.uint8)
        if mask.shape != (orig_h, orig_w):
            mask = cv2.resize(mask, (orig_w, orig_h), interpolation=cv2.INTER_NEAREST)
        if mask.sum() < min_area_px:
            continue
        masks.append(mask)

    for poly in _assemble_rows(masks, (orig_h, orig_w)):
        rows.append({
            "points": poly,
            "vineyard_id": "",       # Task 7 fills globally
            "row_id": "",            # Task 7 fills globally (provisional set by caller)
            "row_structure": "regular",  # Task 5 refines (disrupted if gap >=5m)
        })
    return rows


def assign_provisional_ids(rows, tile_stem):
    """Give each row a per-tile provisional row_id so counts/measurements are
    meaningful before global ID assignment (Task 7) runs. Global IDs overwrite
    these once rows are stitched across tiles."""
    for k, r in enumerate(rows):
        r["row_id"] = f"{tile_stem}-R{k:02d}"
    return rows


def _row_masks_from_result(result, min_area_px=400):
    """Extract full-resolution binary row masks from one Ultralytics result."""
    out = []
    if result.masks is None:
        return out
    cls = result.boxes.cls.cpu().numpy().astype(int)
    names = getattr(result, "names", None) or {}
    row_idx = {i for i, nm in names.items()
               if str(nm).lower() in ("row", "vine_row")}
    if not row_idx:
        row_idx = {VINE_ROW_CLS}
    h, w = result.orig_shape
    for i, m in enumerate(result.masks.data.cpu().numpy()):
        if cls[i] not in row_idx:
            continue
        mask = (m > 0.5).astype(np.uint8)
        if mask.shape != (h, w):
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
        if mask.sum() >= min_area_px:
            out.append(mask)
    return out


def _centreline_from_mask(mask, n_bins=12, min_bin_px=15):
    """One connected row mask -> centreline polyline via PCA major axis.

    Project the foreground pixels onto the mask's principal axis, bin along it,
    and take the perpendicular-mean per bin. A curved row yields a bent polyline
    (bends captured by the binning) rather than a single straight chord.
    """
    ys, xs = np.nonzero(mask)
    if xs.size < min_bin_px:
        return []
    pts = np.stack([xs, ys], axis=1).astype(np.float64)   # (N,2) as (x,y)
    mean = pts.mean(axis=0)
    cov = np.cov((pts - mean).T)
    evals, evecs = np.linalg.eigh(cov)
    d = evecs[:, int(np.argmax(evals))]                   # major axis (along-row)
    n = np.array([-d[1], d[0]])                           # perpendicular
    t = (pts - mean) @ d
    s = (pts - mean) @ n
    t0, t1 = t.min(), t.max()
    if t1 - t0 < 1e-6:
        return []
    edges = np.linspace(t0, t1, n_bins + 1)
    centre = []
    for i in range(n_bins):
        sel = (t >= edges[i]) & (t <= edges[i + 1])
        if sel.sum() < min_bin_px:
            continue
        tt = 0.5 * (edges[i] + edges[i + 1])
        ss = s[sel].mean()
        p = mean + tt * d + ss * n
        centre.append((float(p[0]), float(p[1])))
    if len(centre) < 2:
        return []
    return _rdp(centre, 8.0)


def _merge_collinear(rows, gap_tol=90.0, angle_tol_deg=12.0):
    """Join polylines that are two end-to-end pieces of the SAME row line.

    Safe rule: only merge if the nearest endpoints of two polylines are within
    gap_tol px AND the two segments point the same way (heading difference under
    angle_tol_deg) AND joining doesn't kink (the join direction matches both
    segment headings). This bridges a row split by a gap without ever zig-zagging
    into a neighbouring row.
    """
    if len(rows) <= 1:
        return rows

    def heading(pts):
        a, b = np.array(pts[0]), np.array(pts[-1])
        v = b - a
        nrm = np.hypot(*v)
        return v / nrm if nrm > 1e-6 else v

    segs = [{"pts": [np.array(p, float) for p in r["points"]]} for r in rows]
    changed = True
    while changed:
        changed = False
        for i in range(len(segs)):
            if segs[i] is None:
                continue
            for j in range(i + 1, len(segs)):
                if segs[j] is None:
                    continue
                A, B = segs[i]["pts"], segs[j]["pts"]
                hA, hB = heading(A), heading(B)
                if abs(np.degrees(np.arccos(np.clip(abs(hA @ hB), -1, 1)))) > angle_tol_deg:
                    continue
                # nearest end-to-end endpoint gap (either orientation)
                best = min(np.hypot(*(A[-1] - B[0])), np.hypot(*(B[-1] - A[0])),
                           np.hypot(*(A[0] - B[0])), np.hypot(*(A[-1] - B[-1])))
                if best > gap_tol:
                    continue
                # order the union of points along the shared heading and join
                allp = A + B
                origin = allp[0]
                allp = sorted(allp, key=lambda p: (p - origin) @ hA)
                segs[i]["pts"] = allp
                segs[j] = None
                changed = True
        segs = [s for s in segs if s is not None]

    out = []
    for s in segs:
        pts = [(float(p[0]), float(p[1])) for p in s["pts"]]
        if len(pts) >= 3:
            pts = _rdp(pts, 8.0)
        if len(pts) >= 2:
            out.append({"points": pts, "vineyard_id": "", "row_id": "",
                        "row_structure": "regular"})
    return out


def _filter_rows(rows, min_len_px=300.0, max_angdev_deg=15.0,
                 min_straightness=0.90, min_keep=6):
    """Drop non-vineyard false positives by geometry.

    Real vine rows are LONG, PARALLEL (one shared planting angle) and STRAIGHT;
    model false positives on forest / bare field / grass are short, randomly
    oriented, and kinked — they wander along tree gaps or track edges (see
    30_FINDINGS 2026-09-26). Keep a polyline only if it is:
      - longer than min_len_px,
      - within max_angdev_deg of the tile's length-weighted dominant row angle,
      - straight: end-to-end distance / path length >= min_straightness.

    Guard: if fewer than min_keep rows survive, this tile probably isn't a
    vineyard at all — return NOTHING rather than a handful of borderline junk.
    """
    if not rows:
        return rows

    # length-weighted dominant angle on [0, pi) via doubled-angle mean
    sin2 = cos2 = 0.0
    for r in rows:
        p = np.array(r["points"], float)
        for a, b in zip(p, p[1:]):
            v = b - a
            L = np.hypot(*v)
            if L > 1:
                ang = np.arctan2(v[1], v[0])
                sin2 += np.sin(2 * ang) * L
                cos2 += np.cos(2 * ang) * L
    dom = 0.5 * np.arctan2(sin2, cos2)

    kept = []
    for r in rows:
        p = np.array(r["points"], float)
        path = np.hypot(*(p[1:] - p[:-1]).T).sum()
        if path < min_len_px:
            continue
        chord = np.hypot(*(p[-1] - p[0]))
        if chord / max(path, 1e-6) < min_straightness:      # kinked -> junk
            continue
        v = p[-1] - p[0]
        ang = np.arctan2(v[1], v[0])
        dev = abs(ang - dom) % np.pi
        dev = min(dev, np.pi - dev)
        if np.degrees(dev) > max_angdev_deg:
            continue
        kept.append(r)

    if len(kept) < min_keep:
        return []
    return kept


def predict_tile(model, tile_path, conf=0.25, imgsz=2048, tiled=None,
                 patch=640, stride=480):
    """Run the model on one tile, return list of row dicts + (w,h).

    tiled=None auto-selects: a single-class ('row') model was trained on 640px
    patches, so we slice the 2048 tile into 640 patches, predict each, and
    composite the masks back — otherwise a 640-trained model barely fires on a
    full 2048 image. The 2-class Riseholme model runs whole-tile as before.
    """
    img = cv2.imread(str(tile_path))
    H, W = img.shape[:2]

    if tiled is None:
        names = {str(v).lower() for v in getattr(model, "names", {}).values()}
        tiled = names == {"row"} or (len(names) == 1 and "row" in names)

    if not tiled:
        res = model.predict(str(tile_path), conf=conf, imgsz=imgsz, verbose=False)[0]
        return rows_from_prediction(res), (W, H)

    # tiled: composite row masks from 640 patches into one full-tile union.
    union = np.zeros((H, W), np.uint8)
    xs = list(range(0, max(1, W - patch + 1), stride)) + [W - patch]
    ys = list(range(0, max(1, H - patch + 1), stride)) + [H - patch]
    for y0 in sorted(set(ys)):
        for x0 in sorted(set(xs)):
            crop = img[y0:y0 + patch, x0:x0 + patch]
            res = model.predict(crop, conf=conf, imgsz=patch, verbose=False)[0]
            for m in _row_masks_from_result(res, min_area_px=50):
                union[y0:y0 + patch, x0:x0 + patch] |= m

    # Bridge gaps ALONG the row direction so a row split into 2 segments by a
    # missing-plant gap becomes one component (schema: that's a `disrupted` row,
    # still one polyline). Close with a line kernel oriented at the dominant angle.
    if union.any():
        ang = _dominant_angle(union)
        L = 41  # bridge up to ~1 m gaps along the row
        kern = np.zeros((L, L), np.uint8)
        cv2.line(kern, (int(L/2 - (L/2)*np.cos(ang)), int(L/2 - (L/2)*np.sin(ang))),
                 (int(L/2 + (L/2)*np.cos(ang)), int(L/2 + (L/2)*np.sin(ang))), 1, 3)
        union = cv2.morphologyEx(union, cv2.MORPH_CLOSE, kern)

    # Each connected component in the union is now ONE full row stripe, so fit a
    # centreline per component directly (per-instance PCA). The old
    # centroid-clustering assembler collapsed 35 clean stripes into ~3 rows.
    n, lbl = cv2.connectedComponents(union)
    rows = []
    for k in range(1, n):
        comp = (lbl == k).astype(np.uint8)
        if comp.sum() < 400:
            continue
        poly = _centreline_from_mask(comp)
        if len(poly) >= 2:
            rows.append({"points": poly, "vineyard_id": "", "row_id": "",
                         "row_structure": "regular"})
    rows = _merge_collinear(rows)
    rows = _filter_rows(rows)
    return rows, (W, H)


def _overlay(tile_path, rows, out_path):
    """Debug overlay: draw polylines on the tile."""
    img = cv2.imread(str(tile_path))
    for r in rows:
        pts = np.array(r["points"], dtype=np.int32)
        cv2.polylines(img, [pts], isClosed=False, color=(0, 0, 255), thickness=6)
        for x, y in pts:
            cv2.circle(img, (int(x), int(y)), 8, (0, 255, 255), -1)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)


if __name__ == "__main__":
    from cvat_writer import write_cvat_xml
    from measurements import compute_measurements, write_csv

    ex = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat/images")
    out_dir = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/output")
    model = YOLO(str(BEST))

    objects_by_tile = {}
    for tile in sorted(ex.glob("*.tif")):
        rows, (w, h) = predict_tile(model, tile)
        assign_provisional_ids(rows, tile.stem)
        print(f"{tile.name}: {len(rows)} rows, tile {w}x{h}")
        _overlay(tile, rows, out_dir / f"rows_{tile.stem}.png")
        for j, r in enumerate(rows[:3]):
            pts = r["points"]
            print(f"  row {j}: {len(pts)} pts, "
                  f"({pts[0][0]:.0f},{pts[0][1]:.0f})->({pts[-1][0]:.0f},{pts[-1][1]:.0f})")
        objects_by_tile[tile.name] = {
            "width": w, "height": h,
            "vineyard": [], "interrow_area": [], "waste": [], "row": rows,
        }
    print(f"Overlays written to {out_dir}/rows_*.png")

    # Round-trip through the CVAT writer (must parse back cleanly).
    xml_out = out_dir / "annotations_rows.xml"
    write_cvat_xml(objects_by_tile, xml_out)

    # Real row measurements (count + total length in metres).
    m = compute_measurements(objects_by_tile, ex)
    print(f"\nrow_count          : {m['row_count']}")
    print(f"total_row_length_m : {m['total_row_length_m']:.1f}")
    write_csv(m, out_dir / "measurements_rows.csv")
