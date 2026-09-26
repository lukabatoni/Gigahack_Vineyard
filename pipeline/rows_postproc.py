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

import numpy as np
import cv2
from ultralytics import YOLO

BEST = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/runs/segment/riseholme/weights/best.pt")
VINE_ROW_CLS = 1  # data.yaml: {0: trunk, 1: vine_row}


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
    orig_h, orig_w = result.orig_shape
    masks = []
    for i, m in enumerate(result.masks.data.cpu().numpy()):
        if cls[i] != VINE_ROW_CLS:
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


def predict_tile(model, tile_path, conf=0.25, imgsz=2048):
    """Run the model on one tile, return list of row dicts + (w,h)."""
    res = model.predict(str(tile_path), conf=conf, imgsz=imgsz, verbose=False)[0]
    h, w = res.orig_shape
    return rows_from_prediction(res), (w, h)


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
