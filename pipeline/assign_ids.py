"""
Flow A / Task 7: global ID assignment (vineyard_id, row_id).

The scored counts require IDs that are consistent ACROSS tiles: the same
physical block gets one vineyard_id everywhere, the same physical row gets one
row_id in every tile it crosses. We can't do this per tile — we must stitch in
world space (EPSG:32635), where the tile grid abuts exactly (each tile 51.2 m,
origins step by exactly 51.2 m — verified).

Pipeline:
  1. Convert every tile's row polylines -> world LineStrings (metres).
  2. Blocks: union-find over row segments; two segments share a block if they
     come within BLOCK_GAP_M of each other (docs: gap < 5 m = same block; a road
     separates blocks, so anything farther is a different block).
  3. Rows: within a block, union-find over segments that are (a) nearly parallel
     and (b) collinear (endpoints' extensions meet within ROW_MERGE_M) -> one
     physical row across tiles.
  4. Emit vineyard_id = V01.. per block, row_id = <vid>-R<nn> per stitched row.

Writes the IDs back into the per-tile row dicts in place (pixel geometry
untouched — only the id strings change). Downstream cvat_writer / measurements
then produce correct global counts.

NOTE: operates purely on row geometry. Once canopy polygons exist (A3), blocks
can be refined by canopy clustering too; rows-only is a solid first pass.
"""
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from measurements import pixels_to_world, tile_transform

BLOCK_GAP_M = 5.0      # docs: plantings closer than 5 m are the same block
ROW_PERP_M = 1.0       # perp offset from the shared centreline (rows are ~2 m apart)
ROW_MERGE_M = 4.0      # max end-to-end GAP along the line to still be one row
ROW_ANGLE_TOL_DEG = 20.0
MIN_ROWS_PER_BLOCK = 3  # docs: a vineyard block has >=3 rows; fewer = FP fragment


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def _to_world_segments(objects_by_tile, tiles_dir):
    """-> list of dicts: {tile, idx, line(LineString world), ang(rad)}.
    idx is the position in that tile's 'row' list, so we can write ids back."""
    tiles_dir = Path(tiles_dir)
    segs = []
    for tile_name, objs in objects_by_tile.items():
        rows = objs.get("row", [])
        if not rows:
            continue
        tif = tiles_dir / tile_name
        if not tif.exists():
            found = list(tiles_dir.rglob(tile_name))
            if not found:
                continue
            tif = found[0]
        transform, _ = tile_transform(tif)
        for idx, r in enumerate(rows):
            world = pixels_to_world(r["points"], transform)
            if len(world) < 2:
                continue
            line = LineString(world)
            (x0, y0), (x1, y1) = world[0], world[-1]
            ang = np.arctan2(y1 - y0, x1 - x0) % np.pi   # undirected [0,pi)
            segs.append({"tile": tile_name, "idx": idx, "line": line, "ang": ang})
    return segs


def _angle_close(a, b, tol_rad):
    d = abs(a - b) % np.pi
    d = min(d, np.pi - d)
    return d <= tol_rad


def _same_rowline(si, sj, perp_tol, gap_tol):
    """True if segments si, sj are two pieces of ONE physical row.

    A row is a single straight centreline. Two segments belong to it only if
    the SECOND lies on the FIRST's infinite line (perpendicular offset small)
    AND the along-line gap between them is small. Merely being close (di<=4 m)
    is NOT enough: adjacent parallel rows are ~2 m apart and would chain-merge
    the whole block into one row. We test perpendicular offset instead.
    """
    xi, yi = si["line"].coords[0]
    xj0, yj0 = sj["line"].coords[0]
    xj1, yj1 = sj["line"].coords[-1]
    a = si["ang"]
    d = np.array([np.cos(a), np.sin(a)])       # along-row unit
    nrm = np.array([-np.sin(a), np.cos(a)])    # perpendicular unit
    for (px, py) in ((xj0, yj0), (xj1, yj1)):
        off = abs((px - xi) * nrm[0] + (py - yi) * nrm[1])
        if off > perp_tol:
            return False
    # along-line gap: distance between the two segments' spans on axis d
    ti = sorted((0.0, (si["line"].coords[-1][0] - xi) * d[0]
                 + (si["line"].coords[-1][1] - yi) * d[1]))
    tj = sorted(((xj0 - xi) * d[0] + (yj0 - yi) * d[1],
                 (xj1 - xi) * d[0] + (yj1 - yi) * d[1]))
    gap = max(tj[0] - ti[1], ti[0] - tj[1], 0.0)
    return gap <= gap_tol


