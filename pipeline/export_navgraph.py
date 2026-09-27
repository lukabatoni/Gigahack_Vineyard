"""
Export the walking nav-graph to web/data/navgraph.json so the web app can
re-solve the route in-browser for any user-picked START (no backend needed).

Reuses pipeline/route_planner.py's own graph builder, so the graph the browser
solves on is IDENTICAL to the one that produces the scored route.geojson. Only
the largest connected component reachable from START is exported.

Output JSON (WGS84 for display, metres for edge weights):
  {
    "crs": "EPSG:4326",
    "start": {"lng":..,"lat":..},        # organizer default START, snapped
    "start_node": <int>,
    "nodes": [[lng,lat], ...],           # node index = position in this list
    "edges": [[i, j, weight_m], ...]     # undirected; weight is ground metres
  }

Usage:
  python3 pipeline/export_navgraph.py                      # passages-only (demo)
  python3 pipeline/export_navgraph.py --interrow interrow.geojson   # + real fields
  python3 pipeline/export_navgraph.py --interrow interrow.geojson --rows rows.geojson
"""
import argparse
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.ops import unary_union

import route_planner as rp

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "web" / "data" / "navgraph.json"
TO_WGS84 = Transformer.from_crs("EPSG:32635", "EPSG:4326", always_xy=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passages", default=str(rp.ROUTE_DIR / "passages.geojson"))
    ap.add_argument("--forbidden", default=str(rp.ROUTE_DIR / "forbidden.geojson"))
    ap.add_argument("--interrow", default=None)
    ap.add_argument("--rows", default=None, help="Row polylines (EPSG:32635); buffered and subtracted as barriers")
    ap.add_argument("--row-buffer", type=float, default=0.4, help="Buffer radius (m) around each row line")
    ap.add_argument("--resolution", type=float, default=rp.RESOLUTION_M)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    print("Loading walkable surface …")
    passages = rp.load_union(args.passages)
    forbidden = rp.load_union(args.forbidden) if Path(args.forbidden).exists() else None
    interrow = rp.load_union(args.interrow) if args.interrow and Path(args.interrow).exists() else None
    walkable = rp.build_walkable(passages, interrow=interrow, forbidden=forbidden)
    print(f"  walkable = {walkable.area/1e4:.2f} ha (interrow: {'real' if interrow else 'none'})")

    # subtract row buffers — human can walk in inter-row corridors but cannot cross vine rows
    if args.rows and Path(args.rows).exists():
        import json as _json
        from shapely.geometry import shape
        feats = _json.loads(Path(args.rows).read_text()).get("features", [])
        row_geoms = [shape(f["geometry"]) for f in feats if f.get("geometry")]
        if row_geoms:
            row_barrier = unary_union(row_geoms).buffer(args.row_buffer)
            before = walkable.area
            walkable = walkable.difference(row_barrier)
            print(f"  row barriers subtracted: {len(row_geoms)} lines × {args.row_buffer} m buffer "
                  f"→ removed {(before - walkable.area):.0f} m2")

    print(f"Building nav graph (resolution {args.resolution} m) …")
    G, coords = rp.build_graph(walkable, args.resolution)
    tree = cKDTree(coords)
    start_node = rp.snap(tree, rp.START_XY)
    comp = rp.largest_component_with(G, start_node)
    print(f"  {G.number_of_nodes()} nodes / {G.number_of_edges()} edges; "
          f"{len(comp)} reachable from START")

    # reindex the reachable component to a compact 0..m-1
    comp_sorted = sorted(comp)
    remap = {old: new for new, old in enumerate(comp_sorted)}

    # nodes → WGS84 lng/lat (rounded to ~1 cm)
    xs = coords[comp_sorted, 0]
    ys = coords[comp_sorted, 1]
    lon, lat = TO_WGS84.transform(xs, ys)
    nodes = [[round(float(a), 7), round(float(b), 7)] for a, b in zip(lon, lat)]

    # edges within the component, metric weights straight from the graph
    edges = []
    for u, v, w in G.edges(data="weight"):
        if u in remap and v in remap:
            edges.append([remap[u], remap[v], round(float(w), 3)])

    slon, slat = TO_WGS84.transform(*rp.START_XY)
    out = {
        "crs": "EPSG:4326",
        "start": {"lng": round(float(slon), 7), "lat": round(float(slat), 7)},
        "start_node": remap[start_node],
        "nodes": nodes,
        "edges": edges,
    }
    Path(args.out).write_text(json.dumps(out))
    mb = Path(args.out).stat().st_size / 1e6
    print(f"done: {len(nodes)} nodes, {len(edges)} edges → {args.out} ({mb:.1f} MB)")


if __name__ == "__main__":
    main()
