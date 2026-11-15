"""Write webapp/assets/world.js: Natural Earth 110m land (public domain) as one SVG path in
equirectangular coordinates, 2 units a degree (a 720 x 360 box), for the species maps.
Usage: python ops/make_world.py ne_110m_land.geojson"""
import json
import sys
from pathlib import Path

d = json.load(open(sys.argv[1]))
out = []
for f in d["features"]:
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for poly in polys:
        for ring in poly:
            pts = [(round((x + 180) * 2), round((90 - y) * 2)) for x, y in ring]
            keep = [pts[0]] + [p for i, p in enumerate(pts[1:], 1) if p != pts[i - 1]]
            if len(keep) < 4:
                continue
            s = "M" + " ".join(f"{x} {y}" for x, y in keep[:1])
            px, py = keep[0]
            for x, y in keep[1:]:
                s += f"l{x - px} {y - py}"
                px, py = x, y
            out.append(s + "z")
path = "".join(out)
Path(__file__).resolve().parent.parent.joinpath("webapp/assets/world.js").write_text(
    "// Natural Earth 110m land, public domain (naturalearthdata.com); made by ops/make_world.py\n"
    f'guaminsects.world("{path}");\n')
print(len(path))
