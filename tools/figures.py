"""Статические рисунки для глав: SVG в двух темах из одного описания.

    uv run tools/figures.py           # перерисовать chapters/img/*.svg
    uv run tools/figures.py --check   # код 1, если файлы устарели (для CI)

Цвета берутся из visuals/shared/tokens.css, чтобы рисунки глав и визуализации
сайта были в одной палитре. Каждый рисунок — функция, которая получает тему
(словарь токенов) и возвращает SVG; в главу он вставляется через <picture>,
чтобы на GitHub показывалась версия под тему читателя.
"""

import argparse
import json
import math
import re
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "visuals" / "shared" / "tokens.css"
BASEMAP = ROOT / "visuals" / "shared" / "americas-50m.geojson"
PEOPLING = ROOT / "data" / "peopling.json"
OUT = ROOT / "chapters" / "img"

SANS = "'Alegreya Sans','Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
SERIF = "Alegreya,Georgia,'Times New Roman',serif"


def themes() -> dict[str, dict[str, str]]:
    """Токены светлой и тёмной темы из tokens.css."""
    css = TOKENS.read_text(encoding="utf-8")
    blocks = re.findall(r"(:root[^{]*)\{([^}]*)\}", css)

    def parse(body: str) -> dict[str, str]:
        return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", body))

    light = parse(blocks[0][1])
    dark = {**light, **parse(next(b for sel, b in blocks if 'data-theme="dark"' in sel))}
    return {"light": light, "dark": dark}


# ── Примитивы SVG


def svg(w: int, h: int, t: dict, body: list[str], title: str, desc: str) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
            f'height="{h}" role="img" aria-labelledby="t d" font-family="{SANS}">',
            f"<title id='t'>{escape(title)}</title><desc id='d'>{escape(desc)}</desc>",
            f'<rect width="{w}" height="{h}" fill="{t["bg"]}"/>',
            *body,
            "</svg>",
        ]
    )


def text(
    x, y, s, fill, size=13, anchor="start", weight=400, family=SANS, italic=False, halo=None
) -> str:
    style = ' font-style="italic"' if italic else ""
    if halo:  # подложка цвета фона, чтобы подпись читалась поверх линий
        style += f' paint-order="stroke" stroke="{halo}" stroke-width="4" stroke-linejoin="round"'
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'text-anchor="{anchor}" font-weight="{weight}" font-family="{family}"{style}>'
        f"{escape(s)}</text>"
    )


def line(x1, y1, x2, y2, stroke, width=1.0, dash=None, opacity=1.0) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
        f'stroke-width="{width}" stroke-opacity="{opacity}"{d}/>'
    )


def polyline(pts, stroke, width=2.0) -> str:
    p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (
        f'<polyline points="{p}" fill="none" stroke="{stroke}" '
        f'stroke-width="{width}" stroke-linejoin="round"/>'
    )


def polygon(pts, fill, opacity=1.0) -> str:
    p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return f'<polygon points="{p}" fill="{fill}" fill-opacity="{opacity}"/>'


def rect(x, y, w, h, fill, rx=3, opacity=1.0, extra="") -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
        f'fill="{fill}" fill-opacity="{opacity}"{extra}/>'
    )


# ── Рис. 0.1. Калибровка радиоуглеродной даты (схема)


