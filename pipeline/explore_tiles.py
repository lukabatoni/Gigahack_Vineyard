"""
Task 2: Explore example tiles and reference annotations.
Loads both example GeoTIFFs, parses annotations.xml, prints statistics,
and saves a visualisation of each tile with all objects drawn on top.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import rasterio
from rasterio.plot import show

EXAMPLES_DIR = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat")
ANNOTATIONS_XML = EXAMPLES_DIR / "annotations.xml"
IMAGES_DIR = EXAMPLES_DIR / "images"
OUT_DIR = Path("/Users/luka-sap/Desktop/Gigahack/pipeline/output")
OUT_DIR.mkdir(exist_ok=True)


# ── XML parsing ──────────────────────────────────────────────────────────────

def parse_points(s: str) -> list[tuple[float, float]]:
    """'x1,y1;x2,y2;...' → [(x1,y1), ...]"""
    return [tuple(map(float, p.split(","))) for p in s.split(";")]


def parse_annotations(xml_path: Path) -> dict:
    """Returns {filename: {label: [objects]}} where each object is a dict."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    images = {}
    for img in root.findall("image"):
        name = img.attrib["name"]
        w, h = int(img.attrib["width"]), int(img.attrib["height"])
        objects = {"vineyard": [], "row": [], "interrow_area": [], "waste": []}

        for elem in img:
            label = elem.attrib.get("label")
            if label not in objects:
                continue
            attrs = {a.attrib["name"]: a.text for a in elem.findall("attribute")}

            if label in ("vineyard", "interrow_area"):
                pts = parse_points(elem.attrib["points"])
                objects[label].append({"points": pts, "attrs": attrs})

            elif label == "row":
                pts = parse_points(elem.attrib["points"])
                objects[label].append({"points": pts, "attrs": attrs})

            elif label == "waste":
                obj = {
                    "xtl": float(elem.attrib["xtl"]),
                    "ytl": float(elem.attrib["ytl"]),
                    "xbr": float(elem.attrib["xbr"]),
                    "ybr": float(elem.attrib["ybr"]),
                    "attrs": attrs,
                }
                objects[label].append(obj)

        images[name] = {"width": w, "height": h, "objects": objects}
    return images


# ── Tile inspection ──────────────────────────────────────────────────────────

def inspect_tile(tif_path: Path):
    with rasterio.open(tif_path) as src:
        print(f"\n{'='*60}")
        print(f"Tile: {tif_path.name}")
        print(f"  CRS:          {src.crs}")
        print(f"  Size:         {src.width} × {src.height} px")
        print(f"  Bands:        {src.count}  (dtype: {src.dtypes[0]})")
        print(f"  Pixel size:   {src.res[0]*100:.2f} cm/px")
        print(f"  Ground size:  {src.width*src.res[0]:.1f} m × {src.height*src.res[1]:.1f} m")
        print(f"  BBox (m):     left={src.bounds.left:.1f}  right={src.bounds.right:.1f}")
        print(f"                bottom={src.bounds.bottom:.1f}  top={src.bounds.top:.1f}")
        print(f"  Transform:    {src.transform}")

        # Basic image stats per band
        data = src.read()
        for b in range(src.count):
            band = data[b]
            print(f"  Band {b+1}: min={band.min()}  max={band.max()}  mean={band.mean():.1f}  std={band.std():.1f}")
        return data


# ── Visualisation ────────────────────────────────────────────────────────────

COLORS = {
    "vineyard":      (0.18, 0.80, 0.18, 0.5),   # green fill
    "row":           (0.20, 0.60, 1.00, 1.0),   # blue line
    "interrow_area": (1.00, 0.55, 0.00, 0.25),  # orange fill
    "waste":         (1.00, 0.10, 0.10, 0.8),   # red box
}


