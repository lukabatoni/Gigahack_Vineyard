"""
Task 8: CVAT for Images 1.1 annotations.xml generator.

Takes per-tile geometry dicts (pixel coords) and writes a valid CVAT 1.1
annotations.xml with the exact mandatory label block for this challenge.

Input structure:
    objects_by_tile = {
        "siret3_r021_c012.tif": {
            "width": 2048, "height": 2048,
            "vineyard":      [ {points:[(x,y)..], vineyard_id} ],
            "waste":         [ {xtl,ytl,xbr,ybr, vineyard_id} ],
            "row":           [ {points:[(x,y)..], vineyard_id, row_id, row_structure} ],
            "interrow_area": [ {points:[(x,y)..], vineyard_id, interrow_cover} ],
        }, ...
    }

Coordinates are pixels (0,0 = top-left). Output validated against the mandatory
schema in CLAUDE.md.
"""
from pathlib import Path
from xml.sax.saxutils import escape

# The mandatory label block (verbatim from CLAUDE.md).
LABELS_XML = """    <labels>
      <label><name>vineyard</name><type>polygon</type><attributes>
        <attribute><name>vineyard_id</name><input_type>text</input_type><mutable>false</mutable><default_value></default_value><values></values></attribute></attributes></label>
      <label><name>waste</name><type>rectangle</type><attributes>
        <attribute><name>vineyard_id</name><input_type>text</input_type><mutable>false</mutable><default_value></default_value><values></values></attribute></attributes></label>
      <label><name>row</name><type>polyline</type><attributes>
        <attribute><name>vineyard_id</name><input_type>text</input_type><mutable>false</mutable><default_value></default_value><values></values></attribute>
        <attribute><name>row_id</name><input_type>text</input_type><mutable>false</mutable><default_value></default_value><values></values></attribute>
        <attribute><name>row_structure</name><input_type>select</input_type><mutable>false</mutable><default_value>regular</default_value><values>regular
disrupted
unassessable</values></attribute></attributes></label>
      <label><name>interrow_area</name><type>polygon</type><attributes>
        <attribute><name>vineyard_id</name><input_type>text</input_type><mutable>false</mutable><default_value></default_value><values></values></attribute>
        <attribute><name>interrow_cover</name><input_type>select</input_type><mutable>false</mutable><default_value>bare_soil</default_value><values>bare_soil
vegetation
mixed
unassessable</values></attribute></attributes></label>
    </labels>"""


def _points_str(points):
    return ";".join(f"{float(x):.2f},{float(y):.2f}" for x, y in points)


def _attr(name, value):
    return f'      <attribute name="{escape(name)}">{escape(str(value))}</attribute>'


def build_image_block(image_id, tile):
    name = tile["name"]
    w = tile.get("width", 2048)
    h = tile.get("height", 2048)
    lines = [f'  <image id="{image_id}" name="{escape(name)}" width="{w}" height="{h}">']

    for o in tile.get("vineyard", []):
        lines.append(f'    <polygon label="vineyard" occluded="0" source="auto" '
                     f'points="{_points_str(o["points"])}" z_order="0">')
        lines.append(_attr("vineyard_id", o.get("vineyard_id", "")))
        lines.append("    </polygon>")

    for o in tile.get("interrow_area", []):
        lines.append(f'    <polygon label="interrow_area" occluded="0" source="auto" '
                     f'points="{_points_str(o["points"])}" z_order="0">')
        lines.append(_attr("vineyard_id", o.get("vineyard_id", "")))
        lines.append(_attr("interrow_cover", o.get("interrow_cover", "bare_soil")))
        lines.append("    </polygon>")

    for o in tile.get("row", []):
        lines.append(f'    <polyline label="row" occluded="0" source="auto" '
                     f'points="{_points_str(o["points"])}" z_order="0">')
        lines.append(_attr("vineyard_id", o.get("vineyard_id", "")))
        lines.append(_attr("row_id", o.get("row_id", "")))
        lines.append(_attr("row_structure", o.get("row_structure", "regular")))
        lines.append("    </polyline>")

    for o in tile.get("waste", []):
        lines.append(f'    <box label="waste" occluded="0" source="auto" '
                     f'xtl="{float(o["xtl"]):.2f}" ytl="{float(o["ytl"]):.2f}" '
                     f'xbr="{float(o["xbr"]):.2f}" ybr="{float(o["ybr"]):.2f}" z_order="0">')
        lines.append(_attr("vineyard_id", o.get("vineyard_id", "")))
        lines.append("    </box>")

    lines.append("  </image>")
    return "\n".join(lines)


def write_cvat_xml(objects_by_tile, out_path):
    out_path = Path(out_path)
    parts = ['<?xml version="1.0" encoding="utf-8"?>', "<annotations>",
             '  <version>1.1</version>',
             "  <meta>", "    <task>", "      <name>siret3_vineyard</name>",
             LABELS_XML, "    </task>", "  </meta>"]
    for i, (name, objs) in enumerate(sorted(objects_by_tile.items())):
        tile = dict(objs)
        tile["name"] = name
        parts.append(build_image_block(i, tile))
    parts.append("</annotations>\n")
    out_path.write_text("\n".join(parts))
    print(f"Wrote {out_path} ({len(objects_by_tile)} images)")


if __name__ == "__main__":
    # Round-trip self-test: parse reference XML, re-emit, re-parse, compare counts.
    from explore_tiles import parse_annotations
    ex = Path("/Users/luka-sap/Desktop/Gigahack/05_examples/siret3_examples_cvat")
    ann = parse_annotations(ex / "annotations.xml")

    obt = {}
    for name, d in ann.items():
        o = d["objects"]
        obt[name] = {
            "width": d["width"], "height": d["height"],
            "vineyard": [{"points": v["points"],
                          "vineyard_id": v["attrs"].get("vineyard_id", "")}
                         for v in o["vineyard"]],
            "interrow_area": [{"points": v["points"],
                               "vineyard_id": v["attrs"].get("vineyard_id", ""),
                               "interrow_cover": v["attrs"].get("interrow_cover", "bare_soil")}
                              for v in o["interrow_area"]],
            "row": [{"points": v["points"],
                     "vineyard_id": v["attrs"].get("vineyard_id", ""),
                     "row_id": v["attrs"].get("row_id", ""),
                     "row_structure": v["attrs"].get("row_structure", "regular")}
                    for v in o["row"]],
            "waste": [{"xtl": v["xtl"], "ytl": v["ytl"], "xbr": v["xbr"], "ybr": v["ybr"],
                       "vineyard_id": v["attrs"].get("vineyard_id", "")}
                      for v in o["waste"]],
        }

    out = "/Users/luka-sap/Desktop/Gigahack/pipeline/output/annotations_roundtrip.xml"
    write_cvat_xml(obt, out)

    # re-parse to confirm validity
    reparsed = parse_annotations(Path(out))
    print("\nRound-trip check (orig -> emitted -> reparsed):")
    for name in ann:
        a = ann[name]["objects"]; b = reparsed[name]["objects"]
        print(f"  {name}: "
              f"vineyard {len(a['vineyard'])}->{len(b['vineyard'])}, "
              f"row {len(a['row'])}->{len(b['row'])}, "
              f"interrow {len(a['interrow_area'])}->{len(b['interrow_area'])}, "
              f"waste {len(a['waste'])}->{len(b['waste'])}")