def catmull_rom(knots: list[tuple[float, float]], steps: int = 40) -> list[tuple[float, float]]:
    pts = [knots[0], *knots, knots[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for k in range(steps):
            u = k / steps
            out.append(
                tuple(
                    0.5
                    * (
                        2 * p1[j]
                        + (-p0[j] + p2[j]) * u
                        + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * u**2
                        + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * u**3
                    )
                    for j in (0, 1)
                )
            )
    out.append(knots[-1])
    return out


# Условная кривая: календарное время (0 — раньше, 1 — позже) → радиоуглеродный возраст
# (1 — старше). Крутой участок слева, «плато» в середине. Это не IntCal20.
CURVE_KNOTS = [
    (0.00, 0.97),
    (0.08, 0.93),
    (0.13, 0.86),  # крутой участок — под образцом А
    (0.19, 0.75),
    (0.26, 0.69),
    (0.33, 0.645),
    (0.40, 0.58),
    (0.46, 0.52),
    (0.52, 0.59),
    (0.58, 0.515),
    (0.64, 0.59),
    (0.70, 0.52),
    (0.76, 0.46),
    (0.87, 0.31),
    (1.00, 0.18),
]
CURVE_HALF = 0.014  # полуширина полосы кривой
MEASURED = [  # (радиоуглеродный возраст, погрешность, подпись, токен цвета)
    (0.80, 0.018, "образец А", "z-t"),
    (0.555, 0.012, "образец Б", "z-n"),
]


def intervals(curve, y0: float, s: float) -> list[tuple[float, float]]:
    """Отрезки календарного времени, где полоса кривой пересекает измерение y0 ± s."""
    segs: list[tuple[float, float]] = []
    start = prev = None
    for x, y in curve:
        hit = (y - CURVE_HALF) <= y0 + s and (y + CURVE_HALF) >= y0 - s
        if hit and start is None:
            start = x
        if not hit and start is not None:
            segs.append((start, prev))
            start = None
        prev = x
    if start is not None:
        segs.append((start, prev))
    return [(a, b) for a, b in segs if b - a > 0.004]


def fig_radiocarbon(t: dict) -> str:
    w, h = 760, 450
    left, right, top, bottom = 92, 24, 26, 104
    pw, ph = w - left - right, h - top - bottom
    curve = catmull_rom(CURVE_KNOTS)

    def px(x):
        return left + x * pw

    def py(y):
        return top + (1 - y) * ph

    b = []
    # оси
    b.append(line(left, top, left, top + ph, t["muted"], 1))
    b.append(line(left, top + ph, left + pw, top + ph, t["muted"], 1))
    b.append(text(left - 12, top + 6, "старше", t["muted"], 12, "end"))
    b.append(text(left - 12, top + ph, "моложе", t["muted"], 12, "end"))
    b.append(
        f'<text transform="translate({left - 62},{top + ph / 2}) rotate(-90)" fill="{t["ink"]}" '
        f'font-size="13" text-anchor="middle">радиоуглеродный возраст</text>'
    )
    b.append(text(left, top + ph + 20, "раньше", t["muted"], 12))
    b.append(text(left + pw, top + ph + 20, "позже", t["muted"], 12, "end"))
    b.append(text(left + pw / 2, top + ph + 20, "календарное время", t["ink"], 13, "middle"))

    # полоса кривой
    upper = [(px(x), py(y + CURVE_HALF)) for x, y in curve]
    lower = [(px(x), py(y - CURVE_HALF)) for x, y in reversed(curve)]
    b.append(polygon(upper + lower, t["muted"], 0.28))
    b.append(polyline([(px(x), py(y)) for x, y in curve], t["muted"], 1.4))

    # измерения и их проекции
    label_y = top + ph + 44
    for i, (y0, s, name, tok) in enumerate(MEASURED):
        c = t[tok]
        segs = intervals(curve, y0, s)
        x_end = px(max(bx for _, bx in segs))
        b.append(rect(left, py(y0 + s), x_end - left, py(y0 - s) - py(y0 + s), c, 0, 0.22))
        b.append(line(left, py(y0), x_end, py(y0), c, 1.6))
        b.append(
            text(
                left + 6,
                py(y0 - s) + 15,  # под полосой: слева от пересечения кривая проходит выше
                name,
                t["ink"],
                12,
                halo=t["bg"],
            )
        )
        for a, bx in segs:
            for xx in (a, bx):
                b.append(line(px(xx), py(y0), px(xx), top + ph, c, 1, "3 3", 0.9))
            yb = top + ph - 7 - i * 9
            b.append(rect(px(a), yb, max(px(bx) - px(a), 3), 6, c, 3))
        n = len(segs)
        span = sum(bx - a for a, bx in segs)
        verdict = (
            "узкий интервал — участок кривой крутой"
            if n == 1 and span < 0.12
            else f"{n} {'интервал' if n == 1 else 'интервала' if n < 5 else 'интервалов'} "
            "календарного времени — плато кривой"
        )
        b.append(rect(left, label_y - 9 + i * 20, 10, 6, c, 3))
        b.append(text(left + 16, label_y - 3 + i * 20, f"{name}: {verdict}", t["ink"], 12.5))

    b.append(
        text(
            left + 16,
            label_y + 37,
            "Цветная полоса — измеренный радиоуглеродный возраст ± погрешность измерения.",
            t["muted"],
            12,
        )
    )
    b.append(
        text(
            left + pw,
            top + 12,
            "Схема: кривая условная, не настоящая калибровочная",
            t["muted"],
            12,
            "end",
            italic=True,
        )
    )
    return svg(
        w,
        h,
        t,
        b,
        "Калибровка радиоуглеродной даты (схема)",
        "Условная калибровочная кривая. Образец А попадает на крутой участок и получает узкий "
        "календарный интервал. Образец Б попадает на плато и получает несколько возможных "
        "интервалов — та же погрешность измерения даёт гораздо худшую календарную точность.",
    )


# ── Рис. 0.2. Типичная точность датировки для разных видов свидетельств (оценка)

SCALE = ["день", "год", "десятилетие", "век", "тысячелетие"]
PRECISION = [  # (канал, от, до, пояснение, ненадёжно)
    ("Колониальные документы", 0.0, 1.0, "после 1492 г.", False),
    (
        "Надписи майя",
        0.0,
        0.35,
        "в основном I тыс. н. э.; перевод в наш календарь — по корреляции",
        False,
    ),
    (
        "Дендрохронология",
        0.9,
        1.25,
        "если сохранилось последнее кольцо; юго-запад США и др.",
        False,
    ),
    ("Радиоуглерод", 2.0, 3.3, "зависит от участка кривой — рис. 0.1", False),
    ("Генетика", 3.6, 4.7, "когда разошлись группы — расчёт, а не наблюдение", False),
    ("Глоттохронология", 3.7, 4.9, "метод не считается надёжным", True),
    ("Устная традиция", None, None, "порядок событий, а не абсолютная дата", False),
]


def fig_precision(t: dict) -> str:
    w = 760
    label_w, top, row = 196, 50, 50
    h = top + row * len(PRECISION) + 40
    x0, x1 = 214, 570  # шкала точности
    rel_x = 684  # колонка «только порядок»
    step = (x1 - x0) / (len(SCALE) - 1)

    def px(v):
        return x0 + v * step

    b = [
        "<defs>",
        f'<pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><rect width="6" height="6" fill="{t["bg"]}"/>'
        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{t["ink"]}" stroke-width="2.2" '
        f'stroke-opacity=".55"/></pattern>',
        "</defs>",
    ]
    for i, s in enumerate(SCALE):
        b.append(line(px(i), top - 8, px(i), h - 34, t["rule"], 1))
        b.append(text(px(i), top - 16, s, t["muted"], 12, "middle"))
    b.append(line(rel_x, top - 8, rel_x, h - 34, t["rule"], 1, "2 3"))
    b.append(text(rel_x, top - 16, "только порядок", t["muted"], 12, "middle"))
    b.append(text(px(0) - 8, top - 32, "точнее", t["muted"], 11.5, "middle", italic=True))
    b.append(text(px(len(SCALE) - 1), top - 32, "грубее", t["muted"], 11.5, "middle", italic=True))

    for i, (name, a, z, note, unreliable) in enumerate(PRECISION):
        y = top + 14 + i * row
        b.append(text(label_w - 14, y + 4, name, t["ink"], 13.5, "end", 500))
        if a is None:
            b.append(f'<circle cx="{rel_x}" cy="{y}" r="6" fill="{t["ink"]}" fill-opacity=".8"/>')
            b.append(text(rel_x - 12, y + 22, note, t["muted"], 11.5, "end"))
            continue
        xa, xz = px(a), px(z)
        fill = "url(#hatch)" if unreliable else t["ink"]
        b.append(rect(xa, y - 4, max(xz - xa, 8), 8, fill, 4, 1 if unreliable else 0.8))
        if unreliable:
            b.append(
                f'<rect x="{xa:.1f}" y="{y - 4:.1f}" width="{xz - xa:.1f}" height="8" rx="4" '
                f'fill="none" stroke="{t["ink"]}" stroke-opacity=".55"/>'
            )
        # пояснение — от начала полосы, а у полос справа — к её концу, чтобы не вылезать за край
        if xa > w / 2:
            b.append(text(xz, y + 22, note, t["muted"], 11.5, "end"))
        else:
            b.append(text(xa, y + 22, note, t["muted"], 11.5))

    b.append(
        text(
            w - 8,
            h - 10,
            "Оценка конспекта: примерная точность, а не точные значения",
            t["muted"],
            12,
            "end",
            italic=True,
        )
    )
    return svg(
        w,
        h,
        t,
        b,
        "Типичная точность датировки для разных видов свидетельств (оценка)",
        "Колониальные документы и надписи майя дают даты до дня, дендрохронология — до года, "
        "радиоуглерод — от десятилетий до веков, генетика — тысячелетия, глоттохронология "
        "ненадёжна, устная традиция даёт порядок событий, а не абсолютные даты.",
    )


# ── Глава 1. Общее: данные, числа по-русски, проекция


def peopling() -> dict:
    return json.loads(PEOPLING.read_text(encoding="utf-8"))


def num(v: float, digits: int | None = None) -> str:
    """Число с десятичной запятой: 13.8 → «13,8»."""
    s = f"{v:.{digits}f}" if digits is not None else f"{v:g}"
    return s.replace(".", ",").replace("-", "−")


def ka_span(t: dict, digits: int | None = None) -> str:
    """Подпись интервала из data/peopling.json: «23–21», «≈17», «13,8 ± 0,5», «≈700 лет»."""
    a, b, err = t["from"], t["to"], t.get("error")
    if err:
        return f"{num(a, digits)} ± {num(err)}"
    if b is None:
        return f"≈ {num(round(a * 1000))} лет" if a < 1 else f"≈ {num(a, digits)}"
    return f"{num(a, digits)}–{num(b, digits)}"


def contested_mark(rec: dict) -> str:
    """Пометка спорной датировки: «спорно» или «спорно (2026)» — с года, когда её оспорили."""
    if not rec.get("contested"):
        return ""
    since = rec.get("contested_since")
    return f"спорно ({since})" if since else "спорно"


def ka_digits(t: dict) -> int | None:
    """Две цифры после запятой, если они есть в данных (14,22–13,98), иначе как в данных."""
    vals = [v for v in (t["from"], t["to"]) if v is not None]
    return 2 if any(round(v * 100) % 10 for v in vals) else None


def split_label(s: str, limit: int) -> list[str]:
    """Длинную подпись — на две строки по пробелу ближе к середине."""
    if len(s) <= limit or " " not in s:
        return [s]
    cut = min((i for i, ch in enumerate(s) if ch == " "), key=lambda i: abs(i - len(s) / 2))
    return [s[:cut], s[cut + 1 :]]


def laea(lon0: float, lat0: float) -> Callable[[float, float], tuple[float, float]]:
    """Азимутальная равновеликая проекция Ламберта (то же, что d3.geoAzimuthalEqualArea
    с rotate([-lon0, -lat0])). Возвращает x вправо и y вниз в радиусах Земли."""
    l0, p0 = math.radians(lon0), math.radians(lat0)
    sp0, cp0 = math.sin(p0), math.cos(p0)

    def f(lon: float, lat: float) -> tuple[float, float]:
        dl, p = math.radians(lon) - l0, math.radians(lat)
        cosc = sp0 * math.sin(p) + cp0 * math.cos(p) * math.cos(dl)
        k = math.sqrt(2 / (1 + cosc)) if cosc > -1 + 1e-9 else 0.0
        x = k * math.cos(p) * math.sin(dl)
        y = k * (cp0 * math.sin(p) - sp0 * math.cos(p) * math.cos(dl))
        return x, -y

    return f


def geo_circle(lon: float, lat: float, radius_km: float, step: int = 6) -> list[tuple]:
    """Кольцо точек на расстоянии radius_km от центра (по сфере)."""
    d = radius_km / 6371.0
    p1, l1 = math.radians(lat), math.radians(lon)
    out = []
    for b in range(0, 360, step):
        br = math.radians(b)
        p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(br))
        l2 = l1 + math.atan2(
            math.sin(br) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2)
        )
        out.append((math.degrees(l2), math.degrees(p2)))
    return out