def assign_global_ids(objects_by_tile, tiles_dir):
    """Mutates objects_by_tile in place: fills vineyard_id + row_id on every row.
    Returns (n_blocks, n_rows)."""
    segs = _to_world_segments(objects_by_tile, tiles_dir)
    n = len(segs)
    if n == 0:
        return 0, 0

    # --- blocks: union any two segments whose lines come within BLOCK_GAP_M ---
    block_uf = _UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            if segs[i]["line"].distance(segs[j]["line"]) <= BLOCK_GAP_M:
                block_uf.union(i, j)

    # --- rows: within a block, union nearly-parallel + collinear segments ---
    row_uf = _UF(n)
    tol = np.radians(ROW_ANGLE_TOL_DEG)
    for i in range(n):
        for j in range(i + 1, n):
            if block_uf.find(i) != block_uf.find(j):
                continue
            if not _angle_close(segs[i]["ang"], segs[j]["ang"], tol):
                continue
            # collinear test: j must lie on i's centreline (small perp offset)
            # AND close end-to-end along it. Symmetric check both directions.
            if (_same_rowline(segs[i], segs[j], ROW_PERP_M, ROW_MERGE_M)
                    or _same_rowline(segs[j], segs[i], ROW_PERP_M, ROW_MERGE_M)):
                row_uf.union(i, j)

    # --- label blocks V01.. (stable order by min easting of the block) ---
    block_members = defaultdict(list)
    for i in range(n):
        block_members[block_uf.find(i)].append(i)

    # --- prune false-positive blocks: a real vineyard block has >= MIN_ROWS_PER_BLOCK
    # distinct stitched rows. Isolated fence/track/furrow segments cluster into
    # 1-2 row blocks (see 30_FINDINGS) — drop them entirely so they don't inflate
    # block_count / row_count or pollute the CVAT export + route targets. ---
    dropped = set()
    for broot, members in block_members.items():
        distinct_rows = {row_uf.find(i) for i in members}
        if len(distinct_rows) < MIN_ROWS_PER_BLOCK:
            dropped.update(members)
    if dropped:
        for tile_name, objs in objects_by_tile.items():
            drop_idx = {segs[i]["idx"] for i in dropped if segs[i]["tile"] == tile_name}
            objs["row"] = [r for k, r in enumerate(objs.get("row", []))
                           if k not in drop_idx]
        # re-run clustering + labeling on the pruned set for clean, dense IDs
        return assign_global_ids(objects_by_tile, tiles_dir)

    block_order = sorted(block_members,
                         key=lambda r: min(segs[i]["line"].bounds[0] for i in block_members[r]))
    block_vid = {root: f"V{k + 1:02d}" for k, root in enumerate(block_order)}

    # --- label rows within each block R01.. (order by perpendicular position) ---
    row_members = defaultdict(list)
    for i in range(n):
        row_members[row_uf.find(i)].append(i)

    seg_vid = [None] * n
    seg_rid = [None] * n
    for broot in block_order:
        vid = block_vid[broot]
        rows_here = {r for r in row_members if block_uf.find(r) == broot}
        # order rows by their mean centroid projected on the block's cross-axis
        def _key(rroot):
            xs = [segs[i]["line"].centroid.x for i in row_members[rroot]]
            ys = [segs[i]["line"].centroid.y for i in row_members[rroot]]
            return (np.mean(xs), np.mean(ys))
        for k, rroot in enumerate(sorted(rows_here, key=_key), 1):
            rid = f"{vid}-R{k:02d}"
            for i in row_members[rroot]:
                seg_vid[i] = vid
                seg_rid[i] = rid

    # --- write ids back into the per-tile row dicts ---
    for s, vid, rid in zip(segs, seg_vid, seg_rid):
        row = objects_by_tile[s["tile"]]["row"][s["idx"]]
        row["vineyard_id"] = vid
        row["row_id"] = rid

    # --- tag canopy polygons with their block's vineyard_id ---
    # Each block's footprint = buffered union of its row lines (rows span the
    # planting). A canopy centroid inside a footprint gets that block's id; if it
    # sits outside every footprint (edge plants), snap to the nearest block.
    block_hull = {}
    for broot in block_order:
        lines = [segs[i]["line"] for i in block_members[broot]]
        block_hull[block_vid[broot]] = unary_union(lines).buffer(BLOCK_GAP_M)
    _assign_canopy_vids(objects_by_tile, tiles_dir, block_hull)

    return len(block_order), len(row_members)


def _assign_canopy_vids(objects_by_tile, tiles_dir, block_hull):
    """Set vineyard_id on every canopy polygon from the block footprints."""
    if not block_hull:
        return
    tiles_dir = Path(tiles_dir)
    for tile_name, objs in objects_by_tile.items():
        canopies = objs.get("vineyard", [])
        if not canopies:
            continue
        tif = tiles_dir / tile_name
        if not tif.exists():
            found = list(tiles_dir.rglob(tile_name))
            if not found:
                continue
            tif = found[0]
        transform, _ = tile_transform(tif)
        for c in canopies:
            world = pixels_to_world(c["points"], transform)
            if len(world) < 3:
                c["vineyard_id"] = ""
                continue
            cx = sum(p[0] for p in world) / len(world)
            cy = sum(p[1] for p in world) / len(world)
            pt = Point(cx, cy)
            inside = [vid for vid, hull in block_hull.items() if hull.contains(pt)]
            if inside:
                c["vineyard_id"] = inside[0]
            else:
                c["vineyard_id"] = min(block_hull, key=lambda v: block_hull[v].distance(pt))


if __name__ == "__main__":
    # Exercise on the 2 example tiles via the real model + rows_postproc.
    from ultralytics import YOLO
    from rows_postproc import BEST, predict_tile

    ex = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat/images")
    model = YOLO(str(BEST))
    obt = {}
    for tile in sorted(ex.glob("*.tif")):
        rows, (w, h) = predict_tile(model, tile)
        obt[tile.name] = {"width": w, "height": h,
                          "vineyard": [], "interrow_area": [], "waste": [], "row": rows}

    nb, nr = assign_global_ids(obt, ex)
    print(f"blocks={nb}  rows={nr}")
    for name, objs in obt.items():
        vids = sorted({r["vineyard_id"] for r in objs["row"]})
        rids = sorted({r["row_id"] for r in objs["row"]})
        print(f"  {name}: {len(objs['row'])} segs, vids={vids}, {len(rids)} row_ids")
