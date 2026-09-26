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

from ultralytics import YOLO

from rows_postproc import BEST, predict_tile
from cvat_writer import write_cvat_xml
from measurements import compute_measurements, write_csv
from assign_ids import assign_global_ids

TILES_ROOT = Path("/Users/luka-sap/Desktop/Gigahack/01_tiles")
OUT_DIR = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/output")


def discover_tiles(tiles_root):
    """All *.tif tiles across the 5 part directories, sorted by name."""
    return sorted(Path(tiles_root).rglob("siret3_*.tif"))


def run(tiles, model, conf=0.25):
    """Run the model on each tile -> objects_by_tile dict."""
    objects_by_tile = {}
    t0 = time.time()
    for i, tile in enumerate(tiles, 1):
        rows, (w, h) = predict_tile(model, tile, conf=conf)
        objects_by_tile[tile.name] = {
            "width": w, "height": h,
            "vineyard": [], "interrow_area": [], "waste": [], "row": rows,
        }
        print(f"[{i}/{len(tiles)}] {tile.name}: {len(rows)} rows "
              f"({(time.time() - t0) / i:.1f}s/tile avg)")
    return objects_by_tile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="only process the first N tiles (dry run)")
    ap.add_argument("--tiles-dir", default=str(TILES_ROOT))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--tag", default="all",
                    help="suffix for output filenames (e.g. 'sample')")
    args = ap.parse_args()

    tiles = discover_tiles(args.tiles_dir)
    print(f"Discovered {len(tiles)} tiles under {args.tiles_dir}")
    if args.limit:
        tiles = tiles[:args.limit]
        print(f"Limiting to first {len(tiles)} tiles (dry run)")

    model = YOLO(str(BEST))
    objects_by_tile = run(tiles, model, conf=args.conf)

    # Global ID assignment (Task 7): stitch rows across tiles in world space,
    # overwriting the provisional per-tile ids with consistent vineyard_id/row_id.
    tiles_root = Path(args.tiles_dir)
    nb, nr = assign_global_ids(objects_by_tile, tiles_root)
    print(f"Global IDs: {nb} blocks, {nr} stitched rows")

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