def draw_annotations(ax, objects, title_suffix=""):
    for obj in objects["interrow_area"]:
        pts = np.array(obj["points"])
        poly = plt.Polygon(pts, closed=True,
                           facecolor=COLORS["interrow_area"][:3],
                           edgecolor=(1.0, 0.4, 0.0), linewidth=0.6,
                           alpha=COLORS["interrow_area"][3])
        ax.add_patch(poly)

    for obj in objects["vineyard"]:
        pts = np.array(obj["points"])
        poly = plt.Polygon(pts, closed=True,
                           facecolor=COLORS["vineyard"][:3],
                           edgecolor=(0.0, 0.6, 0.0), linewidth=0.4,
                           alpha=COLORS["vineyard"][3])
        ax.add_patch(poly)

    for obj in objects["row"]:
        pts = np.array(obj["points"])
        ax.plot(pts[:, 0], pts[:, 1], color=COLORS["row"][:3],
                linewidth=1.2, alpha=COLORS["row"][3])

    for obj in objects["waste"]:
        x, y = obj["xtl"], obj["ytl"]
        w = obj["xbr"] - obj["xtl"]
        h = obj["ybr"] - obj["ytl"]
        rect = mpatches.Rectangle((x, y), w, h,
                                   linewidth=1.5, edgecolor="red",
                                   facecolor=(1,0,0,0.2))
        ax.add_patch(rect)


def visualise_tile(tif_path: Path, objects: dict, out_path: Path):
    with rasterio.open(tif_path) as src:
        img = src.read([1, 2, 3]).transpose(1, 2, 0)

    # Stretch contrast for display
    p2, p98 = np.percentile(img, (2, 98))
    img_disp = np.clip((img.astype(float) - p2) / (p98 - p2), 0, 1)

    fig, axes = plt.subplots(1, 2, figsize=(20, 10))

    for ax, title, draw in [
        (axes[0], "RGB only", False),
        (axes[1], "RGB + annotations", True),
    ]:
        ax.imshow(img_disp)
        ax.set_title(f"{tif_path.name}\n{title}", fontsize=10)
        ax.axis("off")
        if draw:
            draw_annotations(ax, objects)

    legend_handles = [
        mpatches.Patch(color=COLORS["vineyard"][:3], alpha=0.7, label="vineyard (polygon)"),
        mpatches.Patch(color=COLORS["interrow_area"][:3], alpha=0.5, label="interrow_area (polygon)"),
        mpatches.Patch(color=COLORS["row"][:3], alpha=1.0, label="row (polyline)"),
        mpatches.Patch(color="red", alpha=0.5, label="waste (bbox)"),
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=4, fontsize=9)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {out_path}")


# ── Stats ────────────────────────────────────────────────────────────────────

def print_annotation_stats(name: str, objects: dict):
    print(f"\nAnnotation stats — {name}")
    for label, items in objects.items():
        print(f"  {label:15s}: {len(items):4d} objects")

    if objects["row"]:
        vineyard_ids = set(o["attrs"].get("vineyard_id","") for o in objects["row"])
        row_ids      = set(o["attrs"].get("row_id","")      for o in objects["row"])
        structures   = [o["attrs"].get("row_structure","")  for o in objects["row"]]
        print(f"  vineyard blocks : {sorted(vineyard_ids)}")
        print(f"  row_ids         : {len(row_ids)} unique ({sorted(row_ids)[:5]}...)")
        print(f"  row_structure   : {dict(zip(*np.unique(structures, return_counts=True)))}")

    if objects["interrow_area"]:
        covers = [o["attrs"].get("interrow_cover","") for o in objects["interrow_area"]]
        print(f"  interrow_cover  : {dict(zip(*np.unique(covers, return_counts=True)))}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Parsing annotations.xml ...")
    annotations = parse_annotations(ANNOTATIONS_XML)
    print(f"  Found {len(annotations)} annotated images: {list(annotations.keys())}")

    for fname, data in annotations.items():
        tif_path = IMAGES_DIR / fname
        if not tif_path.exists():
            print(f"  WARNING: {tif_path} not found, skipping.")
            continue

        inspect_tile(tif_path)
        print_annotation_stats(fname, data["objects"])

        out_png = OUT_DIR / (fname.replace(".tif", "_annotated.png"))
        print(f"  Rendering visualisation ...")
        visualise_tile(tif_path, data["objects"], out_png)

    print("\nDone. Output in:", OUT_DIR)


if __name__ == "__main__":
    main()
