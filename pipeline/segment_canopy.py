"""
Task 3: Canopy segmentation — individual grapevine polygons per tile.

Approach:
  1. HSV + ExG green mask to isolate vine canopy pixels.
  2. Morphological cleanup (close intra-plant gaps, open to remove noise).
  3. Distance transform + local maxima → watershed markers (one seed per plant).
  4. Watershed splits touching canopies into individual plant regions.
  5. Contour extraction per watershed region + area filtering.

No row-angle assumptions. Works on any tile orientation.

Output per tile:
  List of dicts:
    { "points": [(x,y), ...],   # pixel coords, clockwise
      "label": "vineyard",
      "vineyard_id": ""         # filled in by global ID assignment (task 7)
    }
"""
import cv2
import numpy as np
import rasterio
from pathlib import Path
from typing import Union

# ── Tunable parameters ───────────────────────────────────────────────────────

# HSV hue range for secondary filter (keeps only plausible vegetation hues)
HSV_H_LOW,  HSV_H_HIGH  = 15, 55
HSV_S_LOW,  HSV_S_HIGH  = 30, 255
HSV_V_LOW,  HSV_V_HIGH  = 25, 255

# ExG absolute floor — never threshold below this even in dark blocks
EXG_THRESHOLD   = 15
# Percentile within each local block for adaptive threshold
EXG_PERCENTILE  = 87

# Morphological kernel sizes (pixels)
CLOSE_KERNEL_PX = 4         # closes gaps within a single plant canopy
OPEN_KERNEL_PX  = 2         # removes isolated noise specks

# Watershed: minimum distance between plant centres (pixels)
# Used as a starting point; adaptively scaled per tile below
MIN_PEAK_DIST_PX = 24

# Plant size range in pixels (2048×2048 tile, 2.5 cm/px)
# 0.15 m² → 0.15 / 0.025² = 240 px²
# 8.0 m²  → 8.0  / 0.025² = 12800 px²
MIN_AREA_PX = 240
MAX_AREA_PX = 12800


# ── Core functions ───────────────────────────────────────────────────────────

def excess_green(rgb: np.ndarray) -> np.ndarray:
    """ExG = 2G - R - B, clipped to [0,255] uint8."""
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    exg = (2 * g - r - b).clip(0, 255).astype(np.uint8)
    return exg


def green_mask(rgb: np.ndarray) -> np.ndarray:
    """
    Primary: ExG (Excess Green = 2G - R - B) with adaptive local threshold.
    The tile is divided into a grid of blocks; each block gets its own
    ExG threshold at the EXG_PERCENTILE of that block's ExG distribution.
    This handles uneven illumination across the tile.
    Secondary: HSV hue qualifier to suppress non-vegetation false positives.
    Returns uint8 binary mask (255 = vine canopy candidate).
    """
    R = rgb[:,:,0].astype(np.int16)
    G = rgb[:,:,1].astype(np.int16)
    B = rgb[:,:,2].astype(np.int16)
    exg = (2 * G - R - B).astype(np.float32)

    # Adaptive threshold: divide tile into 8x8 grid, threshold each block
    h, w = exg.shape
    block_h, block_w = h // 8, w // 8
    mask_exg = np.zeros((h, w), dtype=np.uint8)
    for r in range(8):
        for c in range(8):
            r0, r1 = r * block_h, (r + 1) * block_h if r < 7 else h
            c0, c1 = c * block_w, (c + 1) * block_w if c < 7 else w
            block = exg[r0:r1, c0:c1]
            thr   = np.percentile(block, EXG_PERCENTILE)
            mask_exg[r0:r1, c0:c1] = ((block > thr) & (block > EXG_THRESHOLD)).astype(np.uint8) * 255

    # HSV qualifier: retain only pixels with plausible vegetation hue
    hsv     = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    lo      = np.array([HSV_H_LOW,  HSV_S_LOW,  HSV_V_LOW],  dtype=np.uint8)
    hi      = np.array([HSV_H_HIGH, HSV_S_HIGH, HSV_V_HIGH], dtype=np.uint8)
    mask_hsv = cv2.inRange(hsv, lo, hi)

    return cv2.bitwise_and(mask_exg, mask_hsv)


def clean_mask(mask: np.ndarray) -> np.ndarray:
    """Morphological close (fill intra-plant gaps) then open (remove noise).
    Also removes connected components larger than MAX_AREA_PX (trees, bushes)
    before watershed so they never seed false canopies.
    """
    k_close = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (CLOSE_KERNEL_PX, CLOSE_KERNEL_PX))
    k_open  = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (OPEN_KERNEL_PX, OPEN_KERNEL_PX))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_close)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k_open)

    # Remove oversized blobs (trees, large bushes) — they are NOT individual vines
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        if cv2.contourArea(cnt) > MAX_AREA_PX:
            cv2.drawContours(mask, [cnt], -1, 0, thickness=cv2.FILLED)

    return mask


