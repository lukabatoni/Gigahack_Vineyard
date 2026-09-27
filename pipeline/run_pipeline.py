"""
Flow A / Block A2: pipeline orchestrator.

Iterates the challenge tiles, runs the model on each, assembles the per-tile
`objects_by_tile` dict (see 50_PARALLEL_WORK §3), and writes the two scored
artifacts:
    - annotations.xml   (CVAT 1.1, via cvat_writer)
    - measurements.csv  (via measurements)

Right now it fills only the `row` layer (Block A1). canopy / interrow / waste
plug in here as A3 / A4 / Lane-B land — each just adds its list to the tile dict.
Rows get a PROVISIONAL per-tile row_id; global IDs are Task 7 (A4).

Usage:
    python run_pipeline.py --limit 5          # 5-tile dry run (fast, MPS-friendly)
    python run_pipeline.py                     # all 311 tiles (slow; run after training)
    python run_pipeline.py --tiles-dir <path>  # override tile root
"""
import argparse
import time
from pathlib import Path

import numpy as np
import cv2
import rasterio
from ultralytics import YOLO

from rows_postproc import BEST, predict_tile
from cvat_writer import write_cvat_xml
from measurements import compute_measurements, write_csv
from assign_ids import assign_global_ids
from segment_canopy import segment_tile
from interrow import derive_interrow

TILES_ROOT = Path("/Users/luka-sap/Desktop/Gigahack/01_tiles")
OUT_DIR = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/output")
ANNOTATED_DIR = Path("/Users/luka-sap/Desktop/Gigahack/annotated_tiles")


def write_annotated_tile(tile_path, objs, out_dir):
    """Draw the tile's row polylines on the imagery and save as a georeferenced
    GeoTIFF (same CRS/transform), filename + '_annotated.tif'.

    Reads via rasterio to preserve the profile, draws with cv2, writes back
    through rasterio so the output stays a valid EPSG:32635 GeoTIFF."""
    with rasterio.open(tile_path) as src:
        profile = src.profile
        # bands -> HxWxC uint8 RGB for drawing (tiles are 3-band RGB)
        arr = src.read()                      # (bands, H, W)
    n_bands = arr.shape[0]
    rgb = np.transpose(arr[:3], (1, 2, 0)).copy()      # (H, W, 3)
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)

    for o in objs.get("interrow_area", []):
        pts = np.array(o["points"], dtype=np.int32)
        if len(pts) >= 3:
            cv2.polylines(rgb, [pts], isClosed=True, color=(0, 200, 255), thickness=2)

    for o in objs.get("vineyard", []):
        pts = np.array(o["points"], dtype=np.int32)
        if len(pts) >= 3:
            cv2.polylines(rgb, [pts], isClosed=True, color=(0, 255, 0), thickness=2)

    for r in objs.get("row", []):
        pts = np.array(r["points"], dtype=np.int32)
        cv2.polylines(rgb, [pts], isClosed=False, color=(255, 0, 0), thickness=6)
        rid = r.get("row_id", "")
        if rid and len(pts):
            cv2.putText(rgb, rid, tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, (255, 255, 0), 3, cv2.LINE_AA)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tile_path.stem}_annotated.tif"
    out_bands = np.transpose(rgb, (2, 0, 1))           # (3, H, W)
    profile.update(count=3, dtype="uint8")
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(out_bands)
    return out_path


def discover_tiles(tiles_root, stems=None):
    """All *.tif tiles across the 5 part directories, sorted by name.

    If `stems` is given (e.g. ['r006_c004', 'siret3_r005_c004']), keep only tiles
    whose filename contains one of those stems — lets us run a small named subset.
    """
    tiles = sorted(Path(tiles_root).rglob("siret3_*.tif"))
    if stems:
        stems = [s if s.startswith("siret3_") else f"siret3_{s}" for s in stems]
        wanted = set(stems)
        tiles = [t for t in tiles if t.stem in wanted]
    return tiles


def run(tiles, model, conf=0.25, do_canopy=True):
    """Run the model on each tile -> (objects_by_tile, tile_paths)."""
    objects_by_tile = {}
    tile_paths = {}
    t0 = time.time()
    for i, tile in enumerate(tiles, 1):
        rows, (w, h) = predict_tile(model, tile, conf=conf)
        canopy = segment_tile(tile) if do_canopy else []
        objects_by_tile[tile.name] = {
            "width": w, "height": h,
            "vineyard": canopy, "interrow_area": [], "waste": [], "row": rows,
        }
        tile_paths[tile.name] = tile
        print(f"[{i}/{len(tiles)}] {tile.name}: {len(rows)} rows, "
              f"{len(canopy)} canopies ({(time.time() - t0) / i:.1f}s/tile avg)")
    return objects_by_tile, tile_paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="only process the first N tiles (dry run)")
    ap.add_argument("--tiles-dir", default=str(TILES_ROOT))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--tag", default="all",
                    help="suffix for output filenames (e.g. 'sample')")
    ap.add_argument("--tiles-list", default=None,
                    help="comma-separated tile stems to run (e.g. r006_c004,r005_c004)")
    ap.add_argument("--no-canopy", action="store_true",
                    help="skip canopy segmentation (rows only)")
    ap.add_argument("--no-annotated", action="store_true",
                    help="skip writing annotated GeoTIFF tiles")
    ap.add_argument("--annotated-dir", default=str(ANNOTATED_DIR))
    args = ap.parse_args()

    stems = [s.strip() for s in args.tiles_list.split(",")] if args.tiles_list else None
    tiles = discover_tiles(args.tiles_dir, stems=stems)
    print(f"Discovered {len(tiles)} tiles under {args.tiles_dir}"
          + (f" (filtered to {len(stems)} stems)" if stems else ""))
    if args.limit:
        tiles = tiles[:args.limit]
        print(f"Limiting to first {len(tiles)} tiles (dry run)")

    model = YOLO(str(BEST))
    objects_by_tile, tile_paths = run(tiles, model, conf=args.conf,
                                      do_canopy=not args.no_canopy)

    # Global ID assignment (Task 7): stitch rows across tiles in world space,
    # overwriting the provisional per-tile ids with consistent vineyard_id/row_id.
    # Also tags each canopy polygon with its block's vineyard_id.
    tiles_root = Path(args.tiles_dir)
    nb, nr = assign_global_ids(objects_by_tile, tiles_root)
    print(f"Global IDs: {nb} blocks, {nr} stitched rows")

    # Inter-row areas: derived per block from stitched rows minus canopy (Golden
    # Rule 4: canopy and inter-row never overlap). Fills objects_by_tile in place.
    n_ir = derive_interrow(objects_by_tile, tiles_root)
    print(f"Inter-row areas: {n_ir}")

    if not args.no_annotated:
        ann_dir = Path(args.annotated_dir)
        for name, objs in objects_by_tile.items():
            write_annotated_tile(tile_paths[name], objs, ann_dir)
        print(f"Annotated tiles -> {ann_dir} ({len(objects_by_tile)} files)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    xml_out = OUT_DIR / f"annotations_{args.tag}.xml"
    csv_out = OUT_DIR / f"measurements_{args.tag}.csv"
    write_cvat_xml(objects_by_tile, xml_out)

    m = compute_measurements(objects_by_tile, tiles_root)
    print(f"\n=== SUMMARY ({len(objects_by_tile)} tiles) ===")
    print(f"row_count          : {m['row_count']}")
    print(f"total_row_length_m : {m['total_row_length_m']:.1f}")
    print(f"block_count        : {m['block_count']}")
    write_csv(m, csv_out)


if __name__ == "__main__":
    main()
