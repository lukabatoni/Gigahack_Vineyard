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
from shapely.geometry import LineString

from measurements import pixels_to_world, tile_transform

BLOCK_GAP_M = 5.0      # docs: plantings closer than 5 m are the same block
ROW_MERGE_M = 4.0      # collinear segment endpoints closer than this = same row
ROW_ANGLE_TOL_DEG = 20.0


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
            # collinear test: each segment's endpoints lie near the other's line
            di = segs[i]["line"].distance(segs[j]["line"])
            if di <= ROW_MERGE_M:
                row_uf.union(i, j)

    # --- label blocks V01.. (stable order by min easting of the block) ---
    block_members = defaultdict(list)
    for i in range(n):
        block_members[block_uf.find(i)].append(i)
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

    return len(block_order), len(row_members)


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
