"""
Task 9 (Lane B): Walking-route planner.

Produces TWO routes over the authorised walkable surface, both EPSG:32635:
  - route.geojson         BLUE inspector route  (targets = waste ∪ inspection points) — SCORED
  - route_farmer.geojson  RED farmer route      (targets = waste only)               — display

Walkable surface = passages ⋃ inter-row areas, MINUS forbidden zones (MINUS canopy
when available). The route may only travel inside it. Hard scoring gates
(CLAUDE.md / 20_DECISIONS): >2% of length outside walkable OR not returning to
START within 5 m → route score 0.

Engine (block-by-block per 50_PARALLEL_WORK §5 B3): built against
`passages.geojson` + MOCK inter-row + MOCK targets first. Swap in Lane A's
`interrow.geojson` + real targets later (--interrow, --targets) with no code change.

Method: regular grid over the walkable polygon (nodes = points inside; edges =
4-neighbour segments that stay inside) → shortest paths (networkx) between START
and every target → nearest-neighbour + 2-opt TSP returning to START → stitch.

START: [629663.8, 5220195.3] EPSG:32635 (47.1225039N 28.7094577E) — organizer pre-test point.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import networkx as nx
import shapely
from shapely.geometry import shape, Point, LineString, mapping
from shapely.ops import unary_union
from scipy.spatial import cKDTree

REPO = Path(__file__).resolve().parent.parent
ROUTE_DIR = REPO / "02_route"
START_XY = (629663.8, 5220195.3)           # EPSG:32635 — organizer pre-test point
CRS_32635 = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32635"}}

RESOLUTION_M = 2.0        # grid spacing; snap error ≤ res/√2 ≈ 1.41 m (< 2 m coverage)
COVERAGE_M = 2.0          # route must pass within this of each target (scoring)
START_RETURN_M = 5.0      # must start & end within this of START (hard gate)
INSIDE_TOL_M = 0.5        # buffer tolerance when checking route stays inside walkable


# ── geometry loading ──────────────────────────────────────────────────────────
def load_union(path):
    feats = json.loads(Path(path).read_text()).get("features", [])
    if not feats:
        return None
    return unary_union([shape(f["geometry"]) for f in feats])


def build_walkable(passages, interrow=None, forbidden=None, canopy=None):
    parts = [g for g in (passages, interrow) if g is not None and not g.is_empty]
    walk = unary_union(parts).buffer(0)
    for cut in (forbidden, canopy):
        if cut is not None and not cut.is_empty:
            trial = walk.difference(cut)
            # never let the subtraction orphan the START point
            if not trial.is_empty and trial.distance(Point(START_XY)) < 1.0:
                walk = trial
    return walk


# ── nav graph over the walkable polygon ─────────────────────────────────────────
def build_graph(walkable, resolution):
    minx, miny, maxx, maxy = walkable.bounds
    xs = np.arange(minx, maxx + resolution, resolution)
    ys = np.arange(miny, maxy + resolution, resolution)
    gx, gy = np.meshgrid(xs, ys)
    gx, gy = gx.ravel(), gy.ravel()

    inside = shapely.contains_xy(walkable, gx, gy)          # vectorised (shapely 2.0)
    nx_pts = gx[inside]
    ny_pts = gy[inside]
    if len(nx_pts) == 0:
        raise RuntimeError("No grid nodes fell inside the walkable surface.")

    # map (col,row) integer grid index -> node id, so neighbours are O(1)
    col = np.round((nx_pts - minx) / resolution).astype(int)
    row = np.round((ny_pts - miny) / resolution).astype(int)
    node_of = {(int(c), int(r)): i for i, (c, r) in enumerate(zip(col, row))}
    coords = np.column_stack([nx_pts, ny_pts])

    # candidate 4-neighbour edges (E, N, NE, NW) — avoids duplicates
    diag = resolution * math.sqrt(2.0)
    offsets = [((1, 0), resolution), ((0, 1), resolution),
               ((1, 1), diag), ((-1, 1), diag)]
    seg_a, seg_b, weights = [], [], []
    for (dc, dr), w in offsets:
        for (c, r), i in node_of.items():
            j = node_of.get((c + dc, r + dr))
            if j is None:
                continue
            seg_a.append(coords[i]); seg_b.append(coords[j]); weights.append((i, j, w))

    # keep only segments fully inside the walkable surface (vectorised covers)
    lines = shapely.linestrings(np.stack([np.array(seg_a), np.array(seg_b)], axis=1))
    ok = shapely.covers(walkable, lines)

    G = nx.Graph()
    G.add_nodes_from(range(len(coords)))
    for keep, (i, j, w) in zip(ok, weights):
        if keep:
            G.add_edge(i, j, weight=w)
    return G, coords


def largest_component_with(G, seed_node):
    for comp in nx.connected_components(G):
        if seed_node in comp:
            return comp
    return {seed_node}


# ── targets ─────────────────────────────────────────────────────────────────────
def snap(tree, xy):
    _, idx = tree.query([xy])
    return int(idx[0])


def make_mock_targets(coords, reachable, start_node, seed=42):
    """Pick nodes from START's connected component as stand-in targets.
    Returns (inspection[], waste[]) as {id,x,y,node,kind}. Deterministic."""
    rng = np.random.default_rng(seed)
    pool = np.array(sorted(reachable - {start_node}))
    pick = rng.choice(pool, size=min(6, len(pool)), replace=False)
    targets = []
    for k, n in enumerate(pick):
        kind = "inspection" if k % 2 == 0 else "waste"
        x, y = coords[n]
        targets.append({"id": f"MOCK-{kind[:4].upper()}-{k:02d}", "x": float(x),
                        "y": float(y), "node": int(n), "kind": kind})
    inspection = [t for t in targets if t["kind"] == "inspection"]
    waste = [t for t in targets if t["kind"] == "waste"]
    return inspection, waste


def load_targets(path, tree):
    """Real targets file: FeatureCollection of Points with props {id,kind,vineyard_id,row_id}."""
    feats = json.loads(Path(path).read_text()).get("features", [])
    insp, waste = [], []
    for f in feats:
        x, y = f["geometry"]["coordinates"][:2]
        p = f.get("properties", {})
        t = {"id": p.get("id", ""), "x": x, "y": y, "node": snap(tree, (x, y)),
             "kind": p.get("kind", "waste")}
        (insp if t["kind"] == "inspection" else waste).append(t)
    return insp, waste


# ── TSP ─────────────────────────────────────────────────────────────────────────
def solve_order(dist):
    """Nearest-neighbour from index 0 (START) + 2-opt. dist is (n+1)x(n+1),
    index 0 = START. Returns visiting order of indices, START first & last."""
    n = dist.shape[0]
    if n <= 1:
        return [0, 0]
    unvisited = set(range(1, n))
    order = [0]
    cur = 0
    while unvisited:
        nxt = min(unvisited, key=lambda j: dist[cur][j])
        order.append(nxt); unvisited.remove(nxt); cur = nxt
    order.append(0)                                   # return to START

    def tour_len(o):
        return sum(dist[o[i]][o[i + 1]] for i in range(len(o) - 1))

    improved = True
    while improved:
        improved = False
        for i in range(1, len(order) - 2):
            for k in range(i + 1, len(order) - 1):
                cand = order[:i] + order[i:k + 1][::-1] + order[k + 1:]
                if tour_len(cand) + 1e-9 < tour_len(order):
                    order = cand; improved = True
    return order


# ── plan one route ──────────────────────────────────────────────────────────────
def plan_route(G, coords, walkable, start_node, targets):
    """targets: list of {node,...}. Returns (coords_list, length_m, stats)."""
    terminals = [start_node] + [t["node"] for t in targets]
    # dedupe terminals that snapped to the same node, keep START at 0
    seen, uniq = set(), []
    for t in terminals:
        if t not in seen:
            uniq.append(t); seen.add(t)
    terminals = uniq

    # pairwise shortest paths among terminals
    n = len(terminals)
    dist = np.full((n, n), np.inf)
    paths = {}
    for a, src in enumerate(terminals):
        lengths, ps = nx.single_source_dijkstra(G, src, weight="weight")
        for b, dst in enumerate(terminals):
            if dst in lengths:
                dist[a][b] = lengths[dst]
                paths[(a, b)] = ps[dst]

    reachable = [b for b in range(n) if np.isfinite(dist[0][b])]
    if len(reachable) < n:
        dropped = n - len(reachable)
        dist = dist[np.ix_(reachable, reachable)]
        remap = {new: old for new, old in enumerate(reachable)}
        order_local = solve_order(dist)
        order = [remap[o] for o in order_local]
    else:
        dropped = 0
        order = solve_order(dist)

    # stitch node paths between consecutive ordered terminals
    node_seq = []
    for i in range(len(order) - 1):
        seg = paths[(order[i], order[i + 1])]
        if node_seq and seg and node_seq[-1] == seg[0]:
            seg = seg[1:]
        node_seq.extend(seg)

    pts = [tuple(coords[n]) for n in node_seq]
    # literally begin & end at START so the return-to-START gate is exact
    pts = [START_XY] + pts + [START_XY]
    line = LineString(pts)
    length_m = line.length

    # validation — measure inside-fraction PER SEGMENT (a global intersection would
    # merge repeated traversals of the same corridor and understate the fraction)
    arr = np.asarray(pts)
    a, b = arr[:-1], arr[1:]
    seglens = np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])
    seglines = shapely.linestrings(np.stack([a, b], axis=1))
    inside_mask = shapely.covers(walkable.buffer(INSIDE_TOL_M), seglines)
    total = seglens.sum()
    inside_frac = float(seglens[inside_mask].sum() / total) if total else 0.0
    ends_ok = (Point(pts[0]).distance(Point(START_XY)) <= START_RETURN_M and
               Point(pts[-1]).distance(Point(START_XY)) <= START_RETURN_M)
    stats = {"length_m": length_m, "inside_frac": inside_frac,
             "targets": len(targets), "unreachable": dropped, "ends_ok": ends_ok,
             "gate_inside_ok": inside_frac >= 0.98, "n_terminals": n}
    return pts, length_m, stats


# ── output ────────────────────────────────────────────────────────────────────
def write_route(pts, length_m, out_path, name):
    fc = {"type": "FeatureCollection", "crs": CRS_32635, "features": [{
        "type": "Feature",
        "geometry": mapping(LineString(pts)),
        "properties": {"name": name, "length_m": round(length_m, 2)}}]}
    Path(out_path).write_text(json.dumps(fc))
    print(f"  wrote {Path(out_path).name}  length={length_m:.1f} m  points={len(pts)}")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passages", default=str(ROUTE_DIR / "passages.geojson"))
    ap.add_argument("--forbidden", default=str(ROUTE_DIR / "forbidden.geojson"))
    ap.add_argument("--interrow", default=None, help="Lane A interrow.geojson (EPSG:32635); mock if absent")
    ap.add_argument("--targets", default=None, help="targets FeatureCollection; mock if absent")
    ap.add_argument("--resolution", type=float, default=RESOLUTION_M)
    ap.add_argument("--out", default=str(REPO))
    args = ap.parse_args()

    print("Loading walkable surface …")
    passages = load_union(args.passages)
    forbidden = load_union(args.forbidden) if Path(args.forbidden).exists() else None
    interrow = load_union(args.interrow) if args.interrow and Path(args.interrow).exists() else None
    walkable = build_walkable(passages, interrow=interrow, forbidden=forbidden)
    print(f"  walkable area = {walkable.area/1e4:.2f} ha  "
          f"(interrow: {'real' if interrow else 'MOCK/none'})")

    print(f"Building nav graph (resolution {args.resolution} m) …")
    G, coords = build_graph(walkable, args.resolution)
    tree = cKDTree(coords)
    start_node = snap(tree, START_XY)
    reachable = largest_component_with(G, start_node)
    print(f"  {G.number_of_nodes()} nodes, {G.number_of_edges()} edges; "
          f"{len(reachable)} reachable from START")

    if args.targets and Path(args.targets).exists():
        insp, waste = load_targets(args.targets, tree)
        print(f"  targets: {len(insp)} inspection + {len(waste)} waste (real)")
    else:
        insp, waste = make_mock_targets(coords, reachable, start_node)
        print(f"  targets: {len(insp)} inspection + {len(waste)} waste (MOCK)")

    print("Planning BLUE inspector route (waste ∪ inspection) …")
    blue_targets = insp + waste
    blue_pts, blue_len, blue_stats = plan_route(G, coords, walkable, start_node, blue_targets)
    print("Planning RED farmer route (waste only) …")
    red_pts, red_len, red_stats = plan_route(G, coords, walkable, start_node, waste)

    out = Path(args.out)
    write_route(blue_pts, blue_len, out / "route.geojson", "inspector")
    write_route(red_pts, red_len, out / "route_farmer.geojson", "farmer")

    print("\nValidation (hard gates):")
    for label, s in [("blue/inspector", blue_stats), ("red/farmer", red_stats)]:
        gate = "PASS" if (s["gate_inside_ok"] and s["ends_ok"]) else "FAIL"
        print(f"  {label:16s} len={s['length_m']:7.1f}m  inside={s['inside_frac']*100:5.1f}%  "
              f"ends_ok={s['ends_ok']}  unreachable={s['unreachable']}  -> {gate}")


if __name__ == "__main__":
    main()