def path_d(pts, close=False) -> str:
    d = "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return d + ("Z" if close else "")


def smooth(pts, steps: int = 12) -> list[tuple[float, float]]:
    return catmull_rom(pts, steps) if len(pts) > 2 else list(pts)


# ── Рис. 1.1. Два пути на юг и стоянки (схема)

MAP_W, MAP_H = 760, 820
MAP_CENTER = (-100, 22)  # центр проекции: между Аляской и югом Чили
MAP_FIT = [
    (-179, 62),
    (-162, 77),
    (-73, -44.8),
    (-34, -7),
]  # углы рамки: пролив, Аляска, юг Чили, Бразилия

# Ледниковые щиты — схема, а не реконструкция: пятна (lon, lat, радиус, км), которые затем
# размываются. Внутренняя Аляска оставлена свободной ото льда; вдоль точек коридора из
# data/peopling.json и вдоль прибрежного пути лёд вырезан маской. Пятна сливаются в одну
# заливку, а прозрачность (ICE_OPACITY) накладывается на неё целиком — поэтому лёд везде
# одного тона, и образец в легенде совпадает с картой. Кордильерский щит узок: его пятна
# размываются слабее (ICE_BLUR_NARROW), иначе размытие съедает его почти целиком.
ICE_OPACITY = 0.42
ICE_BLUR, ICE_BLUR_NARROW = 7, 4
ICE_CORDILLERAN = [
    (-146, 62, 190),
    (-138, 60.8, 280),
    (-130, 57.8, 310),
    (-126, 54.3, 330),
    (-122, 50.8, 290),
    (-120.5, 48.3, 190),
]
ICE_LAURENTIDE = [
    (-85, 61, 1250),
    (-104, 61, 760),
    (-112, 66, 480),
    (-100, 53, 650),
    (-89, 49, 700),
    (-76, 49, 560),
    (-68, 66, 700),
    (-82, 77, 520),
]
ICE_GREENLAND = [(-42, 73, 850), (-47, 66, 380)]

