"""Подложка карт: Natural Earth 1:50m, обрезанная по Америкам и упрощённая.

    uv run --group basemap tools/basemap.py

Скачивает суши и озёра Natural Earth (общественное достояние) из зеркала
nvkelso/natural-earth-vector, оставляет обе Америки с Гренландией и Карибами,
упрощает контуры и пишет visuals/shared/americas-50m.geojson. Отдельным файлом,
visuals/shared/borders-50m.geojson, — сухопутные границы нынешних государств в той
же рамке (линии admin-0 boundary lines): у каждой — пара стран, которые она
разделяет. Запускается вручную при смене версии или параметров — в CI не нужен.
"""

import json
import urllib.request
from pathlib import Path

from shapely.geometry import MultiLineString, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "visuals" / "shared" / "americas-50m.geojson"
BORDERS_OUT = ROOT / "visuals" / "shared" / "borders-50m.geojson"

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
MAX_BORDER_GAP = 0.5  # градусы: страна дальше от середины линии — не её сторона; третья
# ближайшая страна должна быть заметно дальше второй, иначе пара неоднозначна


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


def lines(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        return [g for part in geom.geoms for g in lines(part)]
    return []


def borders() -> list[dict]:
    """Сухопутные границы государств в рамке Америк. В слое линий Natural Earth v5.1.2 нет
    атрибутов стран, поэтому пара стран (ISO A3) определяется по полигонам admin-0: две страны,
    ближайшие к середине линии (часть линий идёт по проливам, а не по суше)."""
    countries = [
        (f["properties"]["ADM0_A3"], shape(f["geometry"]))
        for f in fetch("admin_0_countries")["features"]
    ]
    countries = [(a3, g) for a3, g in countries if g.intersects(CLIP)]
    out = []
    for f in fetch("admin_0_boundary_lines_land")["features"]:
        parts = [g for g in lines(shape(f["geometry"]).intersection(CLIP)) if g.centroid.x <= -30]
        if not parts:
            continue  # Старый Свет
        longest = max(parts, key=lambda g: g.length)
        mid = longest.interpolate(0.5, normalized=True)
        near = sorted((g.distance(mid), a3) for a3, g in countries)[:3]
        if near[1][0] > MAX_BORDER_GAP or near[2][0] < 2 * near[1][0] + 0.05:
            raise SystemExit(f"граница у {mid.x:.2f}, {mid.y:.2f}: не понять, чья — {near}")
        pair = sorted(a3 for _, a3 in near[:2])
        simple = [p.simplify(TOLERANCE) for p in parts]
        geometry = rounded(simple[0] if len(simple) == 1 else MultiLineString(simple))
        out.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "border",
                    "between": pair,
                    "class": f["properties"]["FEATURECLA"],
                },
                "geometry": geometry,
            }
        )
    return out


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

    bl = {
        "type": "FeatureCollection",
        "metadata": {
            "source": f"Natural Earth 1:50m admin-0 boundary lines (land), admin-0 countries "
            f"({NE_VERSION})",
            "url": "https://www.naturalearthdata.com/",
            "license": "Общественное достояние",
            "generator": "tools/basemap.py",
            "simplify_tolerance_deg": TOLERANCE,
            "note": "Нынешние сухопутные границы государств; between — коды ISO A3 двух стран, "
            "которые разделяет линия. На исторических картах — только как ориентир.",
        },
        "features": borders(),
    }
    BORDERS_OUT.write_text(
        json.dumps(bl, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"{BORDERS_OUT.relative_to(ROOT)}: {BORDERS_OUT.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
