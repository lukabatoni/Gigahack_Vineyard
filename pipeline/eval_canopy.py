"""
Canopy evaluation: compare predicted polygons vs reference annotations.
Metric mirrors the challenge scoring:
  - individual-canopy F1 at IoU >= 0.5 (one-to-one greedy match)
  - class IoU (union of all predicted vs union of all reference, pixelwise)
Reports precision, recall, F1, class IoU per tile.
"""
import numpy as np
import cv2
from pathlib import Path

from explore_tiles import parse_annotations

TILE = 2048


def poly_to_mask(points, h=TILE, w=TILE):
    m = np.zeros((h, w), np.uint8)
    pts = np.array(points, np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(m, [pts], 1)
    return m


def bbox(points):
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def boxes_overlap(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def iou(m1, m2):
    inter = np.logical_and(m1, m2).sum()
    if inter == 0:
        return 0.0
    union = np.logical_or(m1, m2).sum()
    return inter / union


def evaluate(preds, refs, iou_thr=0.5):
    """preds, refs: lists of polygon point-lists. Greedy one-to-one match."""
    pred_boxes = [bbox(p) for p in preds]
    ref_boxes = [bbox(r) for r in refs]
    pred_masks = [poly_to_mask(p) for p in preds]
    ref_masks = [poly_to_mask(r) for r in refs]

    matched_ref = set()
    tp = 0
    for pi, pm in enumerate(pred_masks):
        best, best_ri = iou_thr, -1
        for ri, rm in enumerate(ref_masks):
            if ri in matched_ref:
                continue
            if not boxes_overlap(pred_boxes[pi], ref_boxes[ri]):
                continue
            v = iou(pm, rm)
            if v >= best:
                best, best_ri = v, ri
        if best_ri >= 0:
            tp += 1
            matched_ref.add(best_ri)

    fp = len(preds) - tp
    fn = len(refs) - tp
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    # class IoU (union pixelwise)
    pred_union = np.zeros((TILE, TILE), np.uint8)
    for m in pred_masks:
        pred_union |= m
    ref_union = np.zeros((TILE, TILE), np.uint8)
    for m in ref_masks:
        ref_union |= m
    class_iou = iou(pred_union, ref_union)

    return dict(tp=tp, fp=fp, fn=fn, precision=prec, recall=rec, f1=f1,
                class_iou=class_iou, n_pred=len(preds), n_ref=len(refs))


def score_canopy(segment_fn, label=""):
    ex = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat")
    ann = parse_annotations(ex / "annotations.xml")
    print(f"\n=== Canopy eval: {label} ===")
    combined = 0
    for name, d in ann.items():
        refs = [o["points"] for o in d["objects"]["vineyard"]]
        preds = [p["points"] for p in segment_fn(ex / "images" / name)]
        r = evaluate(preds, refs)
        combined += r["f1"]
        print(f"{name}")
        print(f"  pred={r['n_pred']:4d}  ref={r['n_ref']:4d}  "
              f"TP={r['tp']:4d} FP={r['fp']:4d} FN={r['fn']:4d}")
        print(f"  precision={r['precision']:.3f}  recall={r['recall']:.3f}  "
              f"F1={r['f1']:.3f}  classIoU={r['class_iou']:.3f}")
    print(f"  --- mean canopy F1: {combined/len(ann):.3f} ---")


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "sam"
    if which == "sam":
        from segment_canopy_sam import segment_tile_sam
        score_canopy(segment_tile_sam, "SAM+ExG")
    elif which == "classic":
        from segment_canopy import segment_tile
        score_canopy(segment_tile, "Classic ExG+watershed")