# Линии путей — схема по описанию в тексте главы (lon, lat).
COAST_ROUTE = [
    (-168.5, 62.6),
    (-167.5, 57.5),
    (-164.8, 54.0),
    (-157, 55.0),
    (-149.5, 57.6),
    (-141, 59.2),
    (-137.6, 57.3),
    (-134.6, 54.2),
    (-131, 50.3),
    (-127.6, 45),
    (-126, 39),
    (-121.5, 33.2),
]
# из внутренней Аляски к BCN; начало отодвинуто от Апвард-Сан-Ривер: стоянка поздняя
# (≈ 11,5 тыс. лет), и стрелка, выходящая из неё, читалась бы как «отсюда пошли»
CORRIDOR_ENTRY = [(-132.0, 61.9), (-128.6, 60.6)]
CORRIDOR_EXIT = [(-109.3, 47.7)]  # за южным концом коридора; восточнее Купер-Ферри, чтобы
# стрелка не указывала на стоянку, которая старше открытия коридора
BERING_EDGE, BERING_FROM = -171.5, 59  # меридиан и широта, от которых карта обрезана
SITE_NOTES = {  # пояснения к стоянкам, которые иначе читаются неверно
    "usr": ["потомки оставшихся в Берингии,", "не начало пути"],
}


def fig_routes(t: dict) -> str:
    data = peopling()
    base = json.loads(BASEMAP.read_text(encoding="utf-8"))
    land = next(f for f in base["features"] if f["properties"]["kind"] == "land")
    lakes = next(f for f in base["features"] if f["properties"]["kind"] == "lake")
    proj = laea(*MAP_CENTER)

    fit = [proj(lon, lat) for lon, lat in MAP_FIT]
    xs, ys = [p[0] for p in fit], [p[1] for p in fit]
    k = min(MAP_W / (max(xs) - min(xs)), MAP_H / (max(ys) - min(ys)))
    ox = -min(xs) * k + (MAP_W - (max(xs) - min(xs)) * k) / 2
    oy = -min(ys) * k + (MAP_H - (max(ys) - min(ys)) * k) / 2

    def pr(lon: float, lat: float) -> tuple[float, float]:
        x, y = proj(lon, lat)
        return ox + x * k, oy + y * k

    def inside(pt, m=40):
        return -m <= pt[0] <= MAP_W + m and -m <= pt[1] <= MAP_H + m

    def multipolygon_d(geom) -> str:
        parts = []
        for poly in geom["coordinates"]:
            rings = [[pr(lon, lat) for lon, lat in ring] for ring in poly]
            if not any(inside(p) for p in rings[0]):
                continue  # полигон целиком за краем карты
            parts += [path_d(r, close=True) for r in rings]
        return "".join(parts)

    corridor = [(c["lon"], c["lat"]) for c in data["corridor"]]
    corridor_line = smooth([pr(*p) for p in CORRIDOR_ENTRY + corridor + CORRIDOR_EXIT])
    coast_line = smooth([pr(*p) for p in COAST_ROUTE])
    route = t["z-t"]

    def blobs(spec) -> str:
        return "".join(
            f'<path d="{path_d([pr(*q) for q in geo_circle(lon, lat, r)], True)}"/>'
            for lon, lat, r in spec
        )

    b = [
        "<defs>",
        f'<clipPath id="frame"><rect width="{MAP_W}" height="{MAP_H}"/></clipPath>',
        f'<pattern id="offmap" width="7" height="7" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><rect width="7" height="7" fill="{t["bg"]}"/>'
        f'<line x1="0" y1="0" x2="0" y2="7" stroke="{t["rule"]}" stroke-width="1.4"/></pattern>',
        f'<path id="land" d="{multipolygon_d(land["geometry"])}"/>',
        '<filter id="soft" x="-20%" y="-20%" width="140%" height="140%">'
        f'<feGaussianBlur stdDeviation="{ICE_BLUR}"/></filter>',
        '<filter id="soft-narrow" x="-20%" y="-20%" width="140%" height="140%">'
        f'<feGaussianBlur stdDeviation="{ICE_BLUR_NARROW}"/></filter>',
        '<filter id="soft-key" x="-30%" y="-60%" width="160%" height="220%">'
        '<feGaussianBlur stdDeviation="1.6"/></filter>',
        '<filter id="softer" x="-20%" y="-20%" width="140%" height="140%">'
        '<feGaussianBlur stdDeviation="3"/></filter>',
        # маска: всё видно, кроме полосы коридора между щитами
        f'<mask id="gap" maskUnits="userSpaceOnUse" x="0" y="0" width="{MAP_W}" '
        f'height="{MAP_H}"><rect width="{MAP_W}" height="{MAP_H}" fill="#fff"/>'
        f'<g fill="none" stroke="#000" stroke-linecap="round" filter="url(#softer)">'
        f'<path d="{path_d(smooth([pr(*p) for p in corridor]))}" stroke-width="16"/>'
        f'<path d="{path_d(coast_line)}" stroke-width="12"/></g></mask>',
        f'<marker id="head" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5.5" '
        f'markerHeight="5.5" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" '
        f'fill="{route}"/></marker>',
        "</defs>",
        '<g clip-path="url(#frame)">',
        f'<use href="#land" fill="{t["panel"]}"/>',
        # лёд: размытые пятна; лёд лежал и на шельфе, поэтому по суше не обрезается
        f'<g mask="url(#gap)" opacity="{ICE_OPACITY}" fill="{t["muted"]}">'
        f'<g filter="url(#soft)">{blobs(ICE_LAURENTIDE + ICE_GREENLAND)}</g>'
        f'<g filter="url(#soft-narrow)">{blobs(ICE_CORDILLERAN)}</g></g>',
        f'<path d="{multipolygon_d(lakes["geometry"])}" fill="{t["bg"]}" stroke="{t["muted"]}" '
        f'stroke-width=".4" stroke-opacity=".5"/>',
        f'<use href="#land" fill="none" stroke="{t["muted"]}" stroke-width=".6" '
        f'stroke-opacity=".6"/>',
        "</g>",
    ]

    # пути
    b.append(
        f'<path d="{path_d(coast_line)}" fill="none" stroke="{route}" stroke-width="2.6" '
        f'stroke-dasharray="7 5" stroke-linecap="round" marker-end="url(#head)"/>'
    )
    b.append(
        f'<path d="{path_d(corridor_line)}" fill="none" stroke="{route}" stroke-width="2.6" '
        f'stroke-linecap="round" marker-end="url(#head)"/>'
    )
    for lon, lat in corridor:
        x, y = pr(lon, lat)
        b.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{t["panel"]}" stroke="{t["ink"]}" '
            f'stroke-width="1.1"/>'
        )

    ev = {e["id"]: e for e in data["events"]}
    coast_t, corr_t = ev["coast_open"]["time"], ev["corridor_open"]["time"]

    def label(x, y, lines, anchor="start", size=13, first_weight=600, gap=15):
        out = []
        for i, s in enumerate(lines):
            out.append(
                text(
                    x,
                    y + i * gap,
                    s,
                    t["ink"] if i == 0 else t["muted"],
                    size if i == 0 else size - 1.5,
                    anchor,
                    first_weight if i == 0 else 400,
                    halo=t["bg"],
                )
            )
        return out

    # подписи путей
    # слева от берега — пустой океан: подписи привязаны к краю рамки
    _, y = pr(-131, 47)
    b += label(12, y, ["прибрежный путь", "открыт после", f"{ka_span(coast_t)} тыс. л. н."])
    x, y = pr(-104, 53.8)
    b += label(x, y, ["безлёдный коридор", f"открыт целиком {ka_span(corr_t)} тыс. л. н."])

    # ледники и места
    def place(lon, lat, s, size=12.5, anchor="middle", italic=True, color=None, family=SERIF):
        x, y = pr(lon, lat)
        return text(
            x, y, s, color or t["muted"], size, anchor, 400, family, italic=italic, halo=t["bg"]
        )

    b.append(place(-88, 62, "Лаврентийский щит", 14))
    # Кордильерский щит узок — подпись в океане с выноской
    xi, yi = pr(-130.5, 56.8)
    b.append(line(96, yi - 14, xi, yi, t["muted"], 0.8))
    b.append(
        text(
            12, yi - 16, "Кордильерский", t["muted"], 12.5, family=SERIF, italic=True, halo=t["bg"]
        )
    )
    b.append(text(12, yi - 2, "щит", t["muted"], 12.5, family=SERIF, italic=True, halo=t["bg"]))
    # подложка обрезана по 180°: Чукотки на ней нет. Западнее пролива карта честно
    # кончается — штриховка «не показано» вместо пустого моря.
    edge = [pr(BERING_EDGE, lat) for lat in range(BERING_FROM, 86)]
    b.append(polygon([*edge, (-20, -20), (-20, edge[0][1])], "url(#offmap)"))
    b.append(polyline(edge, t["rule"], 1.2))
    b.append(line(-20, edge[0][1], edge[0][0], edge[0][1], t["rule"], 1.2))
    for i, (s1, c, size) in enumerate(
        [
            ("Берингия", t["ink"], 15),
            ("азиатская часть", t["muted"], 11),
            ("не показана", t["muted"], 11),
        ]
    ):
        b.append(
            text(
                8,
                22 + i * 14 + (2 if i else 0),
                s1,
                c,
                size,
                family=SERIF,
                italic=True,
                halo=t["bg"],
            )
        )
    b.append(place(-128, 25, "Тихий океан", 14))
    b.append(place(-48, 30, "Атлантический океан", 14))

    # стоянки
    offsets = {
        "usr": (9, -32, "start"),  # подпись в четыре строки — выше, над началом стрелки
        "white_sands": (10, 4, "start"),
        "monte_verde": (10, -4, "start"),
        "coopers_ferry": (-6, 21, "start"),  # справа конец стрелки коридора — подпись ниже
    }
    for s in data["sites"]:
        x, y = pr(s["lon"], s["lat"])
        b.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{t["ink"]}" stroke="{t["bg"]}" '
            f'stroke-width="2"/>'
        )
        dx, dy, anchor = offsets[s["id"]]
        when = f"{ka_span(s['time'], ka_digits(s['time']))} тыс. л. н."
        if s.get("contested"):
            when += f" — {contested_mark(s)}"
        lines = [s["name"], when, *SITE_NOTES.get(s["id"], [])]
        b += label(x + dx, y + dy, lines, anchor, 13.5)

    # легенда — в пустом углу Тихого океана
    lx, ly = 22, MAP_H - 170
    rows = [
        ("site", "стоянка, о которой идёт речь в главе"),
        ("coast", "прибрежный путь — гипотеза"),
        ("corridor", "безлёдный коридор"),
        ("probe", "места датировки коридора"),
        ("ice", "ледниковые щиты"),
    ]
    for i, (kind, s) in enumerate(rows):
        yy = ly + i * 22
        if kind == "site":
            b.append(f'<circle cx="{lx + 14}" cy="{yy}" r="5" fill="{t["ink"]}"/>')
        elif kind in ("coast", "corridor"):
            dash = ' stroke-dasharray="7 5"' if kind == "coast" else ""
            b.append(
                f'<path d="M{lx},{yy}L{lx + 26},{yy}" stroke="{route}" stroke-width="2.6"{dash} '
                f'marker-end="url(#head)"/>'
            )
        elif kind == "probe":
            b.append(
                f'<circle cx="{lx + 14}" cy="{yy}" r="2.6" fill="{t["panel"]}" '
                f'stroke="{t["ink"]}" stroke-width="1.1"/>'
            )
        else:
            # образец льда — так же, как на карте: на суше, тем же тоном и размытием
            b.append(rect(lx, yy - 9, 28, 18, t["panel"], 4))
            b.append(
                rect(lx + 4, yy - 5, 20, 10, t["muted"], 4, ICE_OPACITY, ' filter="url(#soft-key)"')
            )
        b.append(text(lx + 40, yy + 4, s, t["ink"], 12.5))
    b.append(
        text(lx, ly + len(rows) * 22 + 6, "Даты — тысячи календарных лет назад.", t["muted"], 12)
    )
    b.append(
        text(
            lx,
            ly + len(rows) * 22 + 24,
            "Схема: границы ледников и линии путей условные",
            t["muted"],
            12,
            italic=True,
        )
    )
    b.append(
        f'<rect x=".5" y=".5" width="{MAP_W - 1}" height="{MAP_H - 1}" fill="none" '
        f'stroke="{t["rule"]}"/>'
    )
    names = ", ".join(
        s["name"] + (f" — {contested_mark(s)}" if s.get("contested") else "") for s in data["sites"]
    )
    return svg(
        MAP_W,
        MAP_H,
        t,
        b,
        "Два возможных пути на юг и стоянки главы 1 (схема)",
        f"Карта Северной и Южной Америки. Стоянки: {names}. Пунктирная стрелка — прибрежный "
        f"путь вдоль Тихого океана, открытый после {ka_span(coast_t)} тыс. лет назад; сплошная — "
        f"безлёдный коридор вдоль Скалистых гор, открытый целиком {ka_span(corr_t)} тыс. лет "
        "назад. Ледниковые щиты показаны условно.",
    )


