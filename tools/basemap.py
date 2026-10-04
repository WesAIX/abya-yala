"""Подложка карт: Natural Earth 1:50m, обрезанная по Америкам и упрощённая.

    uv run --group basemap tools/basemap.py

Скачивает суши и озёра Natural Earth (общественное достояние) из зеркала
nvkelso/natural-earth-vector, оставляет обе Америки с Гренландией и Карибами,
упрощает контуры и пишет visuals/shared/americas-50m.geojson. Запускается
вручную при смене версии или параметров — в CI не нужен.
"""

import json
import urllib.request
from pathlib import Path

from shapely.geometry import box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "visuals" / "shared" / "americas-50m.geojson"

NE_VERSION = "v5.1.2"
NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{NE_VERSION}/geojson/ne_50m_{{layer}}.geojson"
)

CLIP = box(-180, -60, -10, 84)  # от Алеутских островов до восточного берега Гренландии
TOLERANCE = 0.04  # градусы, ≈ 4 км: достаточно для обзорных карт
MIN_AREA = 0.05  # кв. градусы: отбрасываем мелкие острова…
CARIBBEAN = box(-86, 10, -59, 24)  # …кроме Антильских
MIN_AREA_CARIBBEAN = 0.002
MIN_LAKE_AREA = 0.5  # Великие озёра, Виннипег, Большое Медвежье, Титикака, Никарагуа…
PRECISION = 2  # знаков после запятой, ≈ 1 км


def fetch(layer: str) -> dict:
    with urllib.request.urlopen(NE_URL.format(layer=layer), timeout=60) as r:
        return json.load(r)


def outside_americas(poly) -> bool:
    """Части Старого Света, попавшие в прямоугольник обрезки."""
    c = poly.centroid
    # Исландия, Азоры, Канары, Кабо-Верде, берег Африки; центр Гренландии — около −41°
    if c.x > -30:
        return True
    # Гавайи — Полинезия, а не Америка
    if c.x < -150 and c.y < 30:
        return True
    # Южная Георгия и Южные Сандвичевы острова
    return c.y < -50 and c.x > -45


def polygons(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for g in geom.geoms for p in polygons(g)]
    return []


def rounded(geom) -> dict:
    def r(coords):
        if isinstance(coords[0], (float, int)):
            return [round(coords[0], PRECISION), round(coords[1], PRECISION)]
        return [r(c) for c in coords]

    g = mapping(geom)
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def land() -> list:
    src = unary_union([shape(f["geometry"]) for f in fetch("land")["features"]])
    keep = []
    for p in polygons(src.intersection(CLIP)):
        if outside_americas(p):
            continue
        limit = MIN_AREA_CARIBBEAN if CARIBBEAN.contains(p.centroid) else MIN_AREA
        if p.area < limit:
            continue
        s = p.simplify(TOLERANCE, preserve_topology=True)
        keep.extend(polygons(s))
    return keep


def lakes() -> list:
    keep = []
    for f in fetch("lakes")["features"]:
        # водохранилища — XX век, на исторической подложке им не место
        if f["properties"].get("featurecla") != "Lake":
            continue
        g = shape(f["geometry"]).intersection(CLIP)
        for p in polygons(g):
            if p.area >= MIN_LAKE_AREA:
                keep.extend(polygons(p.simplify(TOLERANCE, preserve_topology=True)))
    return keep


def feature(kind: str, polys: list) -> dict:
    # d3-geo ждёт внешние кольца по часовой стрелке — обратно RFC 7946
    multi = unary_union([orient(p, sign=-1.0) for p in polys])
    oriented = [orient(p, sign=-1.0) for p in polygons(multi)]
    geom = oriented[0] if len(oriented) == 1 else type(multi)(oriented)
    return {"type": "Feature", "properties": {"kind": kind}, "geometry": rounded(geom)}


def main() -> None:
    fc = {
        "type": "FeatureCollection",
        "metadata": {
            "source": f"Natural Earth 1:50m land, lakes ({NE_VERSION})",
            "url": "https://www.naturalearthdata.com/",
            "license": "Общественное достояние",
            "generator": "tools/basemap.py",
            "simplify_tolerance_deg": TOLERANCE,
        },
        "features": [feature("land", land()), feature("lake", lakes())],
    }
    OUT.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
