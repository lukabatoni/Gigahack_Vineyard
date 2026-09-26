"""
Task 3b: Canopy segmentation via SAM (Segment Anything) + ExG prompting.

Hybrid approach (classic CV guides the neural net):
  1. ExG green-mask (from segment_canopy.green_mask) finds vegetation blobs.
  2. Each blob centroid becomes a POINT PROMPT for SAM.
  3. MobileSAM segments the individual vine canopy at each prompt.
  4. Area filter + dedup (drop near-duplicate masks).

Pretrained NN, NO training. Weights: mobile_sam.pt (downloaded by ultralytics).
This satisfies the mandatory neural-network deliverable for canopy segmentation.

Output per tile: list of dicts
    { "points": [(x,y), ...], "label": "vineyard", "vineyard_id": "" }
"""
import cv2
import numpy as np
import rasterio
from pathlib import Path
from typing import Union

from ultralytics import SAM

from segment_canopy import green_mask, clean_mask, MIN_AREA_PX, MAX_AREA_PX

_SAM_MODEL = None


def get_sam():
    global _SAM_MODEL
    if _SAM_MODEL is None:
        _SAM_MODEL = SAM("mobile_sam.pt")
    return _SAM_MODEL


def blob_prompts(mask: np.ndarray, max_prompts: int = 300) -> np.ndarray:
    """Connected components of the green mask → centroid point prompts.
    Returns Nx2 array of (x, y) pixel coords."""
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    pts = []
    for i in range(1, n):  # skip background
        area = stats[i, cv2.CC_STAT_AREA]
        if area < MIN_AREA_PX * 0.5:      # ignore tiny specks
            continue
        cx, cy = centroids[i]
        pts.append((float(cx), float(cy)))
    if len(pts) > max_prompts:
        # keep the largest blobs if too many prompts
        areas = [stats[i, cv2.CC_STAT_AREA] for i in range(1, n)
                 if stats[i, cv2.CC_STAT_AREA] >= MIN_AREA_PX * 0.5]
        order = np.argsort(areas)[::-1][:max_prompts]
        pts = [pts[i] for i in order]
    return np.array(pts, dtype=np.float32) if pts else np.zeros((0, 2), np.float32)


def mask_to_polygon(binary: np.ndarray) -> list:
    """Largest external contour → simplified polygon points, or None."""
    contours, _ = cv2.findContours(binary.astype(np.uint8),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(cnt)
    if area < MIN_AREA_PX or area > MAX_AREA_PX:
        return None
    eps = 0.004 * cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, eps, True)
    if len(approx) < 3:
        return None
    return [(float(p[0][0]), float(p[0][1])) for p in approx]


def segment_tile_sam(tif_path: Union[str, Path]) -> list:
    """Full SAM+ExG canopy pipeline for one tile."""
    with rasterio.open(tif_path) as src:
        rgb = src.read([1, 2, 3]).transpose(1, 2, 0)  # HxWx3 uint8

    mask = clean_mask(green_mask(rgb))
    prompts = blob_prompts(mask)
    if len(prompts) == 0:
        return []

    sam = get_sam()
    # SAM expects a list of [x,y] points; label 1 = foreground for each point.
    # Prompt one point at a time so each yields its own instance mask.
    polygons = []
    seen_centroids = []
    results = sam(rgb, points=prompts.tolist(),
                  labels=[1] * len(prompts), verbose=False)

    for res in results:
        if res.masks is None:
            continue
        for m in res.masks.data.cpu().numpy():
            binary = (m > 0.5).astype(np.uint8)
            # keep only the part overlapping vegetation (SAM can bleed onto soil)
            binary = binary & (mask > 0).astype(np.uint8)
            poly = mask_to_polygon(binary * 255)
            if poly is None:
                continue
            # dedup by centroid proximity
            cx = np.mean([p[0] for p in poly])
            cy = np.mean([p[1] for p in poly])
            if any((cx - sx) ** 2 + (cy - sy) ** 2 < 15 ** 2 for sx, sy in seen_centroids):
                continue
            seen_centroids.append((cx, cy))
            polygons.append({"points": poly, "label": "vineyard", "vineyard_id": ""})

    return polygons


if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    EXAMPLES = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat/images")
    OUT_DIR = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/output")
    OUT_DIR.mkdir(exist_ok=True)

    for tif in sorted(EXAMPLES.glob("*.tif")):
        print(f"\nSAM segmenting {tif.name} ...")
        polys = segment_tile_sam(tif)
        print(f"  Canopy polygons found: {len(polys)}")

        with rasterio.open(tif) as src:
            rgb = src.read([1, 2, 3]).transpose(1, 2, 0)
        p2, p98 = np.percentile(rgb, (2, 98))
        rgb_disp = np.clip((rgb.astype(float) - p2) / (p98 - p2 + 1e-6), 0, 1)

        fig, axes = plt.subplots(1, 2, figsize=(20, 10))
        axes[0].imshow(rgb_disp); axes[0].set_title("RGB"); axes[0].axis("off")
        axes[1].imshow(rgb_disp)
        for poly in polys:
            pts = np.array(poly["points"])
            axes[1].add_patch(plt.Polygon(pts, closed=True,
                              facecolor=(0.1, 0.8, 0.1), alpha=0.45,
                              edgecolor=(0, 0.5, 0), linewidth=0.5))
        axes[1].set_title(f"SAM+ExG canopies ({len(polys)})"); axes[1].axis("off")
        plt.suptitle(tif.name)
        plt.tight_layout()
        out = OUT_DIR / tif.name.replace(".tif", "_sam.png")
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Saved: {out}")
