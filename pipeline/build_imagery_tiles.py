"""
Build an XYZ (Web-Mercator / EPSG:3857) tile pyramid from the 311 Siret3 GeoTIFFs
so the web map can show our own 2.5 cm/px imagery as a basemap — far sharper than
any satellite provider and loaded on-demand ({z}/{x}/{y}.png).

Output: web/data/imagery/{z}/{x}/{y}.png  (RGBA; black no-data fill → transparent)

Pure rasterio + Pillow (no GDAL CLI, no mercantile). For each output tile we
reproject only the intersecting source tiles into its 256×256 window and paint
the covered pixels, so nothing large is held in memory.

Usage:
  python3 pipeline/build_imagery_tiles.py                 # default zoom 13..20
  python3 pipeline/build_imagery_tiles.py --minzoom 13 --maxzoom 21
"""
import argparse
import glob
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from affine import Affine
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
TILES_DIR = REPO / "01_tiles"
OUT_DIR = REPO / "web" / "data" / "imagery"
TILE_PX = 256
ORIGIN = 2.0 * math.pi * 6378137.0 / 2.0          # Web-Mercator half-extent (m)
WORLD = 2.0 * ORIGIN


def tile_bounds_3857(z, x, y):
    """3857 bounds (minx, miny, maxx, maxy) of XYZ tile (z, x, y)."""
    span = WORLD / (2 ** z)
    minx = -ORIGIN + x * span
    maxy = ORIGIN - y * span
    return minx, maxy - span, minx + span, maxy


def xy_range(z, minx, miny, maxx, maxy):
    """XYZ tile index range covering a 3857 bbox at zoom z."""
    span = WORLD / (2 ** z)
    x0 = int((minx + ORIGIN) // span)
    x1 = int((maxx + ORIGIN) // span)
    y0 = int((ORIGIN - maxy) // span)
    y1 = int((ORIGIN - miny) // span)
    return x0, x1, y0, y1


@lru_cache(maxsize=24)
def open_src(path):
    return rasterio.open(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", default=str(TILES_DIR))
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--minzoom", type=int, default=13)
    ap.add_argument("--maxzoom", type=int, default=20)
    args = ap.parse_args()

    src_paths = sorted(glob.glob(str(Path(args.tiles) / "siret3_*.tif")))
    if not src_paths:
        raise SystemExit(f"No tiles found in {args.tiles}")
    print(f"{len(src_paths)} source tiles")

    # precompute each source's 3857 bounds for fast intersection tests
    src_bounds = []
    data_minx = data_miny = 1e18
    data_maxx = data_maxy = -1e18
    for p in src_paths:
        with rasterio.open(p) as ds:
            b = ds.bounds
            mnx, mny, mxx, mxy = transform_bounds(ds.crs, "EPSG:3857",
                                                  b.left, b.bottom, b.right, b.top)
        src_bounds.append((p, mnx, mny, mxx, mxy))
        data_minx = min(data_minx, mnx); data_miny = min(data_miny, mny)
        data_maxx = max(data_maxx, mxx); data_maxy = max(data_maxy, mxy)

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    total = 0
    for z in range(args.minzoom, args.maxzoom + 1):
        x0, x1, y0, y1 = xy_range(z, data_minx, data_miny, data_maxx, data_maxy)
        z_count = 0
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                tminx, tminy, tmaxx, tmaxy = tile_bounds_3857(z, x, y)
                hits = [sp for sp in src_bounds
                        if not (sp[3] <= tminx or sp[1] >= tmaxx
                                or sp[4] <= tminy or sp[2] >= tmaxy)]
                if not hits:
                    continue
                span = (tmaxx - tminx) / TILE_PX
                dst_tf = Affine(span, 0, tminx, 0, -span, tmaxy)
                rgb = np.zeros((3, TILE_PX, TILE_PX), np.uint8)
                alpha = np.zeros((TILE_PX, TILE_PX), np.uint8)
                for p, *_ in hits:
                    ds = open_src(p)
                    tmp = np.zeros((3, TILE_PX, TILE_PX), np.uint8)
                    reproject(
                        source=rasterio.band(ds, (1, 2, 3)),
                        destination=tmp,
                        dst_transform=dst_tf,
                        dst_crs="EPSG:3857",
                        resampling=Resampling.bilinear,
                    )
                    covered = tmp.sum(axis=0) > 0        # black fill → skip
                    for b in range(3):
                        rgb[b][covered] = tmp[b][covered]
                    alpha[covered] = 255
                if not alpha.any():
                    continue
                arr = np.dstack([rgb[0], rgb[1], rgb[2], alpha])
                d = out_root / str(z) / str(x)
                d.mkdir(parents=True, exist_ok=True)
                Image.fromarray(arr).save(d / f"{y}.png")
                z_count += 1
        total += z_count
        print(f"  zoom {z}: {z_count} tiles")
    print(f"done: {total} tiles → {out_root}")


if __name__ == "__main__":
    main()