def extract_polygons(mask: np.ndarray, rgb: np.ndarray) -> list[dict]:
    """
    Watershed segmentation to split touching canopies into individual plants.
    Peak distance is derived adaptively from the distance transform of the tile
    so the same code works on dense and sparse canopy tiles.
    """
    from scipy.ndimage import label as nd_label

    # Distance transform — peaks = plant centres
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

    # Adaptive peak distance: use 60% of the median non-zero distance value,
    # clamped to [MIN_PEAK_DIST_PX, 50] so we never go absurdly large or small
    nz = dist[dist > 0]
    if len(nz) == 0:
        return []
    adaptive_dist = int(np.clip(np.median(nz) * 0.6, MIN_PEAK_DIST_PX, 50))

    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (adaptive_dist * 2 + 1, adaptive_dist * 2 + 1))
    dilated   = cv2.dilate(dist, kernel)
    local_max = (dist == dilated) & (dist > dist.max() * 0.08) & (mask > 0)

    markers, n_markers = nd_label(local_max)
    if n_markers == 0:
        return []

    # Watershed on inverted green channel (bright green = plant centre = valley)
    green    = rgb[:, :, 1].astype(np.uint8)
    topo_3ch = cv2.cvtColor(cv2.bitwise_not(green), cv2.COLOR_GRAY2BGR)
    markers_ws = markers.astype(np.int32)
    markers_ws[mask == 0] = -1
    cv2.watershed(topo_3ch, markers_ws)

    # One polygon per watershed region
    polygons = []
    for label_id in range(1, n_markers + 1):
        region = ((markers_ws == label_id) & (mask > 0)).astype(np.uint8) * 255
        area   = int(region.sum()) // 255
        if area < MIN_AREA_PX or area > MAX_AREA_PX:
            continue

        contours, _ = cv2.findContours(
            region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        if cv2.contourArea(cnt) < MIN_AREA_PX:
            continue

        epsilon = 0.004 * cv2.arcLength(cnt, True)
        approx  = cv2.approxPolyDP(cnt, epsilon, True)
        if len(approx) < 3:
            continue

        pts = [(float(p[0][0]), float(p[0][1])) for p in approx]
        polygons.append({
            "points":      pts,
            "label":       "vineyard",
            "vineyard_id": "",
        })

    return polygons


def segment_tile(tif_path: Union[str, Path]) -> list[dict]:
    """
    Full pipeline for one GeoTIFF tile.
    Returns list of vineyard polygon dicts (pixel coords).
    """
    with rasterio.open(tif_path) as src:
        rgb = src.read([1, 2, 3]).transpose(1, 2, 0)  # H×W×3 uint8

    mask    = green_mask(rgb)
    mask    = clean_mask(mask)
    polys   = extract_polygons(mask, rgb)
    return polys


# ── Visualisation helper (used by explore / debug scripts) ──────────────────

def draw_polygons_on_image(rgb: np.ndarray, polygons: list[dict]) -> np.ndarray:
    """Returns a copy of rgb with vineyard polygons drawn in green."""
    out = rgb.copy()
    for poly in polygons:
        pts = np.array(poly["points"], dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [pts], isClosed=True, color=(0, 220, 0), thickness=1)
        cv2.fillPoly(out, [pts], color=(0, 180, 0))  # semi-transparent not available in cv2
    return out


# ── Quick self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    EXAMPLES = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat/images")
    OUT_DIR  = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/output")
    OUT_DIR.mkdir(exist_ok=True)

    for tif in sorted(EXAMPLES.glob("*.tif")):
        print(f"\nSegmenting {tif.name} ...")
        with rasterio.open(tif) as src:
            rgb = src.read([1, 2, 3]).transpose(1, 2, 0)

        # Intermediate mask for inspection
        mask  = green_mask(rgb)
        clean = clean_mask(mask)
        polys = extract_polygons(clean, rgb)

        # Compute adaptive dist for display
        dist = cv2.distanceTransform(clean, cv2.DIST_L2, 5)
        nz   = dist[dist > 0]
        adist = int(np.clip(np.median(nz) * 0.6, MIN_PEAK_DIST_PX, 50)) if len(nz) else MIN_PEAK_DIST_PX

        print(f"  Raw green mask coverage : {(mask > 0).mean()*100:.1f}%")
        print(f"  After morphology        : {(clean > 0).mean()*100:.1f}%")
        print(f"  Adaptive peak dist (px) : {adist}")
        print(f"  Canopy polygons found   : {len(polys)}")
        if polys:
            areas = [cv2.contourArea(np.array(p["points"], dtype=np.float32)) for p in polys]
            print(f"  Area (px²): min={min(areas):.0f}  max={max(areas):.0f}  mean={np.mean(areas):.0f}")

        # --- plot: RGB | green mask | detected polygons ---
        fig, axes = plt.subplots(1, 3, figsize=(24, 8))

        # stretch contrast for display
        p2, p98 = np.percentile(rgb, (2, 98))
        rgb_disp = np.clip((rgb.astype(float) - p2) / (p98 - p2 + 1e-6), 0, 1)

        axes[0].imshow(rgb_disp);            axes[0].set_title("RGB"); axes[0].axis("off")
        axes[1].imshow(clean, cmap="Greens");axes[1].set_title("Green mask (cleaned)"); axes[1].axis("off")

        axes[2].imshow(rgb_disp)
        for poly in polys:
            pts = np.array(poly["points"])
            patch = plt.Polygon(pts, closed=True,
                                facecolor=(0.1, 0.8, 0.1), alpha=0.45,
                                edgecolor=(0.0, 0.5, 0.0), linewidth=0.5)
            axes[2].add_patch(patch)
        axes[2].set_title(f"Detected canopies ({len(polys)})")
        axes[2].axis("off")

        plt.suptitle(tif.name, fontsize=11)
        plt.tight_layout()
        out = OUT_DIR / tif.name.replace(".tif", "_segmentation.png")
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Saved: {out}")