# ── Рис. 1.2. Последовательность событий заселения (данные и оценки)

TL_FROM, TL_TO = 25, 10  # тыс. лет назад, слева направо


def fig_timeline(t: dict) -> str:
    data = peopling()
    events = data["events"]
    w = 760
    x0, x1 = 236, 744
    top, row = 76, 40
    rows_h = row * len(events)
    h = top + rows_h + 96

    def px(ka: float) -> float:
        return x0 + (TL_FROM - ka) / (TL_FROM - TL_TO) * (x1 - x0)

    color = {"archaeology": t["ink"], "geology": t["z-t"], "genetics": t["muted"]}
    b = [
        "<defs>",
        f'<pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><rect width="6" height="6" fill="{t["bg"]}"/>'
        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{t["ink"]}" stroke-width="2.2" '
        f'stroke-opacity=".6"/></pattern>',
        # для коротких спорных интервалов (Монте-Верде — 0,24 тыс. лет): штрих чаще
        f'<pattern id="hatch-fine" width="3.5" height="3.5" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><rect width="3.5" height="3.5" fill="{t["bg"]}"/>'
        f'<line x1="0" y1="0" x2="0" y2="3.5" stroke="{t["ink"]}" stroke-width="1.5" '
        f'stroke-opacity=".75"/></pattern>',
        f'<linearGradient id="fadein" x1="0" x2="1"><stop offset="0" stop-color="{t["z-t"]}" '
        f'stop-opacity="0"/><stop offset="1" stop-color="{t["z-t"]}" stop-opacity=".85"/>'
        "</linearGradient>",
        "</defs>",
    ]

    # шкала
    b.append(text((x0 + x1) / 2, top - 50, "тысяч лет назад", t["muted"], 12, "middle"))
    b.append(text(x0, top - 50, "← раньше", t["muted"], 11.5, italic=True))
    b.append(text(x1, top - 50, "позже →", t["muted"], 11.5, "end", italic=True))
    for ka in range(TL_FROM, TL_TO - 1, -1):
        x = px(ka)
        major = ka % 5 == 0
        b.append(line(x, top - 18, x, top + rows_h - 6, t["rule"], 1.2 if major else 0.7))
        b.append(
            text(
                x,
                top - 24,
                str(ka),
                t["ink"] if major else t["muted"],
                12 if major else 11,
                "middle",
                600 if major else 400,
            )
        )

    for i, e in enumerate(events):
        tm, kind = e["time"], e["kind"]
        y = top + i * row + row / 2 - 4
        c = color[kind]
        names = split_label(e["label"], 30)
        for j, s1 in enumerate(names):
            yy = y + 4.5 + (j - (len(names) - 1) / 2) * 15
            b.append(text(x0 - 14, yy, s1, t["ink"], 13, "end", 500))
        a = px(tm["from"])
        bar_h = 10
        value = ka_span(tm, ka_digits(tm))
        if e.get("contested"):
            value += f" — {contested_mark(e)}"
        if kind == "genetics":
            value += " — расчёт"
        if tm.get("point"):
            b.append(
                f'<rect x="{a - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" fill="{c}" '
                f'transform="rotate(45 {a:.1f} {y:.1f})"/>'
            )
            b.append(text(a + 11, y + 4.5, value, t["ink"], 12.5))
        elif tm["to"] is None:  # открыто с этого времени
            err = tm.get("error")
            if err:
                b.append(rect(a, y - bar_h / 2, x1 - a, bar_h, t["z-t"], 4, 0.45))
                ea, ez = px(tm["from"] + err), px(tm["from"] - err)
                b.append(line(ea, y, ez, y, t["ink"], 1.6))
                for xx in (ea, ez):
                    b.append(line(xx, y - 7, xx, y + 7, t["ink"], 1.6))
                b.append(
                    f'<circle cx="{a:.1f}" cy="{y:.1f}" r="4" fill="{c}" stroke="{t["bg"]}" '
                    'stroke-width="1.5"/>'
                )
                b.append(text(ea - 8, y + 4.5, value, t["ink"], 12.5, "end"))
            else:
                fade = 22
                b.append(rect(a - fade, y - bar_h / 2, fade, bar_h, "url(#fadein)", 0))
                b.append(rect(a, y - bar_h / 2, x1 - a, bar_h, c, 4, 0.85, extra=""))
                b.append(text(a - fade - 6, y + 4.5, f"после {value}", t["ink"], 12.5, "end"))
        else:
            z = px(tm["to"])
            wbar = max(z - a, 6)
            if e.get("contested"):
                # короткий интервал чуть расширен вокруг середины, иначе штриховку не видно
                fine = wbar < 20
                if fine:
                    a, wbar = (a + z) / 2 - max(wbar, 12) / 2, max(wbar, 12)
                pat = "url(#hatch-fine)" if fine else "url(#hatch)"
                b.append(rect(a, y - bar_h / 2, wbar, bar_h, pat, 3 if fine else 4))
                b.append(
                    f'<rect x="{a:.1f}" y="{y - bar_h / 2:.1f}" width="{wbar:.1f}" '
                    f'height="{bar_h}" rx="{3 if fine else 4}" fill="none" stroke="{t["ink"]}" '
                    'stroke-opacity=".7"/>'
                )
            elif kind == "genetics":
                b.append(
                    f'<rect x="{a:.1f}" y="{y - bar_h / 2:.1f}" width="{wbar:.1f}" '
                    f'height="{bar_h}" rx="4" fill="{t["muted"]}" fill-opacity=".12" '
                    f'stroke="{t["muted"]}" stroke-width="1.5" stroke-dasharray="4 3"/>'
                )
            else:
                b.append(rect(a, y - bar_h / 2, wbar, bar_h, c, 4, 0.85))
            if a + wbar + 8 + len(value) * 6.6 > w - 8:  # не влезает справа — подпись слева
                b.append(text(a - 8, y + 4.5, value, t["ink"], 12.5, "end"))
            else:
                b.append(text(a + wbar + 8, y + 4.5, value, t["ink"], 12.5))

    # легенда
    ly = top + rows_h + 22
    legend = [
        ("arch", "стоянки и культуры"),
        ("geo", "пути и ландшафт: ледники, коридор, суша"),
        ("gen", "генетический расчёт, а не наблюдение"),
        ("hatch", "датировка спорна"),
    ]
    for i, (kind, s) in enumerate(legend):
        lx = 24 + (i % 2) * 360
        yy = ly + (i // 2) * 22
        if kind == "arch":
            b.append(rect(lx, yy - 5, 26, 10, t["ink"], 4, 0.85))
        elif kind == "geo":
            b.append(rect(lx, yy - 5, 26, 10, t["z-t"], 4, 0.85))
        elif kind == "gen":
            b.append(
                f'<rect x="{lx}" y="{yy - 5}" width="26" height="10" rx="4" '
                f'fill="{t["muted"]}" fill-opacity=".12" stroke="{t["muted"]}" '
                'stroke-width="1.5" stroke-dasharray="4 3"/>'
            )
        else:
            b.append(rect(lx, yy - 5, 26, 10, "url(#hatch)", 4))
        b.append(text(lx + 36, yy + 4.5, s, t["ink"], 12.5))
    b.append(
        text(
            w - 16,
            h - 14,
            "Даты — из публикаций, на которые ссылается глава; ромб — точечная оценка «около»",
            t["muted"],
            12,
            "end",
            italic=True,
        )
    )
    desc = "; ".join(
        f"{e['label']}: {ka_span(e['time'])} тыс. лет назад"
        + (f" — {contested_mark(e)}" if e.get("contested") else "")
        for e in events
    )
    return svg(w, h, t, b, "Последовательность событий заселения Америки", desc + ".")


# ── Рис. 1.3. Приходы и смешения по данным палеогенетики (схема)

# Раскладка — только положение узлов (центр, ширина), содержание — из data/peopling.json.
# По вертикали — порядок событий, а не масштаб времени.
ANCESTRY_W, ANCESTRY_H = 760, 640
ANCESTRY_LAYOUT = {
    "founders": (290, 50, 180),
    "pop_y": (88, 128, 130),
    "other_americans": (220, 128, 0),  # точка развилки, без подписи
    "southern": (100, 222, 130),
    "northern": (340, 222, 130),
    "ancient_beringians": (500, 222, 160),
    "siberian": (668, 222, 160),
    "paleo_eskimos": (668, 338, 170),
    "nadene_ancestors": (270, 430, 170),
    "eskaleut_ancestors": (480, 430, 170),
    "thule": (480, 520, 220),
    "yupik": (410, 604, 100),
    "inuit": (550, 604, 100),
}


def fig_ancestry(t: dict) -> str:
    lin = peopling()["lineages"]
    nodes = {n["id"]: n for n in lin["nodes"]}
    links = lin["links"]
    w, h = ANCESTRY_W, ANCESTRY_H
    stroke = {"first": t["z-n"], "siberian": t["z-t"], "mixed": t["ink"], "hypothesis": t["muted"]}

    def lines_of(n) -> list[str]:
        return textwrap.wrap(n["label"], 22)

    def sub(n) -> str | None:
        tm = n.get("time")
        if not tm:
            return None
        if n["id"] == "paleo_eskimos":
            return f"≈ {num(tm['from'])} тыс. → ≈ {num(round(tm['to'] * 1000))} лет назад"
        s = ka_span(tm, 1 if tm["to"] and tm["from"] < 10 else None)
        return f"{s} лет назад" if "лет" in s else f"{s} тыс. лет назад"

    box = {}  # id → (x, верх, низ)
    body: list[str] = []
    for nid, (x, y, bw) in ANCESTRY_LAYOUT.items():
        n = nodes[nid]
        if bw == 0:
            box[nid] = (x, y, y)
            continue
        ls, s = lines_of(n), sub(n)
        bh = 12 + 16 * len(ls) + (15 if s else 0)
        y0 = y - bh / 2
        box[nid] = (x, y0, y0 + bh)
        dash = ' stroke-dasharray="5 4"' if n["ancestry"] == "hypothesis" else ""
        body.append(
            f'<rect x="{x - bw / 2:.1f}" y="{y0:.1f}" width="{bw}" height="{bh}" rx="6" '
            f'fill="{t["panel"]}" stroke="{stroke[n["ancestry"]]}" stroke-width="1.8"{dash}/>'
        )
        for i, s1 in enumerate(ls):
            body.append(text(x, y0 + 21 + 16 * i, s1, t["ink"], 13.5, "middle", 600))
        if s:
            body.append(text(x, y0 + 21 + 16 * len(ls), s, t["muted"], 12, "middle"))

    edges: list[str] = []
    notes: list[str] = []

    # несколько линий из одного узла или в один узел — разводим концы по горизонтали
    def spread(ends: dict[str, list[str]], key: str, other: str) -> dict[tuple, float]:
        out = {}
        for nid, peers in ends.items():
            peers = sorted(peers, key=lambda q: ANCESTRY_LAYOUT[q][0])
            for i, q in enumerate(peers):
                pair = (nid, q) if key == "from" else (q, nid)
                out[pair] = (i - (len(peers) - 1) / 2) * 22
        return out

    outs: dict[str, list[str]] = {}
    ins: dict[str, list[str]] = {}
    for link in links:
        outs.setdefault(link["from"], []).append(link["to"])
        ins.setdefault(link["to"], []).append(link["from"])
    dx_out, dx_in = spread(outs, "from", "to"), spread(ins, "to", "from")

    for link in links:
        a, z = link["from"], link["to"]
        xa, _, ya = box[a]
        xz, yz, _ = box[z]
        if ANCESTRY_LAYOUT[a][2]:
            xa += dx_out[(a, z)]
        if ANCESTRY_LAYOUT[z][2]:
            xz += dx_in[(a, z)]
        kind = link["kind"]
        src = nodes[a]["ancestry"]
        c = stroke[src] if kind != "hypothesis" else t["muted"]
        if src == "mixed":
            c = t["ink"]
        dash = ' stroke-dasharray="6 5"' if kind == "hypothesis" else ""
        width = 2.4
        my = (ya + yz) / 2
        head = f' marker-end="url(#ah-{src})"' if ANCESTRY_LAYOUT[z][2] else ""
        end = yz - 4 if head else yz
        edges.append(
            f'<path d="M{xa:.1f},{ya:.1f}C{xa:.1f},{my:.1f} {xz:.1f},{my:.1f} {xz:.1f},{end:.1f}" '
            f'fill="none" stroke="{c}" stroke-width="{width}"{dash}{head}/>'
        )
        if kind == "hypothesis":
            notes.append(text((xa + xz) / 2 + 12, my + 4, "?", t["muted"], 18, "middle", 700))
        share = link.get("share")
        if share:
            # подпись доли — у острия своей стрелки, с внешней стороны пары входящих линий
            side = 1 if dx_in[(a, z)] > 0 else -1
            notes.append(
                text(
                    xz + side * 9,
                    yz - 12,
                    f"{num(share['low'])}–{num(share['high'])}%",
                    t["ink"],
                    13,
                    "start" if side > 0 else "end",
                    700,
                    halo=t["bg"],
                )
            )
    fork = box["other_americans"]
    body.append(f'<circle cx="{fork[0]}" cy="{fork[1]}" r="4.5" fill="{t["z-n"]}"/>')
    split = next(lk for lk in links if lk["to"] == "northern")["time"]
    for i, s in enumerate(["разошлись", f"{ka_span(split)} тыс. л. н.", "— расчёт"]):
        notes.append(text(fork[0], fork[1] + 40 + 14 * i, s, t["muted"], 12, "middle"))

    # конец линии палеоэскимосов
    pe = box["paleo_eskimos"]
    notes.append(line(pe[0], pe[2], pe[0], pe[2] + 22, t["z-t"], 2.4))
    notes.append(line(pe[0] - 9, pe[2] + 22, pe[0] + 9, pe[2] + 22, t["z-t"], 2.4))
    notes.append(text(pe[0] + 14, pe[2] + 26, "исчезли", t["muted"], 12))
    ab = box["ancient_beringians"]
    notes.append(line(ab[0], ab[2], ab[0], ab[2] + 22, t["z-n"], 2.4))
    notes.append(line(ab[0] - 9, ab[2] + 22, ab[0] + 9, ab[2] + 22, t["z-n"], 2.4))
    notes.append(text(ab[0] - 14, ab[2] + 20, "вытеснены", t["muted"], 12, "end"))
    notes.append(text(ab[0] - 14, ab[2] + 34, "или вобраны", t["muted"], 12, "end"))

    defs = ["<defs>"]
    for k2, c in stroke.items():
        defs.append(
            f'<marker id="ah-{k2}" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" '
            f'markerHeight="5" orient="auto"><path d="M0,0L10,5L0,10z" fill="{c}"/></marker>'
        )
    defs.append("</defs>")

    legend = []
    lx, ly = 24, h - 64
    for i, (k2, s) in enumerate(
        [
            ("first", "наследственность первых американцев"),
            ("siberian", "сибирская, родственная палеоэскимосской"),
            ("hypothesis", "гипотеза"),
        ]
    ):
        yy = ly + i * 20
        dash = ' stroke-dasharray="6 5"' if k2 == "hypothesis" else ""
        legend.append(
            f'<path d="M{lx},{yy}L{lx + 28},{yy}" stroke="{stroke[k2]}" stroke-width="2.4"{dash}/>'
        )
        legend.append(text(lx + 38, yy + 4.5, s, t["ink"], 12.5))
    legend.append(
        f'<rect x="{lx}" y="{ly - 31}" width="28" height="14" rx="4" fill="{t["panel"]}" '
        f'stroke="{t["ink"]}" stroke-width="1.8"/>'
    )
    legend.append(text(lx + 38, ly - 19.5, "группа, сложившаяся из смешения", t["ink"], 12.5))
    legend.append(text(lx, ly - 46, "Проценты — доля наследственности в смешении", t["muted"], 12))
    legend.append(
        text(
            w - 16,
            22,
            "Схема: время не в масштабе; доли — оценки авторов",
            t["muted"],
            12,
            "end",
            italic=True,
        )
    )
    legend.append(text(16, 22, "раньше ↑", t["muted"], 11.5, italic=True))
    legend.append(text(16, 470, "позже ↓", t["muted"], 11.5, italic=True))

    return svg(
        w,
        h,
        t,
        [*defs, *edges, *body, *notes, *legend],
        "Приходы и смешения по данным палеогенетики (схема)",
        "От группы основателей отходят древние берингийцы и предки остальных коренных "
        "американцев, разошедшиеся на северную и южную ветви. Из Сибири отдельно приходят "
        "палеоэскимосы. Линия, родственная палеоэскимосам, смешивается с северной ветвью — "
        "так складываются предки на-дене и предки эскимосско-алеутских народов; от последних "
        "с туле линия расходится к юпикам и инуитам. «Популяция Y» — гипотеза.",
    )


FIGURES: dict[str, Callable[[dict], str]] = {
    "00-radiocarbon": fig_radiocarbon,
    "00-precision": fig_precision,
    "01-routes": fig_routes,
    "01-timeline": fig_timeline,
    "01-ancestry": fig_ancestry,
}


def render_all() -> dict[Path, str]:
    out = {}
    for theme_name, t in themes().items():
        for name, fn in FIGURES.items():
            out[OUT / f"{name}-{theme_name}.svg"] = fn(t) + "\n"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--check", action="store_true", help="только проверить актуальность")
    args = ap.parse_args()
    files = render_all()
    if args.check:
        stale = [
            p for p, s in files.items() if not p.exists() or p.read_text(encoding="utf-8") != s
        ]
        for p in stale:
            print(f"устарел: {p.relative_to(ROOT)} — запустите uv run tools/figures.py")
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p, s in files.items():
        p.write_text(s, encoding="utf-8")
    print(f"{len(files)} файлов в {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
