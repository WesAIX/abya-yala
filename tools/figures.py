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
AGRICULTURE = ROOT / "data" / "agriculture.json"
COMPLEX = ROOT / "data" / "complex.json"
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


def map_projection(center, fit_pts, w: int, h: int) -> Callable[[float, float], tuple]:
    """LAEA с центром center, вписанная в рамку w×h так, чтобы точки fit_pts попали в неё."""
    proj = laea(*center)
    fit = [proj(lon, lat) for lon, lat in fit_pts]
    xs, ys = [p[0] for p in fit], [p[1] for p in fit]
    k = min(w / (max(xs) - min(xs)), h / (max(ys) - min(ys)))
    ox = -min(xs) * k + (w - (max(xs) - min(xs)) * k) / 2
    oy = -min(ys) * k + (h - (max(ys) - min(ys)) * k) / 2

    def pr(lon: float, lat: float) -> tuple[float, float]:
        x, y = proj(lon, lat)
        return ox + x * k, oy + y * k

    return pr


def basemap_paths(pr, w: int, h: int) -> tuple[str, str]:
    """Пути суши и озёр подложки в координатах рисунка; полигоны за краем рамки отброшены."""
    base = json.loads(BASEMAP.read_text(encoding="utf-8"))

    def inside(pt, m=40):
        return -m <= pt[0] <= w + m and -m <= pt[1] <= h + m

    def multipolygon_d(geom) -> str:
        parts = []
        for poly in geom["coordinates"]:
            rings = [[pr(lon, lat) for lon, lat in ring] for ring in poly]
            if not any(inside(p) for p in rings[0]):
                continue  # полигон целиком за краем карты
            parts += [path_d(r, close=True) for r in rings]
        return "".join(parts)

    land, lakes = (
        next(f for f in base["features"] if f["properties"]["kind"] == kind)
        for kind in ("land", "lake")
    )
    return multipolygon_d(land["geometry"]), multipolygon_d(lakes["geometry"])


def fig_routes(t: dict) -> str:
    data = peopling()
    pr = map_projection(MAP_CENTER, MAP_FIT, MAP_W, MAP_H)
    land_d, lakes_d = basemap_paths(pr, MAP_W, MAP_H)

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
        f'<path id="land" d="{land_d}"/>',
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
        f'<path d="{lakes_d}" fill="{t["bg"]}" stroke="{t["muted"]}" '
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


# ── Глава 2. Общее: данные, годы, знаки

# Местные растения и пришедшие из другого очага — пара из tokens.css (--z-m, --z-s),
# проверена validate_palette.js навыка dataviz для обеих тем: зелёный и янтарный
# (--z-m/--z-n) при дейтеранопии не различаются, эта пара — различается.
ORIGIN = {"local": "z-m", "introduced": "z-s"}


def agriculture() -> dict:
    return json.loads(AGRICULTURE.read_text(encoding="utf-8"))


def grouped(n: int) -> str:
    """Тысячи — через неразрывный пробел, как в тексте: 8700, но 13 100."""
    return f"{n:,}".replace(",", " ") if n >= 10000 else str(n)


def cal_year(y: int) -> str:
    """Календарный год словами: «2100 г. до н. э.», «900 г.», «рубеж эр»."""
    if y == 0:
        return "рубеж эр"
    return f"{grouped(-y)} г. до н. э." if y < 0 else f"{grouped(y)} г."


def bp(y: int) -> int:
    """Календарный год → «лет назад» (от 1950 г., как в источниках). Годы в данных
    пересчитаны из «лет назад» и кратны 50; расчётные (9188 → 9200) — до сотни."""
    v = 1950 - y
    return v if v % 50 == 0 else math.floor(v / 100 + 0.5) * 100


def bp_span(tm: dict) -> str:
    """«≈7500», «7000–6500», «≈9200» (центральная оценка) — без слов «лет назад»."""
    if tm.get("central") is not None:
        return f"≈{grouped(bp(tm['central']))}"
    if tm["to"] is None:
        return f"≈{grouped(bp(tm['from']))}"
    return f"{grouped(bp(tm['from']))}–{grouped(bp(tm['to']))}"


def hatch_defs(t: dict, color: str, pid: str = "hatch") -> str:
    return (
        f'<pattern id="{pid}" width="4" height="4" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><rect width="4" height="4" fill="{t["bg"]}"/>'
        f'<line x1="0" y1="0" x2="0" y2="4" stroke="{color}" stroke-width="2"/></pattern>'
    )


def mark(shape: str, x: float, y: float, fill: str, stroke: str, ring: str, r: float = 5.5) -> str:
    """Знак события: circle — круг, square — квадрат, diamond — ромб, half — круг, залитый
    наполовину (левая половина — fill, правая — цвет фона); ring — кольцо цвета фона."""
    common = f'fill="{fill}" stroke="{stroke}" stroke-width="1.6"'
    halo = f'stroke="{ring}" stroke-width="5" fill="{ring}"'
    if shape == "half":
        geo = f'cx="{x:.1f}" cy="{y:.1f}" r="{r}"'
        left = f"M{x:.1f},{y - r:.1f}A{r},{r} 0 0 0 {x:.1f},{y + r:.1f}Z"
        return (
            f'<circle {geo} {halo}/><circle {geo} fill="{ring}"/>'
            f'<path d="{left}" fill="{fill}"/>'
            f'<circle {geo} fill="none" stroke="{stroke}" stroke-width="1.6"/>'
        )
    if shape == "circle":
        geo = f'cx="{x:.1f}" cy="{y:.1f}" r="{r}"'
        return f"<circle {geo} {halo}/><circle {geo} {common}/>"
    if shape == "square":
        geo = f'x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" rx="1"'
        return f"<rect {geo} {halo}/><rect {geo} {common}/>"
    q = r * 1.3
    pts = f"{x:.1f},{y - q:.1f} {x + q:.1f},{y:.1f} {x:.1f},{y + q:.1f} {x - q:.1f},{y:.1f}"
    return f'<polygon points="{pts}" {halo}/><polygon points="{pts}" {common}/>'


# ── Рис. 2.1. Очаги одомашнивания и пути кукурузы (схема)

CENTERS_W, CENTERS_H = 760, 860
CENTERS_CENTER = (-86, 8)
CENTERS_FIT = [(-138, 32), (-55, 52), (-72, -38), (-34, -7)]  # океан у Калифорнии,
# Ньюфаундленд, север Патагонии, восток Бразилии
CENTERS_BLUR, CENTERS_OPACITY = 9, 0.6
# Раскладка подписей точек: смещение от точки и выравнивание. Только положение, текст — из данных.
PLACE_LABELS = {
    "balsas": (12, -20, "start"),
    "central_am": (-12, 4, "end"),
    "sw_amazon": (12, 26, "start"),
    "sw_us": (-12, -20, "end"),
    "ozarks": (-12, -32, "end"),
    "cahokia": (10, -14, "start"),
    "northeast": (10, -14, "start"),
}
# Что значит дата у точки: даты на пути разной природы, и ни одна не «время прихода».
# Текст — как в главе; число — из события точки в данных.
PLACE_WHEN = {
    "balsas": "находки {when}",
    "central_am": "прошла её к {when}",
    "sw_amazon": "в Южной Америке —\nк {when}",
    "sw_us": "{when}",
    "ozarks": "образцы {when}",
    "cahokia": "резко входит в рацион {when}",
    "northeast": "{when}",
}
# Даты, которые в тексте главы названы календарным годом, а не «лет назад».
PLACE_CALENDAR = {"sw_us", "cahokia"}
# Хвост «и дальше» у открытого конца пути: направление (градусы, 0 — на восток, + вниз), px.
ROUTE_TAIL = (8, 64)
# Изгиб отрезков пути (доля длины, + влево по ходу): линия огибает сушу, а не идёт морем.
ROUTE_BEND = {("balsas", "central_am"): 0.1, ("central_am", "sw_amazon"): 0.08}
# Отрезок, путь по которому неизвестен (todo пути north в data/agriculture.json).
ROUTE_UNKNOWN = {("balsas", "sw_us")}


def fig_centers(t: dict) -> str:
    data = agriculture()
    w, h = CENTERS_W, CENTERS_H
    pr = map_projection(CENTERS_CENTER, CENTERS_FIT, w, h)
    land_d, lakes_d = basemap_paths(pr, w, h)
    local, introduced = t[ORIGIN["local"]], t[ORIGIN["introduced"]]
    events = {e["id"]: e for e in data["events"]}
    places = {p["id"]: p for p in data["places"]}

    def blob(lon, lat, radius_km) -> str:
        return f'<path d="{path_d([pr(*q) for q in geo_circle(lon, lat, radius_km)], True)}"/>'

    blobs = "".join(blob(**b) for c in data["centers"] for b in c["blobs"])
    b = [
        "<defs>",
        f'<clipPath id="frame"><rect width="{w}" height="{h}"/></clipPath>',
        f'<path id="land" d="{land_d}"/>',
        '<filter id="soft" x="-30%" y="-30%" width="160%" height="160%">'
        f'<feGaussianBlur stdDeviation="{CENTERS_BLUR}"/></filter>',
        '<filter id="soft-key" x="-40%" y="-60%" width="180%" height="220%">'
        '<feGaussianBlur stdDeviation="2"/></filter>',
        f'<marker id="head" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" '
        f'markerHeight="5" orient="auto"><path d="M0,0L10,5L0,10z" fill="{introduced}"/></marker>',
        hatch_defs(t, introduced),
        "</defs>",
        '<g clip-path="url(#frame)">',
        f'<use href="#land" fill="{t["panel"]}"/>',
        f'<g opacity="{CENTERS_OPACITY}" fill="{local}" filter="url(#soft)">{blobs}</g>',
        f'<path d="{lakes_d}" fill="{t["bg"]}" stroke="{t["muted"]}" stroke-width=".4" '
        f'stroke-opacity=".5"/>',
        f'<use href="#land" fill="none" stroke="{t["muted"]}" stroke-width=".6" '
        f'stroke-opacity=".6"/>',
        "</g>",
    ]

    def place_text(x, y, s, size=13.5, anchor="middle"):
        return text(x, y, s, t["muted"], size, anchor, 400, SERIF, italic=True, halo=t["bg"])

    b.append(place_text(*pr(-104, -6), "Тихий океан", 14))
    b.append(place_text(*pr(-42, 22), "Атлантический океан", 14))
    b.append(place_text(*pr(-89, 24.6), "Мексиканский залив", 12))

    # пути кукурузы: отрезки между точками, у каждого — стрелка
    def segment(a: str, z: str) -> str:
        (x0, y0), (x1, y1) = (
            pr(places[a]["lon"], places[a]["lat"]),
            pr(places[z]["lon"], places[z]["lat"]),
        )
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        ux, uy = dx / dist, dy / dist
        x0, y0, x1, y1 = x0 + ux * 9, y0 + uy * 9, x1 - ux * 11, y1 - uy * 11
        bend = ROUTE_BEND.get((a, z), 0.0) * dist
        cx, cy = (x0 + x1) / 2 + uy * bend, (y0 + y1) / 2 - ux * bend
        dash = ' stroke-dasharray="2 5"' if (a, z) in ROUTE_UNKNOWN else ""
        return (
            f'<path d="M{x0:.1f},{y0:.1f}Q{cx:.1f},{cy:.1f} {x1:.1f},{y1:.1f}" fill="none" '
            f'stroke="{introduced}" stroke-width="2.6" stroke-linecap="round"{dash} '
            f'marker-end="url(#head)"/>'
        )

    on_route = set()
    for r in data["routes"]:
        for a, z in zip(r["steps"], r["steps"][1:], strict=False):
            b.append(segment(a, z))
        on_route.update(r["steps"])
        if r.get("open_end"):  # «и дальше»: линия гаснет, куда — неизвестно
            end = places[r["steps"][-1]]
            ex, ey = pr(end["lon"], end["lat"])
            ang, ln = math.radians(ROUTE_TAIL[0]), ROUTE_TAIL[1]
            ux, uy = math.cos(ang), math.sin(ang)
            ax, ay, zx, zy = ex + ux * 9, ey + uy * 9, ex + ux * ln, ey + uy * ln
            b.append(
                f'<linearGradient id="tail-{r["id"]}" gradientUnits="userSpaceOnUse" '
                f'x1="{ax:.1f}" y1="{ay:.1f}" x2="{zx:.1f}" y2="{zy:.1f}">'
                f'<stop offset="0" stop-color="{introduced}"/>'
                f'<stop offset="1" stop-color="{introduced}" stop-opacity="0"/></linearGradient>'
            )
            b.append(
                f'<path d="M{ax:.1f},{ay:.1f}L{zx:.1f},{zy:.1f}" stroke="url(#tail-{r["id"]})" '
                f'stroke-width="2.6" stroke-linecap="round" stroke-dasharray="7 4"/>'
            )
            b.append(
                text(
                    ex + ux * (ln * 0.55),
                    ey + uy * (ln * 0.55) + 17,
                    "и дальше",
                    t["ink"],
                    12.5,
                    "middle",
                    italic=True,
                    halo=t["bg"],
                )
            )

    # очаги: название и растения
    for c in data["centers"]:
        x, y = pr(c["label"]["lon"], c["label"]["lat"])
        anchor = c["label"]["anchor"]
        names = split_label(c["name"], 24)
        crops = ", ".join(re.sub(r"\s*\(.*?\)", "", s) for s in c["crops"])
        lines = [(s, t["ink"], 14, 600) for s in names]
        lines += [(s, t["muted"], 12, 400) for s in textwrap.wrap(crops, 26)]
        if c.get("todo"):  # пятно меньше очага — сказать об этом на карте
            lines.append(("пятно — только юго-запад Амазонии", t["muted"], 11.5, 400))
        for i, (s1, col, size, wt) in enumerate(lines):
            b.append(text(x, y + i * 15, s1, col, size, anchor, wt, halo=t["bg"]))

    # точки и даты
    for pid, p in places.items():
        x, y = pr(p["lon"], p["lat"])
        ev = events[p["event"]]
        tm = ev["time"]
        if pid in PLACE_CALENDAR:
            when = ("не позже " if "не позже" in ev["label"] else "≈") + cal_year(tm["from"])
        else:
            when = f"{bp_span(tm)} лет назад"
        when = PLACE_WHEN[pid].format(when=when)
        if ev.get("contested"):
            when += " — спорно"
        if ev["kind"] in ("staple", "important"):  # не точка пути, а перемена в питании
            b.append(mark("square", x, y, introduced, introduced, t["bg"], 5))
        else:
            fill = "url(#hatch)" if ev.get("contested") or pid not in on_route else introduced
            b.append(mark("circle", x, y, fill, introduced, t["bg"], 5.5))
        dx, dy, anchor = PLACE_LABELS[pid]
        b.append(text(x + dx, y + dy, p["name"], t["ink"], 13.5, anchor, 600, halo=t["bg"]))
        for k, s1 in enumerate(when.split("\n")):
            b.append(text(x + dx, y + dy + 15 * (k + 1), s1, t["ink"], 12.5, anchor, halo=t["bg"]))

    # легенда — в пустом углу Тихого океана
    lx, ly = 20, h - 236
    rows = [
        ("blob", "очаг одомашнивания растений"),
        ("arrow", "путь кукурузы"),
        ("unknown", "путь неизвестен: находок почти нет"),
        ("point", "точка на пути кукурузы"),
        ("square", "кукуруза входит в питание (не точка пути)"),
        ("hatch", "кукуруза без известного пути, дата спорна"),
    ]
    for i, (kind, s1) in enumerate(rows):
        yy = ly + i * 22
        if kind == "blob":
            b.append(rect(lx, yy - 9, 28, 18, t["panel"], 4))
            b.append(
                rect(lx + 3, yy - 6, 22, 12, local, 6, CENTERS_OPACITY, ' filter="url(#soft-key)"')
            )
        elif kind in ("arrow", "unknown"):
            dash = ' stroke-dasharray="2 5"' if kind == "unknown" else ""
            b.append(
                f'<path d="M{lx},{yy}L{lx + 24},{yy}" stroke="{introduced}" stroke-width="2.6" '
                f'stroke-linecap="round"{dash} marker-end="url(#head)"/>'
            )
        elif kind == "square":
            b.append(mark("square", lx + 14, yy, introduced, introduced, t["bg"], 5))
        else:
            fill = "url(#hatch)" if kind == "hatch" else introduced
            b.append(mark("circle", lx + 14, yy, fill, introduced, t["bg"], 5.5))
        b.append(text(lx + 40, yy + 4, s1, t["ink"], 12.5))
    notes = [
        "Даты у точек — разного рода: находки, нижняя",
        "граница, возраст образцов; это не время прихода",
        "кукурузы. Все даты приблизительные.",
    ]
    for i, s1 in enumerate(notes):
        b.append(text(lx, ly + len(rows) * 22 + 4 + i * 16, s1, t["muted"], 12))
    b.append(
        text(
            lx,
            ly + len(rows) * 22 + 4 + len(notes) * 16 + 10,
            "Схема: пятна и линии условные",
            t["muted"],
            12.5,
            italic=True,
        )
    )
    b.append(
        f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" fill="none" stroke="{t["rule"]}"/>'
    )
    names = ", ".join(c["name"] for c in data["centers"])
    return svg(
        w,
        h,
        t,
        b,
        "Очаги одомашнивания и пути кукурузы (схема)",
        f"Карта обеих Америк. Размытые пятна — очаги одомашнивания: {names}. Стрелки — пути "
        "кукурузы из долины Бальсас: на юг через Центральную Америку в Южную и на север, "
        "на юго-запад США и через Великие равнины в Озарк, а оттуда — «и дальше». Кахокия — "
        "отдельный знак: время, когда кукуруза резко входит в рацион. Северо-восток — "
        "отдельная точка без стрелки, датировка спорна. Даты у точек разного рода, а не время "
        "прихода. Пятна и линии условные.",
    )


# ── Рис. 2.2. Кукуруза: от появления до основы питания (данные и оценки)

LAG_FROM, LAG_TO = -11550, 1500  # календарные годы; слева — весь разброс генетической оценки
LAG_BANDS = [  # (название полосы, регионы в данных, единица подписей)
    ("Мезоамерика", ("meso",), "bp"),
    ("Южная Америка", ("south", "lowlands"), "bp"),
    ("Юго-запад США", ("sw",), "cal"),
    ("Восток Северной Америки", ("east",), "bp"),
]
# Начало и конец разрыва «появилась → стала основой питания» в каждой полосе.
LAG_GAPS = {
    "Мезоамерика": ("meso_maize_balsas", "meso_staple_belize"),
    "Южная Америка": ("south_maize_first", "south_maize_staple"),
    "Юго-запад США": ("sw_maize_first", "sw_uplands"),
    "Восток Северной Америки": ("east_maize_ohio", "east_maize_staple"),
}
# Раскладка подписей: (подпись к месту; сдвиг знака вниз от основной линии, px; сторона
# подписи: up, up2, up3 — выше на ярус, down, right; выравнивание). Текст даты — из данных.
LAG_LABELS = {
    "meso_maize_balsas": ("Бальсас", 0, "down", "middle"),
    "meso_staple_belize": ("Белиз", 0, "down", "middle"),
    "meso_staple_other": ("остальная Мезоамерика", 0, "up", "middle"),
    "south_maize_ca": ("по пути, Центральная Америка", 0, "up", "end"),
    "south_maize_first": ("Южная Америка", 0, "down", "end"),
    "south_maize_moxos": ("Льянос-де-Мохос", 30, "right", "start"),
    "south_maize_staple": ("", 0, "up", "end"),
    "sw_maize_first": ("", 0, "down", "middle"),
    "sw_uplands": ("нагорья", 0, "up", "middle"),
    "east_maize_ne": ("северо-восток", 0, "up2", "end"),
    "east_maize_ohio": ("Огайо", 0, "down", "end"),
    "east_maize_staple": ("почти весь восток", 0, "up3", "end"),
    "east_maize_cahokia": ("Кахокия", 24, "down", "end"),
}
LAG_CAL = {"east_maize_cahokia"}  # в тексте главы — календарным годом


def qualifier(label: str) -> str:
    """«не позже», «не раньше», «после» — из подписи события в данных, иначе «≈»."""
    for q in ("не позже", "не раньше", "после"):
        if q in label:
            return q + " "
    return ""


def when_text(ev: dict, unit: str) -> str:
    tm = ev["time"]
    q = qualifier(ev["label"]) if tm["to"] is None else ""  # у диапазона границы и так даны
    if unit == "cal":
        if tm["to"] is not None:
            return f"{cal_year(tm['from'])} – {cal_year(tm['to'])}"
        y = cal_year(tm["from"])
        return f"{q}{y}" if q else ("около рубежа эр" if tm["from"] == 0 else f"≈{y}")
    span = bp_span(tm)
    if q:
        span = span.lstrip("≈")
        span = f"{q}≈{span}"
    return f"{span} л. н."


def gap_text(first: dict, staple: dict) -> str:
    """Длина разрыва по данным: от начала основы питания назад до первого появления."""
    a, z = first["time"], staple["time"]
    hi = z["from"] - a["from"]
    lo = z["from"] - (a["to"] if a["to"] is not None else a["from"])

    def fmt(v: int) -> str:
        return num(round(v / 500) / 2) if v >= 1000 else str(round(v / 100) * 100)

    unit = "тыс. лет" if hi >= 1000 else "лет"
    return f"≈{fmt(lo)} {unit}" if fmt(lo) == fmt(hi) else f"≈{fmt(lo)}–{fmt(hi)} {unit}"


def fig_lag(t: dict) -> str:
    data = agriculture()
    events = data["events"]
    w = 760
    x0, x1 = 172, 742
    top = 64
    band_h = {"Мезоамерика": 146, "Восток Северной Америки": 118}
    default_h = 104
    h = top + sum(band_h.get(n, default_h) for n, *_ in LAG_BANDS) + 172
    accent = t["z-n"]

    def px(y: float) -> float:
        return x0 + (y - LAG_FROM) / (LAG_TO - LAG_FROM) * (x1 - x0)

    b = [
        "<defs>",
        hatch_defs(t, t["ink"]),
        f'<clipPath id="plot"><rect x="{x0}" y="0" width="{x1 - x0}" height="{h}"/></clipPath>',
        '<filter id="blur" x="-10%" y="-80%" width="120%" height="260%">'
        '<feGaussianBlur stdDeviation="3 1.2"/></filter>',
        '<filter id="blur-wide" x="-10%" y="-80%" width="120%" height="260%">'
        '<feGaussianBlur stdDeviation="14 1.5"/></filter>',
        f'<linearGradient id="tail" x1="0" x2="1"><stop offset="0" stop-color="{t["ink"]}" '
        f'stop-opacity=".55"/><stop offset="1" stop-color="{t["ink"]}" stop-opacity="0"/>'
        "</linearGradient>",
        "</defs>",
    ]

    # шкалы: сверху — годы, снизу — «лет назад»
    bands_h = sum(band_h.get(n, default_h) for n, *_ in LAG_BANDS)
    yb = top + bands_h
    for y in range(-11000, LAG_TO + 1, 1000):
        x = px(y)
        b.append(line(x, top - 6, x, yb, t["rule"], 1.1 if y == 0 else 0.7))
        b.append(text(x, top - 12, grouped(abs(y)) if y else "0", t["ink"], 11.5, "middle"))
    b.append(text(px(LAG_FROM), top - 32, "годы", t["muted"], 11.5))
    b.append(text(px(0) + 6, top - 32, "н. э.", t["muted"], 11.5))
    b.append(text(px(0) - 6, top - 32, "← до н. э.", t["muted"], 11.5, "end"))
    for v in range(13000, 0, -1000):
        x = px(1950 - v)
        b.append(line(x, yb, x, yb + 5, t["muted"], 0.8))
        b.append(text(x, yb + 18, grouped(v), t["muted"], 11.5, "middle"))
    b.append(text((x0 + x1) / 2, yb + 36, "лет назад", t["muted"], 11.5, "middle"))

    def soft_bar(a, z, y, hh, color, opacity, filt="blur"):
        return (
            f'<rect x="{a:.1f}" y="{y - hh / 2:.1f}" width="{max(z - a, 4):.1f}" height="{hh}" '
            f'rx="{hh / 2}" fill="{color}" fill-opacity="{opacity}" filter="url(#{filt})"/>'
        )

    def sign(ev):
        if ev["kind"] == "important":
            return "half", t["ink"]
        if ev["kind"] == "staple":
            return ("square" if ev.get("evidence") == "isotopes" else "circle"), t["ink"]
        return "circle", "url(#hatch)" if ev.get("contested") else t["bg"]

    y_top = top
    for name, regions, unit in LAG_BANDS:
        bh = band_h.get(name, default_h)
        i = [n for n, *_ in LAG_BANDS].index(name)
        if i % 2 == 0:
            b.append(rect(0, y_top, w, bh, t["band"], 0))
        yc = y_top + bh - 54
        for j, s1 in enumerate(split_label(name, 16)):
            nl = len(split_label(name, 16))
            b.append(text(14, yc + 5 + (j - (nl - 1) / 2) * 16, s1, t["ink"], 14, "start", 600))
        b.append(line(x0, yc, x1, yc, t["rule"], 1))
        halo = t["band"] if i % 2 == 0 else t["bg"]
        evs = {
            e["id"]: e
            for e in events
            if e["region"] in regions
            and e["crop"] == "кукуруза"
            and e["kind"] in ("first", "cultivation", "staple", "important", "domestication")
        }

        # генетическая оценка — широкий размытый отрезок над основной линией
        for e in evs.values():
            if e.get("evidence") != "genetics":
                continue
            tm = e["time"]
            yg = yc - 36
            b.append(
                f'<g clip-path="url(#plot)">'
                f"{soft_bar(px(tm['from']), px(tm['to']), yg, 12, t['muted'], 0.55, 'blur-wide')}"
                "</g>"
            )
            xc = px(tm["central"])
            b.append(line(xc, yg - 8, xc, yg + 8, t["ink"], 1.6))
            gen = [
                "генетический расчёт самого раннего возможного времени одомашнивания: "
                f"≈{grouped(bp(tm['central']))} л. н.",
                f"разброс {grouped(bp(tm['from']))}–{grouped(bp(tm['to']))} л. н.; "
                "само одомашнивание, вероятно, позже",
            ]
            for k, s1 in enumerate(gen):
                b.append(text(x0 + 4, yg - 29 + k * 15, s1, t["ink"], 12, halo=halo))

        # разрыв
        fa, za = LAG_GAPS[name]
        ef, es = evs[fa], evs[za]

        def xmid(ev):
            tm = ev["time"]
            return px((tm["from"] + tm["to"]) / 2) if tm["to"] is not None else px(tm["from"])

        ga, gz = xmid(ef), px(es["time"]["from"])
        b.append(rect(ga, yc - 7, gz - ga, 14, accent, 3, 0.38))
        gt = gap_text(ef, es)
        if gz - ga > 8 + len(gt) * 6.2:
            b.append(text((ga + gz) / 2, yc + 4, gt, t["ink"], 11.5, "middle", 600))
        else:  # узкий разрыв — подпись над ним
            b.append(text(gz, yc - 12, gt, t["ink"], 11.5, "end", 600, halo=halo))

        for eid, e in evs.items():
            if e.get("evidence") == "genetics":
                continue
            place, dy, side, anchor = LAG_LABELS[eid]
            tm = e["time"]
            y = yc + dy
            a = px(tm["from"])
            if tm["to"] is not None:
                b.append(soft_bar(a, px(tm["to"]), y, 10, t["ink"], 0.35))
                x = xmid(e)
            elif not tm.get("point"):  # открыто вправо: «не раньше», «после»
                b.append(f'<g clip-path="url(#plot)">{rect(a, y - 3, 60, 6, "url(#tail)", 0)}</g>')
                x = a
            else:
                x = a
            shape, fill = sign(e)
            b.append(mark(shape, x, y, fill, t["ink"], t["bg"], 5))
            when = when_text(e, "cal" if eid in LAG_CAL else unit)
            if e.get("contested"):
                when += " — спорно"
            s1 = f"{place}: {when}" if place else when
            ly = y + {"up": -12, "up2": -28, "up3": -44, "down": 21, "right": 4}[side]
            dx = 10 if side == "right" else {"start": -4, "end": 4, "middle": 0}[anchor]
            b.append(text(x + dx, ly, s1, t["ink"], 12, anchor, halo=halo))
        y_top += bh

    # легенда
    ly = yb + 62
    items = [
        ("first", "первое появление — по находкам"),
        ("arch", "основа питания — по находкам и выводам авторов"),
        ("iso", "основа питания — по изотопам костей"),
        ("half", "важная культура, но не основа питания"),
        ("gap", "от появления до времени, когда на неё опираются"),
        ("hatch", "датировка спорна"),
        ("gen", "генетический расчёт: самое раннее возможное время"),
    ]
    for k, (kind, s1) in enumerate(items):
        lx = 24 + (k % 2) * 372
        yy = ly + (k // 2) * 22
        if kind == "gap":
            b.append(rect(lx, yy - 6, 26, 12, accent, 3, 0.38))
        elif kind == "gen":
            b.append(soft_bar(lx, lx + 26, yy, 10, t["muted"], 0.55))
        else:
            shape = {"iso": "square", "half": "half"}.get(kind, "circle")
            fill = {"first": t["bg"], "hatch": "url(#hatch)"}.get(kind, t["ink"])
            b.append(mark(shape, lx + 13, yy, fill, t["ink"], t["bg"], 5))
        b.append(text(lx + 36, yy + 4.5, s1, t["ink"], 12.5))
    b.append(
        text(
            w - 16,
            h - 12,
            "Все даты приблизительные; размытый край — неточная граница",
            t["muted"],
            12,
            "end",
            italic=True,
        )
    )
    desc = []
    ev = {e["id"]: e for e in events}
    for name, _regions, unit in LAG_BANDS:
        fa, za = LAG_GAPS[name]
        role = "важная культура" if ev[za]["kind"] == "important" else "основа питания"
        desc.append(
            f"{name}: появление — {when_text(ev[fa], unit)}, {role} — "
            f"{when_text(ev[za], unit)}, разрыв {gap_text(ev[fa], ev[za])}"
        )
    return svg(
        w,
        h,
        t,
        b,
        "Кукуруза: когда появляется и когда становится основой питания",
        "; ".join(desc) + ". Генетическая оценка самого раннего возможного времени "
        "одомашнивания — широкий размытый отрезок от 13 100 до 5700 лет назад.",
    )


# ── Рис. 2.3. Как собирались «три сестры» на востоке и на юго-западе (данные)

SIS_FROM, SIS_TO = -3500, 1500
# Раскладка: (подпись — культура; ярус подписи: + выше линии, − ниже; выравнивание).
# Подписи одного ряда разнесены по ярусам так, чтобы выноски не пересекали текст.
SISTERS = {
    "Восток": {
        "east_squash": ("тыква", 3, "start"),
        "east_sunflower": ("подсолнечник", 2, "start"),
        "east_marshelder": ("Iva annua", 1, "start"),
        "east_complex": ("марь, набор из пяти культур", 1, "start"),
        "east_maize_ne": ("кукуруза на северо-востоке — спорно", 2, "end"),
        "east_maize_ohio": ("кукуруза на Огайо", -1, "end"),
        "east_maize_staple": ("кукуруза — важная культура", -2, "end"),
        "east_beans": ("фасоль", -3, "end"),
        "east_beans_ne": ("фасоль на северо-востоке", -4, "end"),
    },
    "Юго-Запад": {
        "sw_maize_first": ("кукуруза (не позже)", 1, "start"),
        "sw_squash": ("тыква", -1, "start"),
        "sw_beans": ("фасоль (с амарантом и хлопком)", -2, "middle"),
        "sw_uplands": ("кукуруза кормит нагорья", 1, "middle"),
    },
}
SISTERS_SUB = {"Восток": "Северной Америки", "Юго-Запад": "США"}


def fig_sisters(t: dict) -> str:
    ev = {e["id"]: e for e in agriculture()["events"]}
    w, x0, x1 = 760, 132, 742
    local, introduced = t[ORIGIN["local"]], t[ORIGIN["introduced"]]
    step = 17

    def levels(row):
        lv = [v[1] for v in SISTERS[row].values()]
        return max(0, *lv), -min(0, *lv)

    top = 58
    rows_y = []
    y = top
    for row in SISTERS:
        up, down = levels(row)
        y += 20 + up * step
        rows_y.append(y)
        y += 18 + down * step
    foot = 114  # легенда и примечание под шкалой
    h = y + foot

    def px(yr: float) -> float:
        return x0 + (yr - SIS_FROM) / (SIS_TO - SIS_FROM) * (x1 - x0)

    b = [
        "<defs>",
        hatch_defs(t, introduced),
        '<filter id="blur" x="-10%" y="-80%" width="120%" height="260%">'
        '<feGaussianBlur stdDeviation="3 1"/></filter>',
        "</defs>",
    ]
    for yr in range(SIS_FROM, SIS_TO + 1, 500):
        x = px(yr)
        b.append(line(x, top - 6, x, h - foot, t["rule"], 1.1 if yr == 0 else 0.7))
        b.append(text(x, top - 12, grouped(abs(yr)) if yr else "0", t["ink"], 11.5, "middle"))
    b.append(text(px(0) - 6, top - 30, "← до н. э.", t["muted"], 11.5, "end"))
    b.append(text(px(0) + 6, top - 30, "н. э.", t["muted"], 11.5))
    b.append(text(x0, top - 30, "годы", t["muted"], 11.5))

    for row, yc in zip(SISTERS, rows_y, strict=True):
        b.append(text(14, yc - 2, row, t["ink"], 14.5, "start", 600))
        b.append(text(14, yc + 14, SISTERS_SUB[row], t["muted"], 12))
        b.append(line(x0, yc, x1, yc, t["muted"], 1))
        marks, labels = [], []
        for eid, (crop, lvl, anchor) in SISTERS[row].items():
            e = ev[eid]
            tm = e["time"]
            col = local if e["origin"] == "local" else introduced
            a = px(tm["from"])
            if tm["to"] is not None:
                z = px(tm["to"])
                marks.append(
                    f'<rect x="{a:.1f}" y="{yc - 5:.1f}" width="{z - a:.1f}" height="10" rx="5" '
                    f'fill="{col}" fill-opacity=".45" filter="url(#blur)"/>'
                )
                x = (a + z) / 2  # знака нет: точки внутри промежутка источник не даёт
            else:
                x = a  # «после» — знак роли кукурузы и так значит «с этого времени»
            if tm["to"] is None:
                if e["kind"] in ("staple", "important"):  # не приход, а рост роли кукурузы
                    shape = "square"
                else:
                    shape = "circle" if e["origin"] == "local" else "diamond"
                fill = "url(#hatch)" if e.get("contested") else col
                r = 5 if shape == "square" else 5.5
                marks.append(mark(shape, x, yc, fill, col, t["bg"], r))
            ly = yc - 14 - (lvl - 1) * step if lvl > 0 else yc + 22 + (-lvl - 1) * step
            lead_end = ly + 4 if lvl > 0 else ly - 12
            if abs(lvl) > 1 or anchor != "middle":
                labels.append(line(x, yc + (-8 if lvl > 0 else 8), x, lead_end, t["muted"], 0.8))
            dx = {"start": -3, "end": 3, "middle": 0}[anchor]
            labels.append(text(x + dx, ly, crop, t["ink"], 12.5, anchor, halo=t["bg"]))
        b += labels + marks

    ly = h - 88
    items = [
        ("local", "своё растение — одомашнено здесь"),
        ("introduced", "пришло из Мезоамерики — первое появление"),
        ("role", "с этого времени кукуруза важна в питании"),
        ("hatch", "датировка спорна"),
        ("range", "известен только промежуток"),
    ]
    for k, (kind, s1) in enumerate(items):
        lx = 24 + (k % 2) * 372
        yy = ly + (k // 2) * 22
        if kind == "range":
            b.append(
                f'<rect x="{lx}" y="{yy - 5}" width="28" height="10" rx="5" fill="{introduced}" '
                'fill-opacity=".45" filter="url(#blur)"/>'
            )
        elif kind == "role":
            b.append(mark("square", lx + 14, yy, introduced, introduced, t["bg"], 5))
        else:
            shape = "circle" if kind == "local" else "diamond"
            col = local if kind == "local" else introduced
            fill = "url(#hatch)" if kind == "hatch" else col
            b.append(mark(shape, lx + 14, yy, fill, col, t["bg"], 5.5))
        b.append(text(lx + 36, yy + 4.5, s1, t["ink"], 12.5))
    b.append(
        text(
            w - 16,
            h - 12,
            "Все даты приблизительные — по источникам, на которые ссылается глава",
            t["muted"],
            12,
            "end",
            italic=True,
        )
    )

    def describe(row):
        parts = []
        for eid, (crop, *_r) in SISTERS[row].items():
            tm = ev[eid]["time"]
            when = (
                f"{cal_year(tm['from'])} – {cal_year(tm['to'])}"
                if tm["to"] is not None
                else "около рубежа эр"
                if tm["from"] == 0
                else f"≈{cal_year(math.floor(tm['from'] / 50 + 0.5) * 50)}"
            )
            origin = (
                "рост роли"
                if ev[eid]["kind"] in ("staple", "important")
                else "своё растение"
                if ev[eid]["origin"] == "local"
                else "пришло"
            )
            parts.append(f"{crop} ({origin}): {when}")
        return f"{row} — " + ", ".join(parts)

    return svg(
        w,
        h,
        t,
        b,
        "Как собирались «три сестры» на востоке и на юго-западе",
        "; ".join(describe(r) for r in SISTERS) + ".",
    )


# ── Глава 3. Общее: данные, цвета видов связей

# Вещь и люди — пара токенов --z-n / --z-t: validate_palette.js навыка dataviz проходит
# для обеих тем (на фонах --bg). Третьего цвета для «не подтвердилось» нет: любой третий
# токен проваливает проверку различимости при дальтонизме хотя бы в одной теме, поэтому
# опровергнутая связь — нейтральный --muted, пунктир и крест (не цвет, а форма).
KIND = {"thing": "z-n", "people": "z-t", "disproved": "muted"}


def complex_data() -> dict:
    return json.loads(COMPLEX.read_text(encoding="utf-8"))


def arrow_marker(mid: str, color: str, size: float = 5.0) -> str:
    return (
        f'<marker id="{mid}" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="{size}" '
        f'markerHeight="{size}" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" '
        f'fill="{color}"/></marker>'
    )


def bird(shape: str, x: float, y: float, fill: str, r: float = 3.6) -> str:
    """Маленький знак птицы на схеме 3.1: форма — материнская линия."""
    if shape == "circle":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"/>'
    if shape == "square":
        return rect(x - r * 0.9, y - r * 0.9, r * 1.8, r * 1.8, fill, 0.6)
    if shape == "diamond":
        q = r * 1.25
        return polygon([(x, y - q), (x + q, y), (x, y + q), (x - q, y)], fill)
    q = r * 1.2  # triangle
    return polygon([(x, y - q), (x + q, y + q * 0.8), (x - q, y + q * 0.8)], fill)


# ── Рис. 3.1. Четыре пути вещи или человека (схема)

MODES = [  # (название, что происходит — две строки, след)
    (
        "Эстафета",
        ["вещь переходит", "от соседа к соседу"],
        "находки есть по всему пути, и чем дальше от источника, тем их меньше",
    ),
    (
        "Целевой поход",
        ["люди сами ходят", "к далёкому источнику"],
        "у источника и у потребителя находки есть, а между ними — нет",
    ),
    (
        "Промежуточный центр",
        ["птиц разводят", "на полпути"],
        "все птицы у потребителей — потомки немногих предков",
    ),
    (
        "Переселение",
        ["движутся", "сами люди"],
        "стронций в зубах не местный: человек вырос в другом месте",
    ),
]


def fig_modes(t: dict) -> str:
    w, top, lane = 760, 34, 128
    h = top + lane * len(MODES) + 12
    x0, x1 = 206, 726  # схема: слева источник, справа потребитель
    thing, people, ink, muted = t[KIND["thing"]], t[KIND["people"]], t["ink"], t["muted"]
    b = [
        "<defs>",
        arrow_marker("head-thing", thing),
        arrow_marker("head-people", people),
        arrow_marker("head-muted", muted),
        hatch_defs(t, people, "hatch-people"),
        '<filter id="soft" x="-30%" y="-60%" width="160%" height="220%">'
        '<feGaussianBlur stdDeviation="5"/></filter>',
        "</defs>",
        text(w - 14, 20, "Схема: условно", muted, 12, "end", italic=True),
    ]

    def node(x, y, label, filled=False, color=ink, r=6.5):
        fill = color if filled else t["bg"]
        out = [
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{color}" '
            'stroke-width="1.6"/>'
        ]
        if label:
            out.append(text(x, y + 24, label, muted, 12, "middle"))
        return out

    def arrow(xa, ya, xz, yz, mid, color, width=1.8, dash=None, bend=0.0):
        cx, cy = (xa + xz) / 2, (ya + yz) / 2 - bend
        d = f' stroke-dasharray="{dash}"' if dash else ""
        return (
            f'<path d="M{xa:.1f},{ya:.1f}Q{cx:.1f},{cy:.1f} {xz:.1f},{yz:.1f}" fill="none" '
            f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"{d} '
            f'marker-end="url(#{mid})"/>'
        )

    def finds(x, y, n):  # столбик находок над узлом
        return [rect(x - 5, y - 13 - k * 7, 10, 5, thing, 1.5) for k in range(n)]

    for i, (name, what, trace) in enumerate(MODES):
        y0 = top + i * lane
        if i % 2 == 0:
            b.append(rect(0, y0, w, lane, t["band"], 0))
        b.append(text(16, y0 + 30, name, ink, 15, "start", 600))
        for k, s in enumerate(what):
            b.append(text(16, y0 + 48 + k * 15, s, muted, 12.5))
        yc = y0 + 70
        b.append(text(x0 - 6, y0 + lane - 12, "След: ", ink, 12.5, "start", 600))
        b.append(text(x0 + 32, y0 + lane - 12, trace, ink, 12.5))

        if i == 0:  # эстафета: цепочка общин, находок всё меньше
            xs = [x0 + k * (x1 - x0) / 5 for k in range(6)]
            for k, x in enumerate(xs):
                b += finds(x, yc, 6 - k)
                if k:
                    b.append(arrow(xs[k - 1] + 9, yc, x - 10, yc, "head-thing", thing))
                b += node(x, yc, "", filled=k == 0, color=thing if k == 0 else ink)
            b.append(text(xs[0], yc + 24, "источник", muted, 12, "middle"))
            b.append(text((xs[1] + xs[-1]) / 2, yc + 24, "общины по цепочке", muted, 12, "middle"))
        elif i == 1:  # целевой поход: туда и обратно, по пути пусто
            xs, xc = x0, x1 - 24
            mids = [xs + k * (xc - xs) / 4 for k in (1, 2, 3)]
            b.append(arrow(xc - 8, yc - 6, xs + 10, yc - 6, "head-muted", muted, 1.4, "4 4", 76))
            b.append(arrow(xs + 10, yc - 2, xc - 10, yc - 2, "head-thing", thing, 1.8, None, 26))
            b.append(text((xs + xc) / 2, yc - 50, "поход туда", muted, 11.5, "middle", italic=True))
            b.append(
                text(
                    (xs + xc) / 2, yc - 20, "обратно — с вещью", muted, 11.5, "middle", italic=True
                )
            )
            b += finds(xs, yc, 3)
            b += finds(xc, yc, 6)
            for x in mids:
                b += node(x, yc, "", r=5, color=muted)
            b += node(xs, yc, "источник", filled=True, color=thing)
            b += node(xc, yc, "потребитель")
            b.append(text(mids[1], yc + 24, "общины по пути", muted, 12, "middle"))
        elif i == 2:  # промежуточный центр: разнообразие в ареале, одна линия дальше
            ax, cx_, zx = x0 + 44, (x0 + x1) / 2 - 4, x1 - 20
            b.append(
                f'<ellipse cx="{ax:.1f}" cy="{yc - 4:.1f}" rx="54" ry="26" fill="{thing}" '
                f'fill-opacity=".28" filter="url(#soft)"/>'
            )
            shapes = ["circle", "square", "diamond", "triangle", "square", "circle", "diamond"]
            spots = [(-28, -14), (-10, -18), (10, -14), (28, -8), (-20, 2), (2, 0), (22, 8)]
            for s, (dx, dy) in zip(shapes, spots, strict=True):
                b.append(bird(s, ax + dx, yc - 4 + dy, ink))
            b.append(text(ax, yc + 30, "природный ареал", muted, 12, "middle"))
            b.append(arrow(ax + 58, yc - 4, cx_ - 40, yc - 4, "head-thing", thing))
            b.append(rect(cx_ - 34, yc - 20, 68, 32, t["panel"], 6, 1, f' stroke="{thing}"'))
            b.append(bird("circle", cx_ - 9, yc - 4, ink))
            b.append(bird("circle", cx_ + 9, yc - 4, ink))
            b.append(text(cx_, yc + 30, "поселение, где разводят", muted, 12, "middle"))
            # дальше от центра — любым путём: эстафетой (вверху) или походом (внизу)
            xa, xz = cx_ + 38, zx - 30
            yu, yd = yc - 32, yc + 4
            relay = [xa + (xz - xa) * k / 3 for k in range(4)]
            b.append(arrow(xa, yc - 14, relay[1] - 7, yu, "head-thing", thing, 1.5))
            for k in (2, 3):
                b.append(arrow(relay[k - 1] + 6, yu, relay[k] - 8, yu, "head-thing", thing, 1.5))
            for x in relay[1:3]:
                b += node(x, yu, "", r=4, color=ink)
            b.append(
                text(
                    (xa + xz) / 2, yu - 8, "дальше — эстафетой", muted, 11.5, "middle", italic=True
                )
            )
            b.append(arrow(xz - 4, yd - 3, xa + 2, yd - 3, "head-muted", muted, 1.3, "4 4", 10))
            b.append(arrow(xa + 2, yd + 3, xz - 6, yd + 3, "head-thing", thing, 1.6, None, -10))
            b.append(
                text((xa + xz) / 2 + 24, yd + 26, "или походом", muted, 11.5, "middle", italic=True)
            )
            for yy in (yu, yd):
                for j in range(3):
                    b.append(bird("circle", zx - 16 + j * 11, yy, ink, 3.2))
            b.append(text(zx, yc + 38, "потребители", muted, 12, "middle"))
        else:  # переселение: зубы выдают родные места
            hx, nx = x0 + 40, x1 - 90
            b.append(rect(hx - 44, yc - 22, 88, 36, "url(#hatch-people)", 6, 0.6))
            b.append(text(hx, yc + 30, "родные места", muted, 12, "middle"))
            b.append(rect(nx - 90, yc - 22, 180, 36, t["panel"], 6, 1, f' stroke="{t["rule"]}"'))
            b.append(text(nx, yc + 30, "новое место: погребения", muted, 12, "middle"))
            b.append(arrow(hx + 52, yc - 4, nx - 100, yc - 4, "head-people", people, 2.2))
            for k in range(3):
                b.append(
                    f'<circle cx="{hx + 90 + k * 26:.1f}" cy="{yc - 4:.1f}" r="4.5" '
                    f'fill="{people}" stroke="{t["bg"]}" stroke-width="1.5"/>'
                )
            for k in range(6):  # погребения: двое — с «чужим» стронцием, как у родных мест
                gx = nx - 70 + k * 28
                migrant = k in (1, 4)
                fill = "url(#hatch-people)" if migrant else t["bg"]
                stroke = people if migrant else muted
                b.append(rect(gx - 6, yc - 12, 12, 16, fill, 3, 1, f' stroke="{stroke}"'))
    return svg(
        w,
        h,
        t,
        b,
        "Четыре пути, которыми вещь или человек проходили далеко (схема)",
        "Эстафета: вещь переходит от общины к общине, и находок тем меньше, чем дальше от "
        "источника. Целевой поход: люди потребителя сами ходят к источнику и обратно, между "
        "ними находок нет. Промежуточный центр: птиц из природного ареала разводят в "
        "поселении на полпути, и все птицы у потребителей — потомки немногих предков. "
        "Переселение: движутся сами люди, и стронций в их зубах не совпадает с местным. "
        "Расстояния и число участников условные.",
    )


# ── Рис. 3.2 и 3.4. Вещи в пути и люди в пути (карты по data/complex.json)
#
# Обе карты рисует route_map по спецификации: какие виды связей показывать, рамка, подписи.
# Точки берутся только те, что стоят на показанных связях (и места разведения ара — на
# карте вещей).

# Линии без начала: откуда начинается хвост (lon, lat) — схема направления, а не место.
# Какао и ара подходят к Чако с юга, мимо Олд-Тауна и Пакиме, а не через них: Мезоамерика
# лежит к югу, но откуда и каким путём они шли на самом деле, неизвестно, — линия и не
# начинается нигде. Ближайшие плантации какао по Крауну — и на севере Веракруса, и в
# Колиме, так что ни восток, ни запад хвост не выбирает.
THINGS_MAP = {
    "kinds": {"thing", "disproved"},
    "size": (760, 720),
    "center": (-98, 33),
    "fit": [(-127, 50.5), (-67, 48.5), (-127, 23), (-118, 15.5), (-80, 16)],
    "seas": [
        (-121, 24, "Тихий океан", 14),
        (-89.6, 27.3, "Мексиканский", 12),
        (-89.6, 26.3, "залив", 12),
        (-66, 33, "Атлантический", 13),
        (-66, 31.8, "океан", 13),
    ],
    "tails": {"cacao_chaco": [(-105.8, 28.9)], "macaw_chaco": [(-104.8, 29.3)]},
    "bend": {"copper_superior": 0.0, "obsidian": 0.1, "turquoise": 0.0},
    # Подписи путей: (lon, lat, выравнивание, строки). Числа — из данных: {d} расстояние,
    # {s} доля, {s2} доля в самой точке to, {y} время.
    "link_labels": {
        "copper_superior": (
            -82.2,
            45.9,
            "start",
            [
                "медь Верхнего озера",
                "{d} по прямой",
                "{s} вещей семи центров;",
                "в самой Маунд-Сити",
                "меди Мичипикотена нет",
            ],
        ),
        "copper_appalachia": (
            -79.4,
            32.5,
            "end",
            ["медь южных Аппалачей", "{d} · {s} по семи центрам,", "в самой Маунд-Сити — {s2}"],
        ),
        "obsidian": (-101.5, 42.0, "middle", ["обсидиан Йеллоустона"]),
        "cacao_chaco": (-103.8, 27.4, "end", ["какао — откуда,", "неизвестно"]),
        "macaw_chaco": (-103.8, 25.5, "end", ["ара: природный ареал —", "{d} южнее"]),
        "turquoise": (
            -103.1,
            32.4,
            "start",
            [
                "бирюза юго-запада",
                "в Теночтитлане —",
                "не подтвердилась",
                "(последний век",
                "перед испанцами)",
            ],
        ),
    },
    "place_labels": {  # (dx, dy, выравнивание); подпись — из name; None — без подписи
        "mound_city": (-2, -12, "start"),
        "keweenaw": (-6, 15, "end"),
        "isle_royale": (-8, -6, "end"),
        "michipicoten": (8, -6, "start"),
        "appalachia": None,  # район назван в подписи пути
        "obsidian_cliff": (0, -10, "middle"),
        "chaco": (9, -6, "start"),
        "old_town": (-10, 0, "end"),
        "paquime": (-10, 4, "end"),
        "southwest": None,  # район назван в подписи пути
        "tenochtitlan": (-4, 17, "end"),
    },
    # Пояснения под подписью точки: (путь, откуда доля, или None; строки; сдвиг по x).
    "place_extra": {"mound_city": (None, ["на карте — все центры", "хоупвелла в Огайо"], 10)},
    "legend": [
        ("thing", "путь вещи: источник найден по составу"),
        ("tail", "путь вещи: откуда — неизвестно"),
        ("disproved", "связь, которую анализ не подтвердил"),
        ("source", "источник материала"),
        ("breeding", "где разводили ара"),
        ("probable", "вероятный центр разведения"),
    ],
    "notes": [
        "Линии — направления, а не дороги.",
        "Положение точек ориентировочное.",
        "Даты приблизительные.",
    ],
    "legend_w": 276,
    "legend_right": True,  # слева внизу — подписи какао и ара
}

PEOPLE_MAP = {
    "kinds": {"people"},
    # Кахокия вне рамки, а откуда шли её переселенцы, неизвестно, — она описана в тексте.
    "exclude": {"cahokia_migrants"},
    "size": (760, 480),
    "center": (-96, 18),
    "fit": [(-103.6, 21.6), (-88.2, 21.6), (-103.6, 14.6), (-88.2, 14.6)],
    "seas": [
        (-100.6, 16.2, "Тихий океан", 14),
        (-94.6, 21.1, "Мексиканский залив", 13),
    ],
    "tails": {},
    "bend": {"teo_tikal": -0.18, "teo_chiapas": 0.12, "teo_michoacan": 0.12, "teo_oaxaca": -0.1},
    "link_labels": {
        "teo_tikal": (-92.6, 19.75, "start", ["вторжение в Тикаль,", "{y}, по надписям майя"]),
    },
    "place_labels": {
        "teotihuacan": (0, -14, "middle"),
        "tikal": (9, 16, "start"),
        "oaxaca": (0, 20, "middle"),
        "michoacan": (0, 20, "middle"),
        "gulf_coast": (10, 4, "start"),
        "chiapas": (0, 20, "middle"),
    },
    "place_extra": {
        "teotihuacan": (
            "teo_tlajinga",
            ["в районе Тлахинга ≈{s} погребённых —", "переселенцы; откуда — не сказано"],
            0,
            -70,
        ),
        "oaxaca": (None, ["«квартал Оахаки»"], 0),
        "gulf_coast": (None, ["«квартал торговцев»"], 0),
        "michoacan": (None, ["небольшая группа"], 0),
        "chiapas": (None, ["погребены в Теопанкаско"], 0),
    },
    "legend": [
        ("people", "путь людей"),
        ("origin", "откуда пришли (условная точка района)"),
        ("center", "город"),
    ],
    "notes": [
        "Линии — направления, а не дороги.",
        "Время переселений в Теотиуакан не указано;",
        "378 г. — год из надписей майя.",
    ],
    "legend_w": 290,
}


# Пояснения у центров разведения: когда — из данных; формулировки — из главы.
BREEDING_NOTE = {
    "old_town": ["разведение (по скорлупе яиц), {w}"],
    "paquime": ["вероятный центр разведения, {w};", "прямых свидетельств нет"],
}


def breeding_mark(x: float, y: float, bg: str, c: str, probable: bool) -> str:
    """Кольцо с точкой — где разводили ара; пунктирное — разведение вероятно, но не доказано."""
    dash = ' stroke-dasharray="2.6 1.9"' if probable else ""
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{bg}" stroke="{c}" '
        f'stroke-width="2.2"{dash}/><circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{c}"/>'
    )


def span_text(sp: dict) -> str:
    if sp.get("label") and sp["start"] != sp["end"]:
        return sp["label"]
    if sp["end"] is None or sp["start"] == sp["end"]:
        return f"{sp['start']} г." if sp["dating"] == "documented" else f"≈{sp['start']} г."
    return f"{sp['start']}–{sp['end']} гг."


def km_text(d: dict) -> str:
    if d["high"] is None:
        return f"больше {grouped(int(d['low']))} км"
    if d["low"] == d["high"]:
        return f"{'≈' if d.get('about') else ''}{grouped(int(d['low']))} км"
    return f"{grouped(int(d['low']))}–{grouped(int(d['high']))} км"


def share_text(link: dict) -> str:
    return f"{num(link['share_pct'])}%" if "share_pct" in link else link.get("share_words", "")


def map_curve(x0, y0, x1, y1, bend, trim0=7.0, trim1=9.0):
    """Квадратичная кривая от (x0, y0) к (x1, y1) с обрезанными концами; bend — доля длины."""
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy) or 1
    ux, uy = dx / dist, dy / dist
    x0, y0, x1, y1 = x0 + ux * trim0, y0 + uy * trim0, x1 - ux * trim1, y1 - uy * trim1
    cx, cy = (x0 + x1) / 2 + uy * bend * dist, (y0 + y1) / 2 - ux * bend * dist
    return (x0, y0, cx, cy, x1, y1)


def route_map(t: dict, spec: dict, title: str, desc: str) -> str:
    data = complex_data()
    w, h = spec["size"]
    pr = map_projection(spec["center"], spec["fit"], w, h)
    land_d, lakes_d = basemap_paths(pr, w, h)
    all_places = {p["id"]: p for p in data["places"]}
    links = [
        lk
        for lk in data["links"]
        if lk["kind"] in spec["kinds"] and lk["id"] not in spec.get("exclude", ())
    ]
    links_by_id = {lk["id"]: lk for lk in data["links"]}
    used = {pid for lk in links for pid in [*lk["from"], lk["to"]]}
    if "thing" in spec["kinds"]:
        used |= {pid for pid, p in all_places.items() if p["role"] == "breeding"}
    places = {pid: p for pid, p in all_places.items() if pid in used}
    col = {k: t[v] for k, v in KIND.items()}
    kinds = sorted({lk["kind"] for lk in links})

    def xy(pid):
        p = places[pid]
        return pr(p["lon"], p["lat"])

    b = [
        "<defs>",
        f'<clipPath id="frame"><rect width="{w}" height="{h}"/></clipPath>',
        f'<path id="land" d="{land_d}"/>',
        *(arrow_marker(f"head-{k}", col[k], 5) for k in kinds),
        "</defs>",
        '<g clip-path="url(#frame)">',
        f'<use href="#land" fill="{t["panel"]}"/>',
        f'<path d="{lakes_d}" fill="{t["bg"]}" stroke="{t["muted"]}" stroke-width=".4" '
        f'stroke-opacity=".5"/>',
        f'<use href="#land" fill="none" stroke="{t["muted"]}" stroke-width=".6" '
        f'stroke-opacity=".6"/>',
        "</g>",
    ]
    for lon, lat, s, size in spec["seas"]:
        x, y = pr(lon, lat)
        b.append(text(x, y, s, t["muted"], size, "middle", 400, SERIF, italic=True, halo=t["bg"]))

    lines, marks, labels = [], [], []
    for link in links:
        if not link["from"] and link["id"] not in spec["tails"]:
            continue  # ни начала, ни хвоста — подписью у точки (place_extra)
        kind, c = link["kind"], col[link["kind"]]
        x1, y1 = xy(link["to"])
        bend = spec["bend"].get(link["id"], 0.05)
        if link["from"]:
            for pid in link["from"]:
                x0, y0 = xy(pid)
                a, bb, cx, cy, z, zz = map_curve(x0, y0, x1, y1, bend)
                dash = ' stroke-dasharray="6 4"' if kind == "disproved" else ""
                lines.append(
                    f'<path d="M{a:.1f},{bb:.1f}Q{cx:.1f},{cy:.1f} {z:.1f},{zz:.1f}" fill="none" '
                    f'stroke="{c}" stroke-width="2.2" stroke-linecap="round"{dash} '
                    f'marker-end="url(#head-{kind})"/>'
                )
                if kind == "disproved":  # крест на середине линии
                    mx, my = 0.25 * a + 0.5 * cx + 0.25 * z, 0.25 * bb + 0.5 * cy + 0.25 * zz
                    for s in (1, -1):
                        lines.append(line(mx - 7, my - 7 * s, mx + 7, my + 7 * s, t["ink"], 2.4))
        else:  # начала нет: линия появляется из ничего
            for k, (lon, lat) in enumerate(spec["tails"][link["id"]]):
                x0, y0 = pr(lon, lat)
                a, bb, cx, cy, z, zz = map_curve(x0, y0, x1, y1, 0.0, 0, 9)
                gid = f"fade-{link['id']}-{k}"
                dash = ' stroke-dasharray="5 4"' if kind == "thing" else ""
                lines.append(
                    f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{a:.1f}" '
                    f'y1="{bb:.1f}" x2="{z:.1f}" y2="{zz:.1f}"><stop offset="0" stop-color="{c}" '
                    f'stop-opacity="0"/><stop offset=".55" stop-color="{c}"/></linearGradient>'
                )
                lines.append(
                    f'<path d="M{a:.1f},{bb:.1f}L{z:.1f},{zz:.1f}" fill="none" '
                    f'stroke="url(#{gid})" stroke-width="2.2" stroke-linecap="round"{dash} '
                    f'marker-end="url(#head-{kind})"/>'
                )
        lab = spec["link_labels"].get(link["id"])
        if lab:
            lon, lat, anchor, rows = lab
            d = km_text(link["distance_km"]) if link.get("distance_km") else ""
            s2 = f"{num(link['share_at_to']['pct'])}%" if "share_at_to" in link else ""
            yr = span_text(link["when"]) if link.get("when") else ""
            lx, ly = pr(lon, lat)
            for k, row in enumerate(rows):
                s1 = row.format(d=d, s=share_text(link), s2=s2, y=yr)
                labels.append(
                    text(
                        lx,
                        ly + k * 14,
                        s1,
                        t["ink"] if k == 0 else t["muted"],
                        12.5 if k == 0 else 11.5,
                        anchor,
                        600 if k == 0 else 400,
                        halo=t["bg"],
                    )
                )

    for pid, p in places.items():
        x, y = xy(pid)
        role = p["role"]
        if role == "center":
            marks.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.6" fill="{t["ink"]}" '
                f'stroke="{t["bg"]}" stroke-width="1.8"/>'
            )
        elif role == "breeding":
            marks.append(breeding_mark(x, y, t["bg"], col["thing"], p.get("probable", False)))
        elif role == "origin":
            marks.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" fill="{t["bg"]}" '
                f'stroke="{col["people"]}" stroke-width="1.8"/>'
            )
        else:  # source, region — откуда шла вещь
            c = col["disproved"] if pid == "southwest" else col["thing"]
            q = 5
            marks.append(
                f'<polygon points="{x:.1f},{y - q:.1f} {x + q:.1f},{y:.1f} {x:.1f},{y + q:.1f} '
                f'{x - q:.1f},{y:.1f}" fill="{c}" stroke="{t["bg"]}" stroke-width="1.5"/>'
            )
        if spec["place_labels"][pid] is None:
            continue
        dx, dy, anchor = spec["place_labels"][pid]
        weight = 600 if role == "center" else 400
        size = 13 if role == "center" else 12
        labels.append(text(x + dx, y + dy, p["name"], t["ink"], size, anchor, weight, halo=t["bg"]))
        link_id, extra, ex, *ey = spec["place_extra"].get(pid, (None, [], 0))
        if role == "breeding":
            extra = [row.format(w=span_text(p["when"])) for row in BREEDING_NOTE[pid]]
        y_extra = y + (ey[0] if ey else dy)
        for k, row in enumerate(extra):
            if link_id:
                row = row.format(s=share_text(links_by_id[link_id]))
            labels.append(
                text(
                    x + dx + ex,
                    y_extra + 14 * (k + 1),
                    row,
                    t["muted"],
                    11.5,
                    anchor,
                    halo=t["bg"],
                )
            )

    b += lines + marks + labels

    # легенда — в нижнем углу, в море
    rows, notes = spec["legend"], spec["notes"]
    box_h = 16 + len(rows) * 20 + len(notes) * 15 + 4
    bx = w - spec["legend_w"] - 8 if spec.get("legend_right") else 8
    lx, ly = bx + 10, h - box_h + 8
    b.append(rect(bx, ly - 16, spec["legend_w"], box_h, t["bg"], 6, 0.86))
    for k, (kind, s1) in enumerate(rows):
        yy = ly + k * 20
        if kind in ("thing", "people", "disproved"):
            dash = ' stroke-dasharray="6 4"' if kind == "disproved" else ""
            b.append(
                f'<path d="M{lx},{yy}L{lx + 26},{yy}" stroke="{col[kind]}" stroke-width="2.2"'
                f'{dash} marker-end="url(#head-{kind})"/>'
            )
            if kind == "disproved":
                b.append(line(lx + 9, yy - 5, lx + 17, yy + 5, t["ink"], 2))
                b.append(line(lx + 9, yy + 5, lx + 17, yy - 5, t["ink"], 2))
        elif kind == "tail":
            b.append(
                f'<linearGradient id="fade-key" x1="0" x2="1"><stop offset="0" '
                f'stop-color="{col["thing"]}" stop-opacity="0"/><stop offset=".55" '
                f'stop-color="{col["thing"]}"/></linearGradient>'
            )
            b.append(
                f'<rect x="{lx}" y="{yy - 1.1}" width="26" height="2.2" fill="url(#fade-key)"/>'
            )
        elif kind == "source":
            b.append(
                f'<polygon points="{lx + 13},{yy - 5} {lx + 18},{yy} {lx + 13},{yy + 5} '
                f'{lx + 8},{yy}" fill="{col["thing"]}"/>'
            )
        elif kind == "origin":
            b.append(
                f'<circle cx="{lx + 13}" cy="{yy}" r="3.6" fill="{t["bg"]}" '
                f'stroke="{col["people"]}" stroke-width="1.8"/>'
            )
        elif kind == "center":
            b.append(f'<circle cx="{lx + 13}" cy="{yy}" r="4.6" fill="{t["ink"]}"/>')
        else:
            b.append(breeding_mark(lx + 13, yy, t["bg"], col["thing"], kind == "probable"))
        b.append(text(lx + 36, yy + 4, s1, t["ink"], 12, halo=t["bg"]))
    for k, s1 in enumerate(notes):
        b.append(text(lx, ly + len(rows) * 20 + 6 + k * 15, s1, t["muted"], 11.5, halo=t["bg"]))
    b.append(
        f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" fill="none" stroke="{t["rule"]}"/>'
    )
    return svg(w, h, t, b, title, desc)


def fig_routes3(t: dict) -> str:
    links = {link["id"]: link for link in complex_data()["links"]}
    cu, ap = links["copper_superior"], links["copper_appalachia"]
    return route_map(
        t,
        THINGS_MAP,
        "Вещи в пути: Северная Америка и Мезоамерика",
        "Карта. К центрам хоупвелла в Огайо (на карте — одна точка «Маунд-Сити») идут "
        f"стрелки: медь Верхнего озера ({km_text(cu['distance_km'])} по прямой, "
        f"{num(cu['share_pct'])}% вещей семи центров; в самой Маунд-Сити меди Мичипикотена "
        f"нет), медь южных Аппалачей ({km_text(ap['distance_km'])}, {num(ap['share_pct'])}% по "
        f"семи центрам, в самой Маунд-Сити — {num(ap['share_at_to']['pct'])}%) и обсидиан "
        "Йеллоустона. К Чако (Пуэбло-Бонито) с юга — пунктиры без начала: какао и ара; "
        "отмечены Олд-Таун, где разводили ара, и Пакиме — вероятный центр разведения без "
        "прямых свидетельств. Перечёркнутая стрелка от юго-запада к Теночтитлану — связь, "
        "которую не подтвердил анализ бирюзы последнего века перед испанцами. Положение точек "
        "ориентировочное.",
    )


def fig_people(t: dict) -> str:
    links = {link["id"]: link for link in complex_data()["links"]}
    return route_map(
        t,
        PEOPLE_MAP,
        "Люди в пути: Центральная Мексика и земли майя",
        "Карта. В Теотиуакан ведут стрелки людей из Оахаки («квартал Оахаки»), с побережья "
        "Мексиканского залива («квартал торговцев»), из Мичоакана (небольшая группа) и из "
        "Чьяпаса (погребены в Теопанкаско); в районе Тлахинга около "
        f"{share_text(links['teo_tlajinga'])} погребённых — переселенцы, откуда — не сказано. "
        "Из Теотиуакана в Тикаль — стрелка вторжения, "
        f"{span_text(links['teo_tikal']['when'])}, по надписям майя. Точки районов условные.",
    )


# ── Рис. 3.5. Море: Эквадор и Западная Мексика (гипотеза Хослер, схема)

SEA_W, SEA_H = 760, 760
SEA_CENTER = (-89, 3)
SEA_FIT = [(-110, 23.5), (-68, 23.5), (-110, -18), (-68, -18)]
# Трассы плаваний — схема, а не модель: Каллахан прочитан по аннотации, его маршрутов в
# главе нет. Обе линии лишь показывают «вдоль берега» и «с уходом от берега»; на рисунке
# это написано.
SEA_NORTH = [
    (-81.7, -2.4),
    (-81.4, 1.6),
    (-80.6, 5.0),
    (-83.6, 6.6),
    (-88.0, 10.2),
    (-92.8, 13.0),
    (-97.2, 14.8),
    (-101.8, 16.6),
    (-104.9, 18.7),
]
SEA_SOUTH = [
    (-105.6, 18.9),
    (-102.8, 13.0),
    (-97.2, 7.6),
    (-90.6, 2.6),
    (-85.2, -1.6),
    (-82.3, -2.9),
]
SEA_OFFSHORE = (-96.2, 8.1)  # где на схеме подписан возможный месяц вдали от берега
# Подписи областей: (lon, lat, выравнивание, строки); {when}, {arrival} — из данных.
SEA_LABELS = {
    "west_mexico": (
        -100.2,
        20.6,
        "start",
        ["Западная Мексика", "металлургия — {arrival}", "первый период — {when_short}"],
    ),
    "first_period_source": (
        -80.4,
        13.6,
        "start",
        ["Эквадор, Колумбия,", "юг Центральной Америки:", "техника первого периода", "ближе всего"],
    ),
    "south_peru": (-76.6, -14.4, "end", ["южное Перу:", "приёмы второго периода"]),
    "andean_exchange": (
        -82.8,
        -6.0,
        "end",
        [
            "побережье Эквадора и севера Перу:",
            "«топоры-деньги», бусы из раковин",
            "и золота в дальнем обмене (Вернке);",
            "шёл ли он морем до Мексики, Вернке",
            "не пишет — эту связь проводит конспект",
        ],
    ),
}
SEA_BLUR, SEA_OPACITY = 10, 0.5


def months_text(m: dict) -> str:
    if m["high"] is None:
        return f"не меньше {num(m['low'])} месяцев"
    if m["low"] == m["high"]:
        n = num(m["low"])
        if m.get("about"):  # «около» требует родительного падежа: «около 2 месяцев»
            return f"около {n} {'месяца' if n == '1' else 'месяцев'}"
        return f"{n} месяц{'а' if n in ('2', '3', '4') else 'ев'}"
    return f"{num(m['low'])}–{num(m['high'])} месяцев"


def fig_sea(t: dict) -> str:
    sea = complex_data()["sea"]
    w, h = SEA_W, SEA_H
    pr = map_projection(SEA_CENTER, SEA_FIT, w, h)
    land_d, lakes_d = basemap_paths(pr, w, h)
    zones = {z["id"]: z for z in sea["zones"]}
    voy = {v["direction"]: v for v in sea["voyages"]}
    zone, ink, muted = t["z-n"], t["ink"], t["muted"]

    def blobs(z: dict) -> str:
        rings = [geo_circle(bl["lon"], bl["lat"], bl["radius_km"]) for bl in z["blobs"]]
        return "".join(f'<path d="{path_d([pr(*q) for q in r], True)}"/>' for r in rings)

    metal = [z for z in sea["zones"] if z["role"] != "exchange"]
    exch = [z for z in sea["zones"] if z["role"] == "exchange"]
    b = [
        "<defs>",
        f'<clipPath id="frame"><rect width="{w}" height="{h}"/></clipPath>',
        f'<path id="land" d="{land_d}"/>',
        '<filter id="soft" x="-30%" y="-30%" width="160%" height="160%">'
        f'<feGaussianBlur stdDeviation="{SEA_BLUR}"/></filter>',
        '<filter id="soft-key" x="-40%" y="-60%" width="180%" height="220%">'
        '<feGaussianBlur stdDeviation="2"/></filter>',
        hatch_defs(t, ink, "hatch-ink"),
        # штриховка без фона — поверх размытой заливки, чтобы обе области были видны
        '<pattern id="hatch-lines" width="5" height="5" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5" stroke="{ink}" '
        'stroke-width="1.6" stroke-opacity=".7"/></pattern>',
        f'<mask id="exch-mask"><g fill="#fff" filter="url(#soft)">'
        f"{''.join(blobs(z) for z in exch)}</g></mask>",
        arrow_marker("head-n", ink, 5.5),
        arrow_marker("head-s", muted, 5.5),
        "</defs>",
        '<g clip-path="url(#frame)">',
        f'<use href="#land" fill="{t["panel"]}"/>',
        f'<g opacity="{SEA_OPACITY}" fill="{zone}" filter="url(#soft)">'
        f"{''.join(blobs(z) for z in metal)}</g>",
        f'<rect width="{w}" height="{h}" fill="url(#hatch-lines)" mask="url(#exch-mask)"/>',
        f'<path d="{lakes_d}" fill="{t["bg"]}" stroke="{muted}" stroke-width=".4" '
        f'stroke-opacity=".5"/>',
        f'<use href="#land" fill="none" stroke="{muted}" stroke-width=".6" stroke-opacity=".6"/>',
        "</g>",
    ]

    def sea_name(lon, lat, s, size=14):
        x, y = pr(lon, lat)
        return text(x, y, s, muted, size, "middle", 400, SERIF, italic=True, halo=t["bg"])

    b.append(sea_name(-99.5, -5.8, "Тихий океан", 15))
    b.append(sea_name(-76.5, 15.8, "Карибское море", 13))

    def trace(pts, color, mid, dash):
        xy = smooth([pr(*p) for p in pts], 10)
        return (
            f'<path d="{path_d(xy)}" fill="none" stroke="{color}" stroke-width="2.4" '
            f'stroke-dasharray="{dash}" stroke-linecap="round" marker-end="url(#{mid})"/>'
        )

    b.append(trace(SEA_SOUTH, muted, "head-s", "2 5"))
    b.append(trace(SEA_NORTH, ink, "head-n", "7 4"))

    labels = []
    for zid, (lon, lat, anchor, rows) in SEA_LABELS.items():
        z = zones[zid]
        x, y = pr(lon, lat)
        when_short = z["when"]["label"].split("— ")[-1] if z.get("when") else ""
        for k, row in enumerate(rows):
            s1 = row.format(
                arrival=z["arrival"]["label"] if z.get("arrival") else "", when_short=when_short
            )
            labels.append(
                text(
                    x,
                    y + k * 15,
                    s1,
                    ink if k == 0 else muted,
                    13 if k == 0 else 12,
                    anchor,
                    600 if k == 0 else 400,
                    halo=t["bg"],
                )
            )
    # подписи плаваний
    nx, ny = pr(-92.6, 16.6)
    labels.append(
        text(
            nx,
            ny,
            f"на север: {months_text(voy['north']['months'])}",
            ink,
            13,
            "start",
            600,
            halo=t["bg"],
        )
    )
    labels.append(text(nx, ny + 15, "вдоль берега", muted, 12, "start", halo=t["bg"]))
    ox, oy = pr(*SEA_OFFSHORE)
    s_m = voy["south"]["months"]
    labels.append(
        text(ox, oy, f"на юг: {months_text(s_m)},", muted, 13, "start", 600, halo=t["bg"])
    )
    off = voy["south"].get("offshore_months")
    labels.append(
        text(
            ox,
            oy + 15,
            f"возможно, {'месяц' if off == 1 else f'{num(off)} мес.'} вдали от берега",
            muted,
            12,
            "start",
            halo=t["bg"],
        )
    )
    b += labels

    # крупно: что это за рисунок
    b.append(text(20, 330, "Гипотеза Хослер", ink, 22, "start", 700, halo=t["bg"]))
    b.append(text(20, 354, "Схема: путь условный", muted, 15, "start", italic=True, halo=t["bg"]))

    # легенда
    ly = 392
    rows = [
        ("zone", "металлургия по Хослер"),
        ("hatch", "дальний обмен по Вернке"),
        ("north", "плавание на север — трасса условная"),
        ("south", "плавание на юг — трасса условная"),
    ]
    for k, (kind, s1) in enumerate(rows):
        yy = ly + k * 21
        if kind == "zone":
            b.append(
                f'<ellipse cx="33" cy="{yy}" rx="13" ry="7" fill="{zone}" opacity="{SEA_OPACITY}" '
                'filter="url(#soft-key)"/>'
            )
        elif kind == "hatch":
            b.append(rect(20, yy - 7, 26, 14, "url(#hatch-ink)", 5, 0.6))
        else:
            c, mid, dash = (ink, "head-n", "7 4") if kind == "north" else (muted, "head-s", "2 5")
            b.append(
                f'<path d="M20,{yy}L44,{yy}" stroke="{c}" stroke-width="2.4" '
                f'stroke-dasharray="{dash}" marker-end="url(#{mid})"/>'
            )
        b.append(text(56, yy + 4, s1, ink, 12, halo=t["bg"]))
    b.append(
        text(
            20,
            ly + len(rows) * 21 + 4,
            "Границы областей и положение линий условные.",
            muted,
            11.5,
            halo=t["bg"],
        )
    )

    # врезка: сроки плаваний по расчёту Каллахана — туда и обратно неравноценно
    ix, iy, unit = 20, 640, 40  # px на месяц
    b.append(rect(ix - 8, iy - 34, 300, 118, t["bg"], 6, 0.9))
    b.append(
        text(ix, iy - 14, "Сколько длилось плавание (расчёт Каллахана)", ink, 12.5, "start", 600)
    )
    for k in range(7):
        x = ix + 64 + k * unit
        b.append(line(x, iy - 2, x, iy + 52, t["rule"], 0.8))
        b.append(text(x, iy + 66, str(k), muted, 11, "middle"))
    b.append(text(ix + 64 + 6.5 * unit, iy + 66, "мес.", muted, 11, "start"))
    x0 = ix + 64
    # на север: около двух — размытый конец
    n_m = voy["north"]["months"]
    b.append(text(ix, iy + 16, "на север", ink, 12))
    b.append(
        f'<linearGradient id="about-n" x1="0" x2="1"><stop offset="0" stop-color="{ink}" '
        f'stop-opacity=".75"/><stop offset=".8" stop-color="{ink}" stop-opacity=".75"/>'
        f'<stop offset="1" stop-color="{ink}" stop-opacity="0"/></linearGradient>'
    )
    b.append(rect(x0, iy + 7, (n_m["low"] + 0.4) * unit, 12, "url(#about-n)", 2))
    # на юг: не меньше пяти — полоса дальше гаснет, конца нет
    b.append(text(ix, iy + 42, "на юг", ink, 12))
    b.append(
        f'<linearGradient id="open-s" x1="0" x2="1"><stop offset="0" stop-color="{muted}" '
        f'stop-opacity=".85"/><stop offset="1" stop-color="{muted}" stop-opacity="0"/>'
        "</linearGradient>"
    )
    b.append(rect(x0, iy + 33, s_m["low"] * unit, 12, muted, 2, 0.85))
    b.append(rect(x0 + s_m["low"] * unit, iy + 33, 1.4 * unit, 12, "url(#open-s)", 0))
    b.append(
        f'<rect width="{w - 1}" height="{h - 1}" x=".5" y=".5" fill="none" stroke="{t["rule"]}"/>'
    )
    return svg(
        w,
        h,
        t,
        b,
        "Гипотеза Хослер: металлургия морем из Эквадора в Западную Мексику (схема)",
        "Схематическая карта тихоокеанского побережья от Западной Мексики до юга Перу. "
        "Размытые области: Западная Мексика — куда, по Хослер, пришла металлургия "
        f"({zones['west_mexico']['arrival']['label']}; {zones['west_mexico']['when']['label']}); "
        "Эквадор, Колумбия и юг Центральной Америки — с ними ближе всего техника первого "
        "периода; южное Перу — откуда добавились приёмы второго периода. Штриховкой — "
        "побережье Эквадора и севера Перу, где, по Вернке, «топоры-деньги» и бусы шли в "
        "дальний обмен; связь с Мексикой — вывод конспекта. Две условные линии: на север "
        f"вдоль берега — {months_text(n_m)}, на юг с уходом от берега — {months_text(s_m)}. "
        "Врезка сравнивает сроки. Трассы и границы условные.",
    )


# ── Рис. 3.7. Оценки населения крупнейших городов (оценки)

POP_FROM, POP_TO = 1_000, 1_000_000
POP_CITIES = ["Кахокия", "Теотиуакан", "Теночтитлан"]


def fig_population(t: dict) -> str:
    data = complex_data()["population"]
    w, x0, x1 = 760, 214, 728
    top, row, gap = 70, 40, 14
    by_city = {c: [e for e in data if e["place"] == c] for c in POP_CITIES}
    plot_h = sum(len(v) * row + gap for v in by_city.values())
    h = top + plot_h + 96
    ink, muted = t["ink"], t["muted"]

    def px(v: float) -> float:
        return x0 + math.log10(v / POP_FROM) / math.log10(POP_TO / POP_FROM) * (x1 - x0)

    b = [
        "<defs>",
        f'<linearGradient id="more" x1="0" x2="1"><stop offset="0" stop-color="{ink}" '
        f'stop-opacity=".5"/><stop offset="1" stop-color="{ink}" stop-opacity="0"/>'
        "</linearGradient>",
        arrow_marker("head-ink", ink, 5),
        "</defs>",
    ]
    yb = top + plot_h
    y = top
    for ci, ests in enumerate(by_city.values()):  # полосы городов — под сеткой
        block = len(ests) * row + gap
        if ci % 2 == 0:
            b.append(rect(0, y, w, block, t["band"], 0))
        y += block
    for exp in range(3, 7):
        for m in (1, 2, 5):
            v = m * 10**exp
            if v > POP_TO:
                continue
            x = px(v)
            major = m == 1
            b.append(line(x, top - 8, x, yb, t["rule"], 1.2 if major else 0.6))
            if major:
                b.append(text(x, top - 14, grouped(v), ink, 12, "middle", 500))
            else:
                b.append(text(x, yb + 15, grouped(v), muted, 10.5, "middle"))
    b.append(text(x0, top - 40, "жителей", muted, 12))
    b.append(
        text(
            x1,
            top - 40,
            "шкала логарифмическая: каждый шаг — в 10 раз больше",
            muted,
            12,
            "end",
            italic=True,
        )
    )

    y = top
    for ci, (city, ests) in enumerate(by_city.items()):
        block = len(ests) * row + gap
        halo = t["band"] if ci % 2 == 0 else t["bg"]
        b.append(text(14, y + 26, city, ink, 14.5, "start", 600))
        period = ests[0].get("period")
        for k, s1 in enumerate(split_label(period, 20) if period else []):
            b.append(text(14, y + 42 + k * 14, s1, muted, 11.5))
        for j, e in enumerate(ests):
            yc = y + gap / 2 + j * row + row - 8  # линия меток; подпись — над ней
            parts = []
            if "low" in e:
                a, z = px(e["low"]), px(e["high"])
                b.append(rect(a, yc - 4, z - a, 8, ink, 4, 0.5))
                if e.get("high_open"):
                    b.append(rect(z, yc - 4, 40, 8, "url(#more)", 0))
                    parts.append(f"{grouped(e['low'])} — более {grouped(e['high'])}")
                else:
                    parts.append(f"{grouped(e['low'])}–{grouped(e['high'])}")
            if "point" in e:
                x = px(e["point"])
                if "low" in e:  # отметка внутри диапазона
                    b.append(line(x, yc - 8, x, yc + 8, ink, 2))
                    parts.append(f"{e.get('point_label', '')} {grouped(e['point'])}".strip())
                else:
                    hollow = e.get("mentioned")
                    b.append(
                        f'<circle cx="{x:.1f}" cy="{yc:.1f}" r="5" '
                        f'fill="{halo if hollow else ink}" stroke="{ink}" stroke-width="1.6"/>'
                    )
                    parts.append(grouped(e["point"]) if hollow else f"≈{grouped(e['point'])}")
            if "alternatives" in e:  # «или»: отдельные отметки, между ними ничего не утверждается
                for v in e["alternatives"]:
                    b.append(
                        f'<circle cx="{px(v):.1f}" cy="{yc:.1f}" r="5" fill="{halo}" '
                        f'stroke="{ink}" stroke-width="1.6"/>'
                    )
                parts.append(" или ".join(grouped(v) for v in e["alternatives"]))
            if "upto" in e:
                xa, xz = px(e["point"]) + 6, px(e["upto"])
                b.append(
                    f'<path d="M{xa:.1f},{yc:.1f}L{xz:.1f},{yc:.1f}" stroke="{ink}" '
                    f'stroke-width="1.6" stroke-dasharray="2 3"/>'
                )
                b.append(line(xz, yc - 6, xz, yc + 6, ink, 1.6))
                parts.append(f"до {grouped(e['upto'])} {e['upto_label']}")
            s1 = f"{e['author']}: " + "; ".join(parts)
            if e.get("mentioned"):  # не оценка автора, а упомянутая им чужая
                s1 = f"{e.get('mention', '')} " + "; ".join(parts) + f" (по словам {e['author']})"
                s1 = s1.strip()
                if e.get("period") is None and period:
                    s1 += "; время не указано"
            if "words" in e:  # без числа — ни одной метки на шкале, только слова
                b.append(
                    text(
                        px(1200),
                        yc + 4,
                        f"{e['author']}: «{e['words']}» — без числа",
                        ink,
                        12.5,
                        italic=True,
                        halo=halo,
                    )
                )
                continue
            # подпись — над метками, от левой метки; не влезает — прижата к правому краю
            marks = [e[k] for k in ("low", "point") if k in e] + e.get("alternatives", [])
            left = px(min(marks))
            if left + len(s1) * 6.1 < w - 10:
                b.append(text(left, yc - 11, s1, ink, 12, halo=halo))
            else:
                b.append(text(w - 10, yc - 11, s1, ink, 12, "end", halo=halo))
        y += block

    # легенда
    ly = yb + 40
    items = [
        ("range", "диапазон оценки"),
        ("point", "одно число — «около»"),
        ("hollow", "оценка, которую автор только упоминает"),
        ("upto", "«до» — верхняя граница"),
    ]
    for k, (kind, s1) in enumerate(items):
        lx = 24 + (k % 2) * 372
        yy = ly + (k // 2) * 22
        if kind == "range":
            b.append(rect(lx, yy - 4, 26, 8, ink, 4, 0.5))
        elif kind == "upto":
            b.append(
                f'<path d="M{lx},{yy}L{lx + 24},{yy}" stroke="{ink}" stroke-width="1.6" '
                f'stroke-dasharray="2 3"/>'
            )
            b.append(line(lx + 24, yy - 6, lx + 24, yy + 6, ink, 1.6))
        else:
            fill = t["bg"] if kind == "hollow" else ink
            b.append(
                f'<circle cx="{lx + 13}" cy="{yy}" r="5" fill="{fill}" stroke="{ink}" '
                f'stroke-width="1.6"/>'
            )
        b.append(text(lx + 36, yy + 4.5, s1, ink, 12.5))
    b.append(
        text(
            w - 16,
            h - 10,
            "Оценки разных авторов; среднее не показано намеренно",
            muted,
            12,
            "end",
            italic=True,
        )
    )
    desc = "; ".join(
        f"{e['place']} — {e['author']}: "
        + (
            f"{grouped(e['low'])}–{grouped(e['high'])}"
            if "low" in e
            else " или ".join(grouped(v) for v in e["alternatives"])
            if "alternatives" in e
            else e.get("words") or f"≈{grouped(e['point'])}"
        )
        for e in data
    )
    return svg(
        w,
        h,
        t,
        b,
        "Сколько людей жило в крупнейших городах: оценки разных авторов",
        f"Полосы и точки на логарифмической шкале от тысячи до миллиона жителей. {desc}.",
    )


# ── Рис. 3.8. Хронология инков: хроники и радиоуглерод (данные)

INCA_FROM, INCA_TO = 1300, 1540
INCA_SOFT = 12  # px: полуширина размытого края у начала «примерно с …»
INCA_ROWS = [  # (строка в данных, подпись, подзаголовок)
    ("Мачу-Пикчу", "Мачу-Пикчу", ""),
    ("Чамикаль (Эквадор)", "Север", "Чамикаль, Эквадор"),
    ("Мендоса (Аргентина)", "Юго-восток", "Мендоса, Аргентина"),
    ("Титикака", "Титикака", "район озера"),
]


def fig_inca(t: dict) -> str:
    data = complex_data()["inca_chronology"]
    w, x0, x1 = 760, 168, 740
    top, row = 58, 84
    h = top + row * len(INCA_ROWS) + 92
    chron, model, ink, muted = t["z-n"], t["z-t"], t["ink"], t["muted"]

    def px(y: float) -> float:
        return x0 + (y - INCA_FROM) / (INCA_TO - INCA_FROM) * (x1 - x0)

    b = [
        "<defs>",
        '<filter id="blur" x="-10%" y="-80%" width="120%" height="260%">'
        '<feGaussianBlur stdDeviation="3 1"/></filter>',
        # начало без конца: размытое начало (≈) и угасание вправо; отметки-черты нет
        f'<linearGradient id="open-key" x1="0" x2="1"><stop offset="0" stop-color="{model}" '
        f'stop-opacity="0"/><stop offset=".35" stop-color="{model}" stop-opacity=".6"/>'
        f'<stop offset="1" stop-color="{model}" stop-opacity="0"/></linearGradient>',
        hatch_defs(t, ink, "hatch-ink"),
        "</defs>",
    ]
    yb = top + row * len(INCA_ROWS)
    for i in range(0, len(INCA_ROWS), 2):  # полосы строк — под сеткой
        b.append(rect(0, top + i * row, w, row, t["band"], 0))
    for yr in range(INCA_FROM, INCA_TO + 1, 20):
        x = px(yr)
        b.append(line(x, top - 6, x, yb, t["rule"], 1.0 if yr % 100 == 0 else 0.6))
        b.append(text(x, top - 12, str(yr), ink, 11.5, "middle"))
    b.append(text(x0, top - 34, "годы", muted, 11.5))

    for i, (site, name, sub) in enumerate(INCA_ROWS):
        y0 = top + i * row
        halo = t["band"] if i % 2 == 0 else t["bg"]
        yc = y0 + row / 2
        b.append(text(14, yc + (0 if sub else 5), name, ink, 14, "start", 600))
        if sub:
            b.append(text(14, yc + 16, sub, muted, 11.5))
        evs = [e for e in data if e["site"] == site]
        chron_evs = [e for e in evs if e["kind"] == "chronicle"]
        for e in evs:
            sp = e["when"]
            a = px(sp["start"])
            if e["kind"] == "model":
                ym = yc + 10
                if sp["end"] is None:
                    a0 = a - INCA_SOFT  # размытое начало: от a0 до a + INCA_SOFT
                    peak = 2 * INCA_SOFT / (x1 - a0)
                    gid = f"open-{e['id']}"
                    b.append(
                        f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
                        f'x1="{a0:.1f}" x2="{x1}"><stop offset="0" stop-color="{model}" '
                        f'stop-opacity="0"/><stop offset="{peak:.3f}" stop-color="{model}" '
                        f'stop-opacity=".6"/><stop offset="1" stop-color="{model}" '
                        'stop-opacity="0"/></linearGradient>'
                    )
                    b.append(rect(a0, ym - 5, x1 - a0, 10, f"url(#{gid})", 0))
                    s1 = f"радиоуглерод: {e['label']}"
                else:
                    z = px(sp["end"])
                    b.append(
                        f'<rect x="{a:.1f}" y="{ym - 5:.1f}" width="{z - a:.1f}" height="10" '
                        f'rx="5" fill="{model}" fill-opacity=".6" filter="url(#blur)"/>'
                    )
                    s1 = f"радиоуглерод: {e['label']} {sp['start']}–{sp['end']}"
                    if e.get("prob"):
                        s1 += f" ({num(e['prob'])}%)"
                    if e.get("duration"):
                        s1 += f"; пробыли {e['duration']['low']}–{e['duration']['high']} лет"
                b.append(text(a, ym + 21, s1, ink, 12, halo=halo))
            elif e["kind"] == "finds":
                z = px(sp["end"])
                b.append(rect(a, yc - 5, z - a, 10, "url(#hatch-ink)", 5, 0.8))
                b.append(
                    text(z + 10, yc + 4, f"{e['label']} — уже в {sp['label']}", ink, 12, halo=halo)
                )
        # хроники: ромбы и короткая полоса над линией модели; подписи — выше
        for k, e in enumerate(chron_evs):
            sp = e["when"]
            yh = yc - 12
            a = px(sp["start"])
            if sp["end"] != sp["start"]:
                z = px(sp["end"])
                b.append(rect(a, yh - 4, z - a, 8, chron, 2))
                xm = (a + z) / 2
                when = f"{sp['start']}–{sp['end']}"
            else:
                xm = a
                b.append(mark("diamond", a, yh, chron, chron, t["bg"], 4.5))
                when = str(sp["start"])
            s1 = f"хроники: {e['label']}, {when}"
            anchor = "start" if k else ("end" if len(chron_evs) > 1 else "start")
            dx = 8 if anchor == "start" else -8
            b.append(text(xm + dx, yh - 10, s1, ink, 12, anchor, halo=halo))

    ly = yb + 34
    items = [
        ("chron", "дата по хроникам (полоска — промежуток)"),
        ("model", "интервал по радиоуглероду — модель авторов"),
        ("open", "начало по радиоуглероду (≈), конец не указан"),
        ("finds", "находки — век по выводу авторов"),
    ]
    for k, (kind, s1) in enumerate(items):
        lx = 24 + (k % 2) * 372
        yy = ly + (k // 2) * 22
        if kind == "chron":
            b.append(mark("diamond", lx + 13, yy, chron, chron, t["bg"], 4.5))
        elif kind == "model":
            b.append(
                f'<rect x="{lx}" y="{yy - 5}" width="26" height="10" rx="5" fill="{model}" '
                'fill-opacity=".6" filter="url(#blur)"/>'
            )
        elif kind == "open":
            b.append(rect(lx, yy - 5, 26, 10, "url(#open-key)", 0))
        else:
            b.append(rect(lx, yy - 5, 26, 10, "url(#hatch-ink)", 5, 0.8))
        b.append(text(lx + 36, yy + 4.5, s1, ink, 12.5))
    b.append(
        text(
            w - 16,
            h - 10,
            "Все даты приблизительные; размытый край — неточная граница",
            muted,
            12,
            "end",
            italic=True,
        )
    )
    kinds = {"chronicle": "хроники", "model": "радиоуглерод", "finds": "находки"}

    def when(sp: dict) -> str:
        if sp.get("label"):
            return sp["label"]
        if sp["end"] is None:
            return f"с {sp['start']}"
        return str(sp["start"]) if sp["end"] == sp["start"] else f"{sp['start']}–{sp['end']}"

    desc = "; ".join(
        f"{e['site']} — {kinds[e['kind']]}: {e['label']}, {when(e['when'])}" for e in data
    )
    return svg(
        w,
        h,
        t,
        b,
        "Хронология инков: даты хроник и радиоуглерода",
        f"Шкала от 1300 до 1540 г. {desc}.",
    )


# ── Глава 4. Общее: данные, граница, пятна областей

TRANSITION = ROOT / "data" / "transition.json"
BORDERS = ROOT / "visuals" / "shared" / "borders-50m.geojson"

# Цвета главы 4. Пары проверены validate_palette.js навыка dataviz для обеих тем:
# --z-m / --z-t (Мезоамерика и Оазисамерика, Мезоамерика и колонии на рис. 4.7) — на фоне
# суши --panel; --z-n / --z-t (война и мир на рис. 4.10, развалины и документы на рис. 4.8) —
# на фоне --bg; та же пара --z-n / --z-t на фоне суши --panel — отступление испанцев и уход
# пуэбло на рис. 4.9, полоса Гадсдена и земли оодхам на рис. 4.12 (проверено отдельно, обе
# темы). Третьего цвета для Аридоамерики нет: пара --z-n / --z-m проваливает проверку
# различимости при дальтонизме, поэтому Аридоамерика — нейтральная точечная фактура.


def transition() -> dict:
    return json.loads(TRANSITION.read_text(encoding="utf-8"))


def border_d(pr, pair: tuple[str, str]) -> str:
    """Нынешняя граница двух стран (коды ISO A3) из visuals/shared/borders-50m.geojson."""
    fc = json.loads(BORDERS.read_text(encoding="utf-8"))
    out = []
    for f in fc["features"]:
        if f["properties"]["between"] != sorted(pair):
            continue
        g = f["geometry"]
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        out += [path_d([pr(lon, lat) for lon, lat in part]) for part in parts]
    return "".join(out)


def blobs_d(pr, blobs) -> str:
    """Пятна {lon, lat, radius_km} — кругами на сфере, для размытой заливки или маски."""
    rings = [geo_circle(b["lon"], b["lat"], b["radius_km"]) for b in blobs]
    return "".join(f'<path d="{path_d([pr(*q) for q in r], True)}"/>' for r in rings)


# Мезоамерика к югу от края Кирхгофа: край — опорные точки из data/transition.json, а
# замыкание с юга (через море и Центральную Америку) — схема; суша обрезает его по берегу.
MESO_SOUTH = [
    (-96.4, 22.9),
    (-93.0, 17.6),
    (-88.0, 13.4),
    (-93.5, 11.5),
    (-105.6, 16.6),
    (-108.9, 22.6),  # восточнее мыса Нижней Калифорнии: полуостров в Мезоамерику не входит
]
MESO_BLUR = 9


def meso_d(pr, tr: dict) -> str:
    places = {p["id"]: p for p in tr["places"]}
    meso = next(a for a in tr["areas"] if a["kind"] == "meso")
    edge = [(places[pid]["lon"], places[pid]["lat"]) for pid in meso["edge"]]
    return path_d([pr(*q) for q in [*edge, *MESO_SOUTH]], close=True)


def place_mark(kind: str, x: float, y: float, t: dict) -> str:
    """Знаки карт главы 4: landmark — ориентир, mine — рудник, colony — колония,
    origin — откуда шли переселенцы, edge — опорная точка края Мезоамерики."""
    if kind == "mine":
        return rect(
            x - 4.4, y - 4.4, 8.8, 8.8, t["ink"], 1, extra=f' stroke="{t["bg"]}" stroke-width="1.6"'
        )
    if kind == "colony":
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{t["z-t"]}" stroke="{t["bg"]}" '
            'stroke-width="1.8"/>'
        )
    if kind == "origin":
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{t["bg"]}" stroke="{t["z-t"]}" '
            'stroke-width="2.2"/>'
        )
    if kind == "edge":
        return (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{t["panel"]}" stroke="{t["ink"]}" '
            'stroke-width="1.4"/>'
        )
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{t["ink"]}" stroke="{t["bg"]}" '
        'stroke-width="1.6"/>'
    )


def map_base(t: dict, w: int, h: int, pr, extra_defs: list[str]) -> list[str]:
    """Начало карты главы 4: рамка, суша, фильтры размытия; заливки — до озёр и берега."""
    land_d, _ = basemap_paths(pr, w, h)
    return [
        "<defs>",
        f'<clipPath id="frame"><rect width="{w}" height="{h}"/></clipPath>',
        f'<clipPath id="landclip"><path d="{land_d}"/></clipPath>',
        f'<path id="land" d="{land_d}"/>',
        '<filter id="soft" x="-30%" y="-30%" width="160%" height="160%">'
        f'<feGaussianBlur stdDeviation="{MESO_BLUR}"/></filter>',
        '<filter id="soft-key" x="-40%" y="-60%" width="180%" height="220%">'
        '<feGaussianBlur stdDeviation="2"/></filter>',
        *extra_defs,
        "</defs>",
        '<g clip-path="url(#frame)">',
        f'<use href="#land" fill="{t["panel"]}"/>',
    ]


def map_coast(t: dict, pr, w: int, h: int) -> list[str]:
    _, lakes_d = basemap_paths(pr, w, h)
    return [
        f'<path d="{lakes_d}" fill="{t["bg"]}" stroke="{t["muted"]}" stroke-width=".4" '
        'stroke-opacity=".5"/>',
        f'<use href="#land" fill="none" stroke="{t["muted"]}" stroke-width=".6" '
        'stroke-opacity=".6"/>',
        "</g>",
    ]


def sea_label(pr, lon, lat, s, t, size=13) -> str:
    x, y = pr(lon, lat)
    return text(x, y, s, t["muted"], size, "middle", 400, SERIF, italic=True, halo=t["bg"])


def day_text(sp: dict) -> str:
    """«21 августа 1591 г.», «1591 г.», «≈1546 г.», «1785–1787 гг.»."""
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    if sp.get("day"):
        y, m, d = sp["day"].split("-")
        return f"{int(d)} {months[int(m) - 1]} {y} г."
    if sp.get("label", "").startswith("около"):
        return f"≈{sp['start']} г."
    if sp["end"] is not None and sp["end"] != sp["start"]:
        return f"{sp['start']}–{sp['end']} гг."
    return f"{sp['start']} г."


# ── Рис. 4.1. Понятия Кирхгофа и нынешняя граница (схема)

ZONES4_W, ZONES4_H = 760, 860
ZONES4_CENTER = (-107.5, 29.5)
ZONES4_FIT = [(-122.4, 42.2), (-93.0, 42.2), (-122.4, 17.0), (-93.0, 17.0)]
# Подписи областей: (lon, lat, вторая строка); Аридоамерика подписана дважды — по обе
# стороны границы, чтобы было видно, что граница её разрезает.
ZONES4_AREA_LABELS = {
    "aridoamerica": [(-116.4, 40.6, "собиратели и охотники"), (-103.6, 27.7, None)],
    "oasisamerica": [(-110.6, 35.0, "земледельцы «оазисов»")],
    "mesoamerica": [(-102.6, 18.6, "ко времени завоевания")],
}
ZONES4_PLACES = {  # id: (откуда: transition или complex, подпись, dx, dy, выравнивание)
    "mexico_city": ("transition", "Мехико", 8, 14, "start"),
    "paquime": ("complex", "Пакиме", -8, 4, "end"),
    "casa_grande": ("transition", "Каса-Гранде", -8, -7, "end"),
    "mesa_verde": ("transition", "Меса-Верде", -8, -6, "end"),
    "chaco": ("complex", "Чако", 8, 4, "start"),
    "santa_fe": ("transition", "Санта-Фе", 8, 4, "start"),
}
ZONES4_EDGE_LABELS = {
    "sinaloa_mouth": (-8, -6, "end"),
    "lerma": (0, 16, "middle"),
    "panuco_mouth": (8, -6, "start"),
}
# Подпись границы — вдоль нижнего течения Рио-Гранде, между двумя точками (lon, lat);
# сдвиг — в пикселях поперёк линии, на сторону США.
ZONES4_BORDER_LABEL = ((-102.2, 29.9), (-99.0, 27.3), -9)


def fig_zones(t: dict) -> str:
    tr = transition()
    w, h = ZONES4_W, ZONES4_H
    pr = map_projection(ZONES4_CENTER, ZONES4_FIT, w, h)
    areas = {a["kind"]: a for a in tr["areas"]}
    meso_c, oasis_c, ink, muted = t["z-m"], t["z-t"], t["ink"], t["muted"]
    arid_mask = (
        '<mask id="arid-mask">'
        f'<g fill="#fff" filter="url(#soft)">{blobs_d(pr, areas["arid"]["blobs"])}</g>'
        f'<g fill="#000" filter="url(#soft)">{blobs_d(pr, areas["oasis"]["blobs"])}'
        f'<path d="{meso_d(pr, tr)}"/></g></mask>'
    )
    dots = (
        '<pattern id="dots" width="7" height="7" patternUnits="userSpaceOnUse">'
        f'<circle cx="3.5" cy="3.5" r="1.25" fill="{muted}"/></pattern>'
    )
    b = map_base(t, w, h, pr, [arid_mask, dots])
    b += [
        '<g clip-path="url(#landclip)">',
        f'<rect width="{w}" height="{h}" fill="{muted}" fill-opacity=".14" '
        'mask="url(#arid-mask)"/>',
        f'<rect width="{w}" height="{h}" fill="url(#dots)" mask="url(#arid-mask)"/>',
        f'<g fill="{oasis_c}" opacity=".5" filter="url(#soft)">'
        f"{blobs_d(pr, areas['oasis']['blobs'])}</g>",
        f'<path d="{meso_d(pr, tr)}" fill="{meso_c}" opacity=".55" filter="url(#soft)"/>',
        "</g>",
    ]
    b += map_coast(t, pr, w, h)
    b.append(
        f'<path d="{border_d(pr, ("MEX", "USA"))}" fill="none" stroke="{ink}" '
        'stroke-width="1.5" stroke-linejoin="round"/>'
    )
    b.append(sea_label(pr, -119.2, 29.0, "Тихий океан", t, 15))
    b.append(sea_label(pr, -94.6, 24.4, "Мексиканский", t, 13))
    b.append(sea_label(pr, -94.6, 23.7, "залив", t, 13))

    # области: крупная подпись и пояснение
    for kind, aid in (("arid", "aridoamerica"), ("oasis", "oasisamerica"), ("meso", "mesoamerica")):
        for lon, lat, sub in ZONES4_AREA_LABELS[aid]:
            x, y = pr(lon, lat)
            b.append(text(x, y, areas[kind]["name"], ink, 18, "middle", 600, SERIF, True, t["bg"]))
            if sub:
                b.append(text(x, y + 17, sub, muted, 12.5, "middle", halo=t["bg"]))

    # граница — подпись вдоль линии
    (ax, ay), (zx, zy) = (pr(*q) for q in ZONES4_BORDER_LABEL[:2])
    rot = math.degrees(math.atan2(zy - ay, zx - ax))
    bx, by = (ax + zx) / 2, (ay + zy) / 2
    b.append(
        f'<g transform="translate({bx:.1f},{by:.1f}) rotate({rot:.1f})">'
        + text(
            0,
            ZONES4_BORDER_LABEL[2],
            "граница США и Мексики сегодня",
            ink,
            12,
            "middle",
            600,
            halo=t["bg"],
        )
        + "</g>"
    )

    # край Мезоамерики: опорные точки Кирхгофа
    places = {p["id"]: p for p in tr["places"]}
    for pid, (dx, dy, anchor) in ZONES4_EDGE_LABELS.items():
        p = places[pid]
        x, y = pr(p["lon"], p["lat"])
        b.append(place_mark("edge", x, y, t))
        b.append(text(x + dx, y + dy, p["name"], ink, 11.5, anchor, italic=True, halo=t["bg"]))

    # ориентиры
    cplaces = {p["id"]: p for p in complex_data()["places"]}
    for pid, (src, name, dx, dy, anchor) in ZONES4_PLACES.items():
        p = places[pid] if src == "transition" else cplaces[pid]
        x, y = pr(p["lon"], p["lat"])
        b.append(place_mark("landmark", x, y, t))
        b.append(text(x + dx, y + dy, name, ink, 12.5, anchor, 500, halo=t["bg"]))

    # крупно: что это за рисунок; легенда — в океане
    lx, ly = 22, h - 232
    b.append(text(lx, ly, "Схема: границы областей", ink, 21, "start", 700, halo=t["bg"]))
    b.append(text(lx, ly + 25, "условные", ink, 21, "start", 700, halo=t["bg"]))
    rows = [
        ("meso", "Мезоамерика — по Кирхгофу (1943)"),
        ("oasis", "Оазисамерика"),
        ("arid", "Аридоамерика"),
        ("edge", "край Мезоамерики: Пануко — Лерма — Синалоа"),
        ("border", "нынешняя граница США и Мексики"),
        ("landmark", "ориентир"),
    ]
    y0 = ly + 56
    for k, (kind, s1) in enumerate(rows):
        yy = y0 + k * 21
        if kind == "meso":
            b.append(
                f'<ellipse cx="35" cy="{yy}" rx="13" ry="7" fill="{meso_c}" opacity=".55" '
                'filter="url(#soft-key)"/>'
            )
        elif kind == "oasis":
            b.append(
                f'<ellipse cx="35" cy="{yy}" rx="13" ry="7" fill="{oasis_c}" opacity=".5" '
                'filter="url(#soft-key)"/>'
            )
        elif kind == "arid":
            b.append(rect(22, yy - 7, 26, 14, muted, 6, 0.14))
            b.append(rect(22, yy - 7, 26, 14, "url(#dots)", 6))
        elif kind == "edge":
            b.append(place_mark("edge", 35, yy, t))
        elif kind == "border":
            b.append(line(22, yy, 48, yy, ink, 1.5))
        else:
            b.append(place_mark("landmark", 35, yy, t))
        b.append(text(58, yy + 4, s1, ink, 12, halo=t["bg"]))
    notes = [
        "Названия Аридо- и Оазисамерики — Кирхгоф, 1954.",
        "Положение точек ориентировочное.",
    ]
    for k, s1 in enumerate(notes):
        b.append(text(lx, y0 + len(rows) * 21 + 4 + k * 15, s1, muted, 11.5, halo=t["bg"]))
    b.append(
        f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" fill="none" stroke="{t["rule"]}"/>'
    )
    return svg(
        w,
        h,
        t,
        b,
        "Понятия Кирхгофа и нынешняя граница США и Мексики (схема)",
        "Схематическая карта Мексики и юго-запада США. Размытым пятном на юге — Мезоамерика ко "
        "времени завоевания; её северный край проходит размытой полосой от устья реки Пануко "
        "через Лерму к устью реки Синалоа. Севернее — Аридоамерика (точечная фактура: земли "
        "собирателей и охотников, от севера Мексики до Большого Бассейна) и Оазисамерика "
        "(земледельцы юго-запада США и северо-запада Мексики). Тонкая линия — нынешняя граница "
        "США и Мексики, она проходит поперёк обеих областей. Ориентиры: Мехико, Пакиме, "
        "Каса-Гранде, Меса-Верде, Чако, Санта-Фе. Границы областей условные, положение точек "
        "ориентировочное.",
    )


# ── Рис. 4.2. Как работает и как ломается самотёчный канал (схема)

# Числа на рисунке — из текста главы (сноска nelson2010): больше 500 км каналов, до 650 км²
# полей, распад сети около 1070 г., паводки и маловодье 1356–1384 гг. Профили условные.
CANAL_PANELS = [
    {
        "title": "Канал работает",
        "ground": 0,  # насколько врезалось русло, px
        "water": 106,  # уровень воды, y в панели
        "notes": ["река стоит выше дна канала —", "вода сама идёт к полям"],
        "muted": [],
    },
    {
        "title": "Река ниже водозабора",
        "ground": 30,
        "water": 160,
        "notes": ["русло врезалось или выше по реке", "воду забрали новые каналы —"],
        "muted": ["так объясняют распад ≈1070 г.;", "что из этого верно, спорят"],
    },
    {
        "title": "Паводок выше берегов",
        "ground": 0,
        "water": 70,
        "notes": ["1356–1384 гг.: очень высокие паводки", "чередовались с маловодьем —"],
        "muted": ["могли разрушать водозаборы"],
    },
]


def fig_canals(t: dict) -> str:
    w, h = 760, 420
    pw, ph, gap, x00, y00 = 236, 196, 14, 16, 86
    ink, muted, water = t["ink"], t["muted"], t["z-t"]
    gy, bed, cb = 96, 150, 124  # поверхность земли, дно русла, дно канала (y в панели)
    rx0, rx1, sl = 18, 112, 14  # берега русла (водозабор — на правом) и откос
    b = [
        text(
            16,
            30,
            "Самотёчный канал: вода идёт в него, только пока река стоит выше его дна",
            ink,
            17,
            "start",
            700,
        ),
        text(
            16,
            52,
            "Каналы хохокам на Солт-Ривер — больше 500 км; ими поливали, возможно, до "
            "650 км² полей",
            muted,
            12.5,
        ),
    ]
    for k, pn in enumerate(CANAL_PANELS):
        ox = x00 + k * (pw + gap)

        def P(pts, ox=ox):
            return [(ox + x, y00 + y) for x, y in pts]

        b.append(rect(ox, y00, pw, ph, t["panel"], 4, 1, f' stroke="{t["rule"]}"'))
        b.append(text(ox + 10, y00 + 22, f"{k + 1}. {pn['title']}", ink, 13.5, "start", 700))
        bd = bed + pn["ground"]
        # грунт: берега и русло; справа от русла — канава канала: мы смотрим вдоль неё,
        # дальняя стенка канавы — светлее
        ground = [
            (0, gy),
            (rx0, gy),
            (rx0 + sl, bd),
            (rx1 - sl, bd),
            (rx1, cb),
            (pw, cb),
            (pw, ph),
            (0, ph),
        ]
        b.append(polygon(P(ground), muted, 0.32))
        b.append(polygon(P([(rx1, gy), (pw, gy), (pw, cb), (rx1, cb)]), muted, 0.12))
        b.append(
            polyline(
                P([(0, gy), (rx0, gy), (rx0 + sl, bd), (rx1 - sl, bd), (rx1, cb), (pw, cb)]),
                muted,
                1.2,
            )
        )
        b.append(polyline(P([(rx1, gy), (pw, gy)]), muted, 0.8))
        if pn["ground"]:  # прежнее дно — пунктиром
            (xa, ya), (xz, _) = P([(rx0 + sl * 0.6, bed), (rx1 - sl * 0.6, bed)])
            b.append(line(xa, ya, xz, ya, ink, 1.1, "3 3"))
        wl = pn["water"]
        if wl < gy:  # паводок: вода выше берегов
            wpoly = [
                (0, wl),
                (pw, wl),
                (pw, cb),
                (rx1, cb),
                (rx1 - sl, bd),
                (rx0 + sl, bd),
                (rx0, gy),
                (0, gy),
            ]
        else:
            f = (wl - gy) / (bd - gy)
            wpoly = [(rx0 + sl * f, wl), (rx1 - sl * f, wl), (rx1 - sl, bd), (rx0 + sl, bd)]
            if wl < cb:  # вода заходит в канал
                wpoly = [
                    (rx0 + sl * f, wl),
                    (pw, wl),
                    (pw, cb),
                    (rx1, cb),
                    (rx1 - sl, bd),
                    (rx0 + sl, bd),
                ]
        b.append(polygon(P(wpoly), water, 0.55))
        xs = [x for x, _ in wpoly]
        (xa, ya), (xz, _) = P([(min(xs), wl), (max(xs), wl)])
        b.append(line(xa, ya, xz, ya, water, 1.6))
        b.append(
            text(
                ox + (rx0 + rx1) / 2,
                y00 + bd - 8,
                "река",
                ink,
                11.5,
                "middle",
                italic=True,
                halo=t["panel"],
            )
        )
        if k == 0:
            (xa, ya), (xz, _) = P([(rx1 + 12, cb - 7), (pw - 12, cb - 7)])
            b.append(
                f'<path d="M{xa:.1f},{ya:.1f}L{xz:.1f},{ya:.1f}" stroke="{ink}" '
                'stroke-width="1.4" marker-end="url(#head-ink)"/>'
            )
            b.append(
                text(
                    ox + pw - 10, y00 + gy - 8, "канал — к полям", ink, 11.5, "end", halo=t["panel"]
                )
            )
            b.append(text(ox + rx1 + 4, y00 + cb + 16, "водозабор", muted, 11, halo=t["panel"]))
        if k == 1:
            b.append(
                text(ox + pw - 10, y00 + gy - 8, "канал сухой", ink, 11.5, "end", halo=t["panel"])
            )
            b.append(text(ox + rx1 + 4, y00 + cb + 16, "водозабор", muted, 11, halo=t["panel"]))
            b.append(text(ox + rx0 + 2, y00 + bed - 6, "прежнее дно", ink, 10.5, halo=t["panel"]))
        if k == 2:  # водозабор размыт: зубчатый край
            jag = [(rx1 - 2, gy + 2), (rx1 + 8, gy + 9), (rx1 + 1, gy + 16), (rx1 + 10, cb - 2)]
            b.append(polyline(P(jag), ink, 1.6))
            b.append(
                text(
                    ox + rx1 + 18,
                    y00 + gy + 18,
                    "водозабор",
                    ink,
                    11.5,
                    "start",
                    600,
                    halo=t["panel"],
                )
            )
            b.append(
                text(
                    ox + rx1 + 18, y00 + gy + 32, "размыт", ink, 11.5, "start", 600, halo=t["panel"]
                )
            )
        # пояснения под панелью
        for j, s1 in enumerate(pn["notes"]):
            b.append(text(ox + 2, y00 + ph + 24 + j * 16, s1, ink, 12))
        for j, s1 in enumerate(pn["muted"]):
            b.append(text(ox + 2, y00 + ph + 24 + (len(pn["notes"]) + j) * 16, s1, muted, 12))
    b.insert(0, f"<defs>{arrow_marker('head-ink', ink, 5)}</defs>")
    b.append(text(16, h - 30, "Схема: профили условные, без масштаба.", ink, 14, "start", 700))
    b.append(
        text(
            16,
            h - 12,
            "Показаны только объяснения, связанные с водой; третье — беспорядки на северной "
            "окраине — схема не показывает.",
            muted,
            12,
        )
    )
    return svg(
        w,
        h,
        t,
        b,
        "Как работает и как ломается самотёчный канал (схема)",
        "Три условных поперечных профиля реки с каналом, отходящим от правого берега. 1 — канал "
        "работает: уровень реки выше дна канала, вода сама идёт к полям. 2 — река ниже "
        "водозабора: русло врезалось или выше по реке воду забрали новые каналы, канал сухой; "
        "так объясняют распад сети около 1070 г., что верно — спорят. 3 — паводок выше берегов: "
        "в 1356–1384 гг. очень высокие паводки чередовались с маловодьем и могли разрушать "
        "водозаборы. Каналы хохокам на Солт-Ривер — больше 500 км, поливали, возможно, до "
        "650 км² полей.",
    )


# ── Рис. 4.5. Население центральной части Меса-Верде и «Великая засуха» (данные)

MV_FROM, MV_TO, MV_MAX = 600, 1300, 36000
MV_ZERO_AFTER = 6  # лет: «через несколько лет после 1280 г.» — схематичный спуск к нулю


def fig_mesaverde(t: dict) -> str:
    mv = transition()["mesaverde"]
    w, h = 760, 500
    x0, x1, top, yb = 84, 736, 70, 380
    ink, muted, dry = t["ink"], t["muted"], t["z-n"]

    def px(yr: float) -> float:
        return x0 + (yr - MV_FROM) / (MV_TO - MV_FROM) * (x1 - x0)

    def py(v: float) -> float:
        return yb - v / MV_MAX * (yb - top)

    dr = mv["drought"]["when"]
    b = [
        "<defs>",
        '<pattern id="dry" width="5" height="5" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="5" stroke="{dry}" '
        'stroke-width="1.8"/></pattern>',
        "</defs>",
    ]
    for v in range(0, MV_MAX + 1, 5000):
        y = py(v)
        b.append(line(x0, y, x1, y, t["rule"], 1.0 if v == 0 else 0.6))
        b.append(text(x0 - 8, y + 4, grouped(v), muted, 11.5, "end"))
    for yr in range(MV_FROM, MV_TO + 1, 100):
        b.append(line(px(yr), yb, px(yr), yb + 5, muted, 1))
        b.append(text(px(yr), yb + 19, f"{yr}", ink, 12, "middle"))
    b.append(text(x0 - 8, top - 22, "жителей одновременно, в среднем за период", muted, 12))

    # засуха — штриховка во всю высоту
    b.append(
        rect(px(dr["start"]), top, px(dr["end"]) - px(dr["start"]), yb - top, "url(#dry)", 0, 0.75)
    )

    # полоса интервала и ступенчатая линия
    periods = mv["periods"]
    for per in periods:
        a, z = px(per["when"]["start"]), px(per["when"]["end"])
        lo = max(per["population"] - per["ci80"], 0)
        hi = per["population"] + per["ci80"]
        b.append(rect(a, py(hi), z - a, py(lo) - py(hi), muted, 0, 0.3))
    pts = []
    for per in periods:
        y = py(per["population"])
        pts += [(px(per["when"]["start"]), y), (px(per["when"]["end"]), y)]
    b.append(polyline(pts, ink, 2.4))
    last = periods[-1]
    xe, ye = px(last["when"]["end"]), py(last["population"])
    xz = px(last["when"]["end"] + MV_ZERO_AFTER)
    b.append(
        f'<path d="M{xe:.1f},{ye:.1f}L{xz:.1f},{py(0):.1f}" stroke="{ink}" stroke-width="2.4" '
        'stroke-dasharray="4 3" fill="none"/>'
    )
    b.append(line(xz, py(0), x1, py(0), ink, 2.4))

    # подписи
    peak = max(periods, key=lambda p: p["population"])

    def when(p):
        return f"{p['when']['start']}–{p['when']['end']} гг."

    xp = px(peak["when"]["start"]) - 10
    b.append(
        text(
            xp,
            py(peak["population"]) - 6,
            f"{when(peak)}: {grouped(peak['population'])}",
            ink,
            12.5,
            "end",
            600,
            halo=t["bg"],
        )
    )
    # последний период — под его полосой, выноской вверх: слева ступени почти того же уровня
    xl = (px(last["when"]["start"]) + px(last["when"]["end"])) / 2
    y_lo = py(last["population"] - last["ci80"])
    y_lab = py(9000)
    b.append(line(xl, y_lo + 2, xl, y_lab - 14, muted, 0.8))
    b.append(
        text(
            xl + 4,
            y_lab,
            f"{when(last)}: {grouped(last['population'])}",
            ink,
            12.5,
            "end",
            600,
            halo=t["bg"],
        )
    )
    b.append(
        text(xl + 4, y_lab + 15, "население падает ещё до засухи", muted, 12, "end", halo=t["bg"])
    )
    after = mv["after"]
    b.append(
        text(
            x1 - 6,
            py(0) - 10,
            f"{after['when']['label']} — {after['label']}",
            ink,
            12,
            "end",
            halo=t["bg"],
        )
    )
    b.append(
        text(
            x1,
            top - 22,
            f"{mv['drought']['name']} {dr['start']}–{dr['end']} гг.",
            dry,
            12.5,
            "end",
            600,
        )
    )
    b.append(text(x1, top - 8, "по годичным кольцам", muted, 11.5, "end"))

    # легенда
    ly = yb + 50
    items = [
        ("line", "среднее за период — сумма жителей общинных центров и малых поселений"),
        ("band", "неформальный 80-процентный интервал авторов"),
        ("dry", "самая тяжёлая часть засухи"),
    ]
    for k, (kind, s1) in enumerate(items):
        yy = ly + k * 20
        if kind == "line":
            b.append(line(24, yy, 50, yy, ink, 2.4))
        elif kind == "band":
            b.append(rect(24, yy - 6, 26, 12, muted, 0, 0.3))
        else:
            b.append(rect(24, yy - 6, 26, 12, "url(#dry)", 0, 0.75))
        b.append(text(60, yy + 4.5, s1, ink, 12.5))
    b.append(text(w - 16, h - 10, "Даты периодов приблизительные", muted, 12, "end", italic=True))
    desc = "; ".join(
        f"{p['when']['start']}–{p['when']['end']}: "
        f"{grouped(p['population'])} ± {grouped(p['ci80'])}"
        for p in periods
    )
    return svg(
        w,
        h,
        t,
        b,
        "Население центральной части Меса-Верде, 600–1280 гг., и «Великая засуха»",
        "Ступенчатый график: по горизонтали годы 600–1300, по вертикали — среднее число жителей "
        f"одновременно. По периодам (жителей ± 80-процентный интервал): {desc}. Через несколько "
        f"лет после 1280 г. — никого. Штриховкой — «Великая засуха» {dr['start']}–{dr['end']} гг.: "
        "она начинается, когда население уже падает.",
    )


# ── Карты главы 4: общие помощники для рис. 4.6, 4.9 и 4.12


def river_d(pr, tr: dict, rid: str) -> str:
    r = next(r for r in tr["rivers"] if r["id"] == rid)
    return path_d([pr(lon, lat) for lon, lat in r["coords"]])


def rivers_layer(t: dict, pr, tr: dict, ids) -> list[str]:
    return [
        f'<path d="{river_d(pr, tr, rid)}" fill="none" stroke="{t["z-t"]}" stroke-width="1.3" '
        'stroke-opacity=".55" stroke-linejoin="round"/>'
        for rid in ids
    ]


def region_blob(pr, p: dict, color: str, opacity: float = 0.45) -> str:
    """Условная область — размытое пятно радиуса radius_km."""
    ring = geo_circle(p["lon"], p["lat"], p["radius_km"])
    return (
        f'<path d="{path_d([pr(*q) for q in ring], True)}" fill="{color}" opacity="{opacity}" '
        'filter="url(#soft)"/>'
    )


def move_path(x0, y0, x1, y1, bend, color, width, dash, marker, trim0=9.0, trim1=11.0) -> str:
    a, bb, cx, cy, z, zz = map_curve(x0, y0, x1, y1, bend, trim0, trim1)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="M{a:.1f},{bb:.1f}Q{cx:.1f},{cy:.1f} {z:.1f},{zz:.1f}" fill="none" '
        f'stroke="{color}" stroke-width="{width}"{d} stroke-linecap="round" '
        f'marker-end="url(#{marker})"/>'
    )


def label_lines(x, y, rows, t, anchor="start", size=12.5, lh=15) -> list[str]:
    """rows — [(строка, цвет, жирность)]; первая — на y, остальные ниже."""
    return [
        text(x, y + k * lh, s1, c, size if k == 0 else size - 1, anchor, wt, halo=t["bg"])
        for k, (s1, c, wt) in enumerate(rows)
    ]


def scale_bar(pr, x, y, kms, t, lon=-108.0, lat=34.0) -> list[str]:
    """Масштабная линейка: штрихи на расстояниях kms (км) от начала."""
    x0, y0 = pr(lon, lat)
    x1, y1 = pr(lon, lat + 1)
    px_km = math.hypot(x1 - x0, y1 - y0) / 111.2
    out = [line(x, y, x + kms[-1] * px_km, y, t["ink"], 1.6)]
    for km in [0, *kms]:
        xx = x + km * px_km
        out.append(line(xx, y - 4, xx, y + 4, t["ink"], 1.4))
        out.append(text(xx, y + 17, f"{km} км" if km else "0", t["ink"], 11.5, "middle"))
    return out


# ── Рис. 4.6. Дальние переселения конца XIII в. (схема по тексту главы)

MIG_W, MIG_MAP_H, MIG_KEY_H = 760, 620, 104
MIG_CENTER = (-108.8, 35.0)
MIG_FIT = [(-113.6, 38.1), (-104.4, 38.1), (-113.6, 32.0), (-104.4, 32.0)]
MIG_BEND = {"mesa_verde_exodus": -0.12, "kayenta_south": -0.12}
MIG_LANDMARKS = {  # id: (откуда, dx, dy, выравнивание)
    "santa_fe": ("transition", 8, 14, "start"),
    "casa_grande": ("transition", 8, 14, "start"),
    "chaco": ("complex", 8, 4, "start"),
}
# Подписи областей: id: (dx, dy от центра пятна, выравнивание, строки — первая жирная)
MIG_TEXT = {
    "mesa_verde": (
        -10,
        -8,
        "end",
        ["Меса-Верде", "уход начался до 1260 г.,", "к 1285 г. — никого"],
    ),
    "kayenta": (0, -4, "middle", ["район Каента"]),
    "rio_grande_north": (
        None,  # по правому краю карты
        74,
        "end",
        [
            "север долины Рио-Гранде",
            "сюда ушло большинство жителей",
            "Меса-Верде: условия для земледелия",
            "без полива здесь были лучше;",
            "плато Пахарито — убежище в засуху",
        ],
    ),
    "central_arizona": (
        -16,
        96,
        "start",
        [
            "центральная Аризона",
            "1280-е гг.: здесь начали делать",
            "посуду саладо — по осторожной",
            "формулировке авторов, те, кого",
            "считают этими переселенцами",
        ],
    ),
}


def fig_migrations(t: dict) -> str:
    tr = transition()
    w, mh = MIG_W, MIG_MAP_H
    h = mh + MIG_KEY_H
    pr = map_projection(MIG_CENTER, MIG_FIT, w, mh)
    places = {p["id"]: p for p in tr["places"]}
    ink, muted, col = t["ink"], t["muted"], t["z-t"]
    moves = [m for m in tr["moves"] if m["figure"] == "migrations"]
    b = map_base(t, w, mh, pr, [arrow_marker("head-col", col, 5)])
    regions = {m["to"] for m in moves} | {m["from"] for m in moves}
    b.append('<g clip-path="url(#landclip)">')
    b += [region_blob(pr, places[r], col, 0.4) for r in sorted(regions) if "radius_km" in places[r]]
    b.append("</g>")
    b += map_coast(t, pr, w, mh)
    b.append('<g clip-path="url(#frame)">')
    b += rivers_layer(t, pr, tr, ["rio_grande", "gila"])
    b.append("</g>")
    for rid, lon, lat, rot in (("Рио-Гранде", -107.05, 33.9, -84), ("Хила", -109.75, 33.2, 22)):
        x, y = pr(lon, lat)
        b.append(
            f'<g transform="translate({x:.1f},{y:.1f}) rotate({rot})">'
            + text(0, 0, rid, col, 11.5, "middle", italic=True, halo=t["bg"])
            + "</g>"
        )
    x, y = pr(-112.5, 36.55)
    b.append(text(x, y, "плато Колорадо", muted, 15, "middle", 400, SERIF, True, t["bg"]))

    # стрелки — направления, а не дороги
    for m in moves:
        a, z = places[m["from"]], places[m["to"]]
        (x0, y0), (x1, y1) = pr(a["lon"], a["lat"]), pr(z["lon"], z["lat"])
        trim1 = 44 if "radius_km" in z else 11
        trim0 = 26 if "radius_km" in a else 12
        b.append(
            move_path(x0, y0, x1, y1, MIG_BEND[m["id"]], col, 3.2, "7 4", "head-col", trim0, trim1)
        )

    cpl = {p["id"]: p for p in complex_data()["places"]}
    for pid, (src, dx, dy, anchor) in MIG_LANDMARKS.items():
        p = places[pid] if src == "transition" else cpl[pid]
        x, y = pr(p["lon"], p["lat"])
        b.append(place_mark("landmark", x, y, t))
        b.append(text(x + dx, y + dy, p["name"], ink, 12, anchor, 500, halo=t["bg"]))
    for pid in ("hopi", "zuni"):
        x, y = pr(places[pid]["lon"], places[pid]["lat"])
        b.append(mark("circle", x, y, t["bg"], ink, t["bg"], 4.2))
        b += label_lines(x + 9, y + 4, [(places[pid]["name"], ink, 700)], t)
    xz, yz = pr(places["zuni"]["lon"], places["zuni"]["lat"])
    b += label_lines(
        xz,
        yz + 22,
        [
            ("хопи и зуни — северные группы,", muted, 400),
            ("уцелевшие после распада южной", muted, 400),
            ("сети в 1400–1450 гг.", muted, 400),
        ],
        t,
        "middle",
        12.5,
        14,
    )

    mv = places["mesa_verde"]
    x, y = pr(mv["lon"], mv["lat"])
    b.append(place_mark("origin", x, y, t))
    for pid, (dx, dy, anchor, rows) in MIG_TEXT.items():
        p = places[pid]
        x, y = pr(p["lon"], p["lat"])
        if dx is None:
            x, dx = w - 12, 0
        b += label_lines(
            x + dx,
            y + dy,
            [(rows[0], ink, 700)] + [(r, muted, 400) for r in rows[1:]],
            t,
            anchor,
            12.5,
            14,
        )

    # заголовок и масштаб связей
    b.append(text(20, 36, "Дальние переселения конца XIII в.", ink, 21, "start", 700, halo=t["bg"]))
    b.append(text(20, 58, "стрелки — направления, а не дороги", ink, 14, halo=t["bg"]))
    sx, sy = w - 300, mh - 52
    b.append(text(sx, sy - 22, "Сходство посуды связывало поселения", ink, 12, halo=t["bg"]))
    b.append(
        text(sx, sy - 8, "в среднем на 70–120 км, часть — больше 250 км", ink, 12, halo=t["bg"])
    )
    b += scale_bar(pr, sx, sy + 10, [100, 250], t)
    b.append(
        f'<rect x=".5" y=".5" width="{w - 1}" height="{mh - 1}" fill="none" stroke="{t["rule"]}"/>'
    )

    # легенда
    ky0 = mh + 26
    rows = [
        ("region", "откуда и куда шли — области условные"),
        ("move", "направление переселения, а не дорога"),
        ("origin", "Меса-Верде"),
        ("pueblo", "нынешние хопи и зуни"),
        ("landmark", "ориентир"),
        ("river", "реки — для ориентира"),
    ]
    for k, (kind, s1) in enumerate(rows):
        lx = 20 + (k // 3) * 372
        yy = ky0 + (k % 3) * 22
        if kind == "region":
            b.append(
                f'<ellipse cx="{lx + 13}" cy="{yy}" rx="13" ry="7" fill="{col}" opacity=".45" '
                'filter="url(#soft-key)"/>'
            )
        elif kind == "move":
            b.append(
                f'<path d="M{lx},{yy}L{lx + 22},{yy}" stroke="{col}" stroke-width="3" '
                'stroke-dasharray="7 4" marker-end="url(#head-col)"/>'
            )
        elif kind == "pueblo":
            b.append(mark("circle", lx + 13, yy, t["bg"], ink, t["bg"], 4.2))
        elif kind == "river":
            b.append(line(lx, yy, lx + 26, yy, col, 1.3, opacity=0.55))
        else:
            b.append(place_mark(kind, lx + 13, yy, t))
        b.append(text(lx + 36, yy + 4, s1, ink, 12.5))
    b.append(
        text(
            20,
            h - 10,
            "Схема: области условные; положение точек ориентировочное.",
            muted,
            12,
            italic=True,
        )
    )
    return svg(
        w,
        h,
        t,
        b,
        "Дальние переселения конца XIII в. (схема)",
        "Карта плато Колорадо и юга Аризоны. Толстая пунктирная стрелка ведёт от Меса-Верде к "
        "размытому пятну на севере долины Рио-Гранде: сюда ушло большинство жителей; уход "
        "начался до 1260 г., к 1285 г. на Меса-Верде никого. Вторая стрелка — от района Каента "
        "на северо-востоке Аризоны к размытому пятну в центральной Аризоне: переселенцы 1280-х "
        "гг.; здесь, по осторожной формулировке авторов, начали делать посуду саладо. Кругами "
        "отмечены хопи и зуни — северные группы, уцелевшие после распада южной сети в "
        "1400–1450 гг. Линейка: сходство посуды связывало поселения в среднем на 70–120 км, "
        "часть — больше 250 км. Ориентиры: Чако, Санта-Фе, Каса-Гранде; реки Рио-Гранде и "
        "Хила. Схема: области условные.",
    )


# ── Рис. 4.7. Чичимекская война и колонии тлашкальтеков (данные)

CHICH_W, CHICH_MAP_H, CHICH_KEY_H = 760, 600, 132
CHICH_CENTER = (-100.9, 22.5)
CHICH_FIT = [(-105.6, 27.0), (-96.2, 27.0), (-105.6, 18.35), (-96.2, 18.35)]
CHICH_BLUR = 16  # px: край Мезоамерики в крупном масштабе размыт сильнее, чем на рис. 4.1
# Стрелки: id цели: (откуда, изгиб). Паррас основали в 1598 г. семьи из Сан-Эстебана, а не
# переселенцы 1591 г. из Тлашкалы, — поэтому его стрелка короткая, от Сан-Эстебана.
CHICH_ROUTES = {
    "colotlan": ("tlaxcala", -0.14),
    "saltillo": ("tlaxcala", -0.1),
    "parras": ("saltillo", 0.12),
}
CHICH_LABELS = {  # id: (dx, dy, выравнивание, вторая строка: шаблон по when)
    "zacatecas": (-10, -6, "end", "серебро {w}"),
    "san_luis_potosi": (0, -27, "middle", "рудник {w} — уже после мира"),
    "colotlan": (-10, 18, "end", "основан {w}"),
    "saltillo": (10, -6, "start", "колония {w}"),
    "parras": (-10, 16, "end", "основан {w}"),
    "tlaxcala": (10, 4, "start", None),
    "mexico_city": (-9, 4, "end", None),
}
CHICH_NAMES = {"saltillo": ["Сан-Эстебан-де-ла-Нуэва-", "Тласкала (у Сальтильо)"]}
CHICH_NOTES = {"parras": "семьями из Сан-Эстебана"}  # третья строка подписи
# Опорные точки края Мезоамерики, попавшие в рамку: подпись (dx, dy, выравнивание). Без них
# не видно, что Колотлан и Сакатекас стоят в размытой полосе края, а не внутри Мезоамерики.
CHICH_EDGE = {"lerma": (0, 17, "middle"), "panuco_mouth": (-8, 4, "end")}
CHICH_MESO_LABEL = (-104.0, 20.0)


def fig_chichimeca(t: dict) -> str:
    tr = transition()
    w, mh = CHICH_W, CHICH_MAP_H
    h = mh + CHICH_KEY_H
    pr = map_projection(CHICH_CENTER, CHICH_FIT, w, mh)
    places = {p["id"]: p for p in tr["places"]}
    ink, muted, col, meso_c = t["ink"], t["muted"], t["z-t"], t["z-m"]
    b = map_base(
        t,
        w,
        mh,
        pr,
        [
            arrow_marker("head-col", col, 5.5),
            '<filter id="soft-wide" x="-30%" y="-30%" width="160%" height="160%">'
            f'<feGaussianBlur stdDeviation="{CHICH_BLUR}"/></filter>',
        ],
    )
    b += [
        '<g clip-path="url(#landclip)">',
        f'<path d="{meso_d(pr, tr)}" fill="{meso_c}" opacity=".5" filter="url(#soft-wide)"/>',
        "</g>",
    ]
    b += map_coast(t, pr, w, mh)
    b.append(sea_label(pr, -96.6, 24.3, "Мексиканский", t, 13))
    b.append(sea_label(pr, -96.6, 23.75, "залив", t, 13))
    b.append(sea_label(pr, -105.0, 19.2, "Тихий океан", t, 13))
    x, y = pr(*CHICH_MESO_LABEL)
    b.append(text(x, y, "Мезоамерика", ink, 16, "middle", 600, SERIF, True, t["bg"]))
    b.append(
        text(x, y + 15, "по Кирхгофу, ко времени завоевания", muted, 11.5, "middle", halo=t["bg"])
    )

    # край Мезоамерики: опорные точки Кирхгофа
    for pid, (dx, dy, anchor) in CHICH_EDGE.items():
        p = places[pid]
        x, y = pr(p["lon"], p["lat"])
        b.append(place_mark("edge", x, y, t))
        b.append(text(x + dx, y + dy, p["name"], ink, 11.5, anchor, italic=True, halo=t["bg"]))

    # переселение тлашкальтеков: направления, а не дороги
    for pid, (src, bend) in CHICH_ROUTES.items():
        ox, oy = pr(places[src]["lon"], places[src]["lat"])
        x1, y1 = pr(places[pid]["lon"], places[pid]["lat"])
        a, bb, cx, cy, z, zz = map_curve(ox, oy, x1, y1, bend, 8, 9)
        b.append(
            f'<path d="M{a:.1f},{bb:.1f}Q{cx:.1f},{cy:.1f} {z:.1f},{zz:.1f}" fill="none" '
            f'stroke="{col}" stroke-width="2.2" stroke-dasharray="6 4" stroke-linecap="round" '
            'marker-end="url(#head-col)"/>'
        )

    # народы — подписи без границ, поверх стрелок
    for p in tr["peoples"]:
        x, y = pr(p["label"]["lon"], p["label"]["lat"])
        b.append(
            f'<text x="{x:.1f}" y="{y:.1f}" fill="{muted}" font-size="17" text-anchor="middle" '
            f'font-family="{SERIF}" font-style="italic" letter-spacing="1.5" paint-order="stroke" '
            f'stroke="{t["bg"]}" stroke-width="4" stroke-linejoin="round">'
            f"{escape(p['name'])}</text>"
        )

    marks, labels = [], []
    for pid, (dx, dy, anchor, sub) in CHICH_LABELS.items():
        p = places[pid]
        x, y = pr(p["lon"], p["lat"])
        marks.append(place_mark(p["role"], x, y, t))
        names = CHICH_NAMES.get(pid, [p["name"]])
        for k, s1 in enumerate(names):
            labels.append(text(x + dx, y + dy + k * 15, s1, ink, 13, anchor, 600, halo=t["bg"]))
        if sub:
            s1 = sub.format(w=day_text(p["when"]))
            labels.append(
                text(x + dx, y + dy + len(names) * 15, s1, muted, 12, anchor, halo=t["bg"])
            )
        if pid in CHICH_NOTES:
            labels.append(
                text(x + dx, y + dy + 30, CHICH_NOTES[pid], muted, 12, anchor, halo=t["bg"])
            )
    # Тлашкала: капитуляции и выход колонистов
    cap = next(e for e in tr["timeline"] if e["id"] == "capitulations")
    tx, ty = pr(places["tlaxcala"]["lon"], places["tlaxcala"]["lat"])
    for k, s1 in enumerate(
        [f"капитуляции {day_text(cap['when'])};", "в июне 1591 г. вышли первые колонисты"]
    ):
        labels.append(text(tx - 10, ty + 20 + k * 14, s1, muted, 12, "end", halo=t["bg"]))
    b += marks + labels

    # крупно: что это за рисунок
    war = next(e for e in tr["timeline"] if e["id"] == "war")
    span = f"{war['when']['start']}–{war['when']['end']}"
    b.append(text(20, 38, f"Война {span} гг.", ink, 22, "start", 700, halo=t["bg"]))
    b.append(text(20, 60, "и колонии тлашкальтеков 1591 г.", ink, 15, "start", halo=t["bg"]))
    b.append(
        f'<rect x=".5" y=".5" width="{w - 1}" height="{mh - 1}" fill="none" stroke="{t["rule"]}"/>'
    )

    # легенда — полосой под картой, в два столбца
    rows = [
        ("mine", "рудник, испанский город"),
        ("colony", "колония тлашкальтеков"),
        ("origin", "откуда шли переселенцы"),
        ("edge", "опорная точка края по Кирхгофу"),
        ("route", "направление переселения, а не дорога"),
        ("meso", "Мезоамерика — край размыт"),
        ("people", "народы, которых испанцы звали «чичимеками»;"),
    ]
    ky = mh + 26
    for k, (kind, s1) in enumerate(rows):
        lx = 20 + (k // 4) * 372
        yy = ky + (k % 4) * 22
        if kind == "route":
            b.append(
                f'<path d="M{lx},{yy}L{lx + 24},{yy}" stroke="{col}" stroke-width="2.2" '
                'stroke-dasharray="6 4" marker-end="url(#head-col)"/>'
            )
        elif kind == "meso":
            b.append(
                f'<ellipse cx="{lx + 13}" cy="{yy}" rx="13" ry="7" fill="{meso_c}" opacity=".5" '
                'filter="url(#soft-key)"/>'
            )
        elif kind == "people":
            b.append(text(lx + 13, yy + 5, "пами", muted, 13, "middle", family=SERIF, italic=True))
        else:
            b.append(place_mark(kind, lx + 13, yy, t))
        b.append(text(lx + 36, yy + 4, s1, ink, 12.5))
    b.append(text(20 + 372 + 36, ky + 3 * 22 - 4, "подписи без границ: земли известны", muted, 12))
    b.append(text(20 + 372 + 36, ky + 3 * 22 + 10, "лишь в общих чертах", muted, 12))
    b.append(text(20, h - 10, "Положение точек ориентировочное.", muted, 12, italic=True))
    col_names = ", ".join(
        f"{places[pid]['name']} ({day_text(places[pid]['when'])})"
        for pid, (src, _) in CHICH_ROUTES.items()
        if src == "tlaxcala"
    )
    return svg(
        w,
        h,
        t,
        b,
        f"Чичимекская война {span} гг. и колонии тлашкальтеков",
        "Карта центральной и северной Мексики. Размытой полосой — северный край Мезоамерики по "
        "Кирхгофу. Севернее — подписи народов без границ: "
        + ", ".join(p["name"] for p in tr["peoples"])
        + f". Рудники: Сакатекас (серебро {day_text(places['zacatecas']['when'])}), "
        f"Сан-Луис-Потоси ({day_text(places['san_luis_potosi']['when'])}, после мира). Из "
        f"Тлашкалы (капитуляции {day_text(cap['when'])}) пунктирные стрелки ведут к колониям: "
        f"{col_names}; от Сан-Эстебана — короткая стрелка к Паррасу, основанному его семьями в "
        f"{places['parras']['when']['start']} г. Опорные точки края — Лерма и устье Пануко. "
        "Положение точек ориентировочное.",
    )


# ── Рис. 4.8. Население провинции Хемес до и после миссий (данные)

JZ_FROM, JZ_TO, JZ_MAX = 1480, 1700, 8500
JZ_KIND = {"ruins": "z-n", "document": "z-t"}
# Подписи точек: id: (где, сдвиг по y) — "left" — слева от точки; "col" — в колонке справа от
# поля графика, с выноской (поздние точки стоят тесно у края шкалы).
JZ_LABELS = {
    "zarate": ("left", 0),
    "benavides": ("left", 0),
    "record_1644": ("left", 4),
    "patokwa": ("col", -60),
    "military_1694": ("col", 14),
}
JZ_MARK_ROWS = {"contact": 0, "colony": 0, "missions": 1, "revolt": 0}  # ряд подписи вехи


def jz_value(e: dict) -> str:
    v = grouped(e["value"])
    return {"exact": v, "at_most": f"не больше {v}", "less_than": f"меньше {v}"}[e["bound"]]


def fig_jemez(t: dict) -> str:
    jz = transition()["jemez"]
    w, h = 760, 520
    x0, x1, top, yb, xc = 70, 592, 104, 404, 612
    ink, muted = t["ink"], t["muted"]
    col = {k: t[v] for k, v in JZ_KIND.items()}

    def px(yr: float) -> float:
        return x0 + (yr - JZ_FROM) / (JZ_TO - JZ_FROM) * (x1 - x0)

    def py(v: float) -> float:
        return yb - v / JZ_MAX * (yb - top)

    b = ["<defs>"]
    b += [arrow_marker(f"head-{k}", c, 5) for k, c in col.items()]
    b += [arrow_marker("head-muted", muted, 5), "</defs>"]
    for v in range(0, JZ_MAX + 1, 1000):
        y = py(v)
        b.append(line(x0, y, x1, y, t["rule"], 1.0 if v == 0 else 0.6))
        b.append(text(x0 - 8, y + 4, grouped(v), muted, 11.5, "end"))
    for yr in range(JZ_FROM, JZ_TO + 1, 20):
        b.append(line(px(yr), yb, px(yr), yb + 5, muted, 1))
        b.append(text(px(yr), yb + 19, f"{yr}", ink, 12, "middle"))
    b.append(text(x0 - 8, 22, "жителей провинции Хемес", muted, 12))

    # вехи колонизации
    for m in jz["marks"]:
        sp = m["when"]
        a = px(sp["start"])
        ytxt = top - 46 + JZ_MARK_ROWS[m["id"]] * 28
        if sp["end"] != sp["start"]:
            z = px(sp["end"] + 1)
            b.append(rect(a, top - 4, z - a, yb - top + 4, t["band"], 0))
            xm, when = (a + z) / 2, sp["label"]
        else:
            b.append(line(a, top - 4, a, yb, muted, 1, "3 3"))
            xm, when = a, f"{sp['start']}"
        b.append(text(xm, ytxt, when, ink, 12, "middle", 600, halo=t["bg"]))
        b.append(text(xm, ytxt + 14, m["label"], muted, 11.5, "middle", halo=t["bg"]))

    # убыль за 1620–1680 гг. — скобкой по оси времени, а не линией между точками: численность
    # в промежутках неизвестна
    d = jz["decline"]
    xa, xz, yr_ = px(d["from"]), px(d["to"]), py(4500)
    b.append(
        f'<path d="M{xa:.1f},{yr_ + 6:.1f}V{yr_:.1f}H{xz:.1f}V{yr_ + 6:.1f}" stroke="{muted}" '
        'stroke-width="1.2" fill="none"/>'
    )
    xm_ = (xa + xz) / 2
    b.append(
        text(
            xm_ + 24,
            yr_ - 22,
            f"−{num(d['pct'])}% за {d['from']}–{d['to']} гг.",
            ink,
            14,
            "middle",
            700,
            halo=t["bg"],
        )
    )
    b.append(text(xm_ + 24, yr_ - 7, d["label"], muted, 12, "middle", halo=t["bg"]))

    for e in jz["estimates"]:
        c, sp = col[e["kind"]], e["when"]
        a, z = px(sp["start"]), px(sp["end"])
        if "low" in e:  # диапазон по развалинам — подпись внутри полосы
            b.append(
                rect(
                    a,
                    py(e["high"]),
                    z - a,
                    py(e["low"]) - py(e["high"]),
                    c,
                    2,
                    0.35,
                    f' stroke="{c}" stroke-width="1.4"',
                )
            )
            xm = (a + z) / 2
            yt = py(e["high"]) + 22
            b.append(
                text(xm, yt, f"{grouped(e['low'])}–{grouped(e['high'])}", ink, 13.5, "middle", 700)
            )
            b.append(text(xm, yt + 17, sp["label"], ink, 11.5, "middle"))
            for k, s1 in enumerate(split_label(e["label"], 14)):
                b.append(text(xm, yt + 32 + k * 14, s1, ink, 11.5, "middle"))
            continue
        y = py(e["value"])
        xm = (a + z) / 2
        if sp["end"] != sp["start"]:
            b.append(line(a, y, z, y, c, 3))
        if e["kind"] == "ruins":
            b.append(mark("diamond", xm, y, t["bg"], c, t["bg"], 4.6))
        else:
            b.append(mark("circle", xm, y, c, c, t["bg"], 4.6))
        if e["bound"] != "exact":  # «не больше», «меньше» — стрелка вниз
            b.append(
                f'<path d="M{xm:.1f},{y + 7:.1f}L{xm:.1f},{y + 19:.1f}" stroke="{c}" '
                f'stroke-width="1.6" marker-end="url(#head-{e["kind"]})"/>'
            )
        where, dy = JZ_LABELS[e["id"]]
        when = sp.get("label") or (
            f"{sp['start']}–{sp['end']}" if sp["end"] != sp["start"] else f"{sp['start']}"
        )
        what = f" {e['what']}" if e.get("what") else ""
        s1, s2 = f"{jz_value(e)}{what} — {when}", e["label"]
        if where == "left":
            b.append(text(a - 10, y + dy - 2, s1, ink, 12.5, "end", 600, halo=t["bg"]))
            b.append(text(a - 10, y + dy + 12, s2, muted, 11.5, "end", halo=t["bg"]))
            continue
        # колонка справа: число, время, пояснение — по строке; выноска от точки
        rows = [(jz_value(e) + what, ink, 600), (when, ink, 400)]
        rows += [(r, muted, 400) for r in split_label(s2, 20)]
        yt = y + dy
        b.append(
            f'<path d="M{xm + 7:.1f},{y:.1f}L{x1 + 6:.1f},{yt - 4:.1f}L{xc - 4:.1f},{yt - 4:.1f}" '
            f'stroke="{muted}" stroke-width=".8" fill="none"/>'
        )
        for k, (r, c2, wt) in enumerate(rows):
            b.append(
                text(xc, yt + k * 14, r, c2, 12.5 if k == 0 else 11.5, "start", wt, halo=t["bg"])
            )

    # легенда
    ly = yb + 52
    items = [
        ("ruins", "оценка по развалинам"),
        ("document", "число из испанского документа"),
        ("down", "«не больше», «меньше»"),
    ]
    for k, (kind, s1) in enumerate(items):
        lx = 24 + k * 240
        if kind == "down":
            b.append(
                f'<path d="M{lx + 8},{ly - 8}L{lx + 8},{ly + 5}" stroke="{ink}" stroke-width="1.6" '
                'marker-end="url(#head-muted)"/>'
            )
        elif kind == "ruins":
            b.append(mark("diamond", lx + 8, ly, t["bg"], col["ruins"], t["bg"], 4.6))
        else:
            b.append(mark("circle", lx + 8, ly, col["document"], col["document"], t["bg"], 4.6))
        b.append(text(lx + 22, ly + 4.5, s1, ink, 12.5))
    b.append(
        text(
            w - 16,
            h - 10,
            "Между точками линий нет: численность в промежутках неизвестна",
            muted,
            12,
            "end",
            italic=True,
        )
    )

    def est_desc(e):
        if "low" in e:
            return f"{e['when']['label']}: {grouped(e['low'])}–{grouped(e['high'])} (по развалинам)"
        when = e["when"].get("label") or e["when"]["start"]
        src = "по развалинам" if e["kind"] == "ruins" else "по документам"
        return f"{when}: {jz_value(e)} ({src})"

    desc = "; ".join(est_desc(e) for e in jz["estimates"])
    marks_desc = "; ".join(
        f"{m['when'].get('label') or m['when']['start']} — {m['label']}" for m in jz["marks"]
    )
    return svg(
        w,
        h,
        t,
        b,
        "Население провинции Хемес, 1480–1700 гг.",
        f"По горизонтали годы 1480–1700, по вертикали — число жителей. {desc}. Вехи: {marks_desc}. "
        f"Убыль за {d['from']}–{d['to']} гг. — {num(d['pct'])}% ({d['label']}).",
    )


# ── Рис. 4.9. Восстание пуэбло 1680 г. и после (схема по тексту главы)

REV_W, REV_MAP_H, REV_KEY_H = 760, 640, 120
REV_CENTER = (-105.7, 35.4)
REV_FIT = [(-110.9, 39.75), (-100.3, 39.75), (-110.9, 31.45), (-100.3, 31.45)]
REV_KIND = {"retreat": "z-n", "flight": "z-t", "run": "muted"}
REV_BEND = {
    "retreat_santa_fe": 0.10,
    "retreat_isleta": -0.06,
    "flight_santa_clara": 0.10,
    "flight_picuris": 0.07,
    "run_1980": -0.34,
}
# Подписи точек: id: (столбец, сдвиг по y от точки, строки). Точки у Рио-Гранде стоят
# тесно — подписи вынесены в два столбца, к точке ведёт выноска. Столбец: "e" — восточный
# (по долготе REV_COL_E, выравнивание влево), "w" — западный (REV_COL_W, вправо), "near" —
# у самой точки.
REV_COL_E, REV_COL_W = -104.95, -107.35
REV_LABELS = {
    "taos": ("e", 8, ["Таос", "Попе разослал отсюда по пуэбло", "верёвку с узлами"]),
    "picuris": ("e", 40, ["Пикурис", "Луис Тупату"]),
    "santa_fe": ("e", 44, ["Санта-Фе", "здесь собрались уцелевшие испанцы"]),
    "san_juan": ("w", -14, ["Сан-Хуан (Окай-Овинге)", "пуэбло Попе"]),
    "santa_clara": ("w", 20, ["Санта-Клара"]),
    "zia": ("w", 10, ["Сия, Санта-Ана, Сан-Фелипе", "в 1690-х — за испанцев"]),
    "isleta": ("w", 4, ["Ислета", "не участвовала; здесь —", "около 1500 беженцев"]),
    "el_paso": (
        "e",
        -44,
        ["Эль-Пасо", "переправа у монастыря Гуадалупе;", "отсюда — поселения вокруг Эль-Пасо"],
    ),
    "el_cuartelejo": (
        "near",
        0,
        ["Эль-Куартелехо", "у союзников-апачей; большинство", "прожило здесь около десяти лет"],
    ),
    "hopi": ("near", 0, ["хопи"]),
}
REV_GROUP = {"zia": ["zia", "santa_ana", "san_felipe"]}  # одна подпись на три точки
# Подписи стрелок: id: (lon, lat, выравнивание, строки)
REV_MOVE_LABELS = {
    "retreat_santa_fe": (
        -105.55,
        33.0,
        "start",
        ["отступление испанцев", "конец сентября 1680 г."],
    ),
    "flight_picuris": (
        -103.55,
        38.35,
        "end",
        ["октябрь 1696 г.", "Санта-Клара и Пикурис —", "на равнины, к союзникам"],
    ),
    "run_1980": (
        -108.3,
        37.55,
        "middle",
        ["1980 г.: бег со шнуром", "с узлами — от Таоса до хопи"],
    ),
}


def fig_revolt(t: dict) -> str:
    tr = transition()
    w, mh = REV_W, REV_MAP_H
    h = mh + REV_KEY_H
    pr = map_projection(REV_CENTER, REV_FIT, w, mh)
    places = {p["id"]: p for p in tr["places"]}
    ink, muted = t["ink"], t["muted"]
    col = {k: t[v] for k, v in REV_KIND.items()}
    moves = [m for m in tr["moves"] if m["figure"] == "revolt"]
    b = map_base(t, w, mh, pr, [arrow_marker(f"head-{k}", c, 5) for k, c in col.items()])
    b += map_coast(t, pr, w, mh)
    b.append('<g clip-path="url(#frame)">')
    b += rivers_layer(t, pr, tr, ["rio_grande"])
    b.append(
        f'<path d="{border_d(pr, ("MEX", "USA"))}" fill="none" stroke="{ink}" '
        'stroke-width="1.2" stroke-linejoin="round"/>'
    )
    b.append("</g>")
    x, y = pr(-107.25, 33.6)
    b.append(
        f'<g transform="translate({x:.1f},{y:.1f}) rotate(-80)">'
        + text(0, 0, "Рио-Гранде", t["z-t"], 11.5, "middle", italic=True, halo=t["bg"])
        + "</g>"
    )
    x, y = pr(-108.6, 31.62)
    b.append(text(x, y, "граница США и Мексики сегодня", ink, 11.5, "middle", halo=t["bg"]))
    x, y = pr(-101.7, 35.5)
    b.append(text(x, y, "равнины", muted, 16, "middle", 400, SERIF, True, t["bg"]))

    for m in moves:
        a, z = places[m["from"]], places[m["to"]]
        (x0, y0), (x1, y1) = pr(a["lon"], a["lat"]), pr(z["lon"], z["lat"])
        dash, wd = ("2 4", 1.6) if m["kind"] == "run" else ("7 4", 2.6)
        b.append(
            move_path(
                x0,
                y0,
                x1,
                y1,
                REV_BEND[m["id"]],
                col[m["kind"]],
                wd,
                dash,
                f"head-{m['kind']}",
                7,
                10,
            )
        )
    for mid, (lon, lat, anchor, rows) in REV_MOVE_LABELS.items():
        kind = next(m["kind"] for m in moves if m["id"] == mid)
        x, y = pr(lon, lat)
        c = col[kind] if kind != "run" else ink
        b += label_lines(
            x, y, [(rows[0], c, 700)] + [(r, muted, 400) for r in rows[1:]], t, anchor, 12.5, 14
        )

    # точки и подписи с выносками
    marks, labels = [], []
    xe_col, xw_col = pr(REV_COL_E, 35)[0], pr(REV_COL_W, 35)[0]
    for pid, (colname, dy, rows) in REV_LABELS.items():
        group = REV_GROUP.get(pid, [pid])
        pts = [pr(places[g]["lon"], places[g]["lat"]) for g in group]
        for g, (x, y) in zip(group, pts, strict=True):
            role = places[g]["role"]
            if role == "spanish":
                marks.append(place_mark("mine", x, y, t))
            elif role == "place":
                marks.append(mark("diamond", x, y, t["bg"], ink, t["bg"], 4.2))
            else:
                marks.append(mark("circle", x, y, ink, ink, t["bg"], 3.4))
        x, y = pts[0]
        if colname == "near":
            anchor = "end" if pid == "el_cuartelejo" else "start"
            lx, ly = (x + 4, y - 50) if anchor == "end" else (x + 9, y + 4)
        else:
            anchor = "start" if colname == "e" else "end"
            lx = xe_col if colname == "e" else xw_col
            ly = y + dy
            xe = lx + (-6 if anchor == "start" else 6)
            for x2, y2 in pts:
                labels.append(
                    f'<path d="M{x2:.1f},{y2:.1f}L{xe:.1f},{ly - 4:.1f}" stroke="{muted}" '
                    'stroke-width=".7" fill="none"/>'
                )
        labels += label_lines(
            lx, ly, [(rows[0], ink, 700)] + [(r, muted, 400) for r in rows[1:]], t, anchor, 12.5, 14
        )
    b += labels + marks

    b.append(text(20, 36, "Восстание пуэбло: 1680 г. и после", ink, 21, "start", 700, halo=t["bg"]))
    b.append(text(20, 58, "пуэбло — точками, без границ земель", ink, 14, halo=t["bg"]))
    b.append(
        f'<rect x=".5" y=".5" width="{w - 1}" height="{mh - 1}" fill="none" stroke="{t["rule"]}"/>'
    )

    # легенда
    ky0 = mh + 26
    rows = [
        ("pueblo", "пуэбло"),
        ("spanish", "испанский город, миссия"),
        ("place", "место у союзников-апачей"),
        ("retreat", "отступление испанцев, 1680"),
        ("flight", "уход пуэбло к союзникам, 1696"),
        ("run", "бег в память о гонцах, 1980"),
    ]
    for k, (kind, s1) in enumerate(rows):
        lx = 20 + (k // 3) * 372
        yy = ky0 + (k % 3) * 22
        if kind in col:
            dash, wd = ("2 4", 1.6) if kind == "run" else ("7 4", 2.6)
            b.append(
                f'<path d="M{lx},{yy}L{lx + 22},{yy}" stroke="{col[kind]}" stroke-width="{wd}" '
                f'stroke-dasharray="{dash}" marker-end="url(#head-{kind})"/>'
            )
        elif kind == "pueblo":
            b.append(mark("circle", lx + 13, yy, ink, ink, t["bg"], 3.4))
        elif kind == "spanish":
            b.append(place_mark("mine", lx + 13, yy, t))
        else:
            b.append(mark("diamond", lx + 13, yy, t["bg"], ink, t["bg"], 4.2))
        b.append(text(lx + 36, yy + 4, s1, ink, 12.5))
    b.append(text(20, h - 26, "Стрелки — направления, а не дороги.", muted, 12))
    b.append(text(20, h - 10, "Положение точек ориентировочное.", muted, 12, italic=True))
    return svg(
        w,
        h,
        t,
        b,
        "Восстание пуэбло 1680 г. и после (схема)",
        "Карта Нью-Мексико и соседних земель. Пуэбло — точками без границ земель: Таос (отсюда "
        "Попе разослал верёвку с узлами), Пикурис, Сан-Хуан (Окай-Овинге), Санта-Клара, Сия, "
        "Санта-Ана и Сан-Фелипе (в 1690-х — на стороне испанцев), Ислета (не участвовала; около "
        "1500 беженцев), хопи. Квадратами — Санта-Фе, где собрались уцелевшие испанцы, и "
        "Эль-Пасо. Стрелки отступления испанцев ведут от Санта-Фе и Ислеты к Эль-Пасо (конец "
        "сентября 1680 г.). Стрелки от Санта-Клары и Пикуриса ведут на равнины, к союзникам-апачам "
        "в Эль-Куартелехо (октябрь 1696 г.). Пунктир от Таоса до хопи — бег 1980 г. со шнуром с "
        "узлами в память о гонцах 1680 г. Положение точек ориентировочное.",
    )


# ── Рис. 4.10. Дважды «мир покупкой» (схема по данным)

# Строка на событие: слева дата и подпись, справа — метка или полоса на шкале. Так подписи
# не налезают друг на друга даже там, где события идут через год (1785–1787, 1591).
PEACE_ROWS = {"chichimeca": (1540, 1600, 10), "apache": (1740, 1860, 20)}  # от, до, шаг меток
PEACE_TITLES = {
    "chichimeca": "Конец Чичимекской войны, 1540–1600",
    "apache": "Апачи, команчи и Мексика, 1740–1860",
}
PEACE_COLOR = {"war": "z-n", "peace": "z-t", "event": "ink", "state": "ink"}
PEACE_FADE = 22  # px: размытый край полосы
PEACE_OPEN = 60  # px: сколько тянется полоса без конца, прежде чем погаснуть
PEACE_WHEN = {  # даты, которые в столбец дат не помещаются словами из данных
    "establecimientos": "с 1786",
    "raids": "с начала 1830-х",
}
PEACE_ON_BAR = {  # пояснение в той же строке, слева от полосы или метки
    "establecimientos": "больше четырёх десятилетий",
    "gadsden": "подписан; в силу — 1854",
}


def peace_when(ev: dict) -> str:
    sp = ev["when"]
    if ev["id"] in PEACE_WHEN:
        return PEACE_WHEN[ev["id"]]
    if sp.get("day"):
        y, m, d = sp["day"].split("-")
        return f"{int(d)}.{m}.{y}"
    if sp.get("label", "").startswith("около"):
        return f"≈{sp['start']}"
    if sp["end"] is not None and sp["end"] != sp["start"]:
        return f"{sp['start']}–{sp['end']}"
    return f"{sp['start']}"


def fig_peace(t: dict) -> str:
    tl = transition()["timeline"]
    w, xd, xl, x0, x1 = 760, 112, 122, 400, 744
    row_h, head, gap = 21, 48, 30
    counts = {r: sum(e["row"] == r for e in tl) for r in PEACE_ROWS}
    h = 16 + sum(head + n * row_h for n in counts.values()) + gap + 84
    ink, muted = t["ink"], t["muted"]
    b = ["<defs>"]
    for kind, tok in PEACE_COLOR.items():
        c = t[tok]
        b.append(
            f'<linearGradient id="fade-r-{kind}" x1="0" x2="1"><stop offset="0" stop-color="{c}"/>'
            f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></linearGradient>'
            f'<linearGradient id="fade-l-{kind}" x1="0" x2="1"><stop offset="0" stop-color="{c}" '
            f'stop-opacity="0"/><stop offset="1" stop-color="{c}"/></linearGradient>'
        )
    b.append("</defs>")
    y_top = 16
    for row, (lo, hi, step) in PEACE_ROWS.items():

        def px(yr: float, lo=lo, hi=hi) -> float:
            return x0 + (yr - lo) / (hi - lo) * (x1 - x0)

        evs = sorted((e for e in tl if e["row"] == row), key=lambda e: e["when"]["start"])
        b.append(text(16, y_top + 20, PEACE_TITLES[row], ink, 15, "start", 700))
        ya = y_top + head
        yb = ya + len(evs) * row_h
        for yr in range(lo, hi + 1, step):
            b.append(line(px(yr), ya - 6, px(yr), yb, t["rule"], 0.7))
            b.append(text(px(yr), ya - 12, f"{yr}", muted, 11.5, "middle"))
        for i, ev in enumerate(evs):
            yc = ya + i * row_h + row_h / 2
            if i % 2 == 0:
                b.append(rect(0, yc - row_h / 2, w, row_h, t["band"], 0))
            c = t[PEACE_COLOR[ev["kind"]]]
            sp = ev["when"]
            b.append(text(xd, yc + 4, peace_when(ev), ink, 12, "end", 600))
            b.append(text(xl, yc + 4, ev["label"], ink, 12))
            a = px(sp["start"])
            fs = sp.get("fuzzy_start")
            fe = sp.get("fuzzy_end") or sp.get("open_end")
            if sp["end"] is None or sp["end"] != sp["start"]:  # полоса
                z = px(sp["end"]) if sp["end"] is not None else min(a + PEACE_OPEN, x1)
                core_a = a + (PEACE_FADE / 2 if fs else 0)
                core_z = z - (PEACE_FADE / 2 if fe else 0)
                if sp.get("open_end"):
                    core_z = core_a + 4
                    z = core_z + PEACE_OPEN
                if fs:
                    b.append(
                        rect(
                            a - PEACE_FADE / 2,
                            yc - 5,
                            core_a - a + PEACE_FADE / 2,
                            10,
                            f"url(#fade-l-{ev['kind']})",
                            0,
                        )
                    )
                b.append(rect(core_a, yc - 5, max(core_z - core_a, 2), 10, c, 0))
                if fe:
                    b.append(
                        rect(
                            core_z,
                            yc - 5,
                            min(z - core_z + PEACE_FADE / 2, x1 - core_z),
                            10,
                            f"url(#fade-r-{ev['kind']})",
                            0,
                        )
                    )
                note = PEACE_ON_BAR.get(ev["id"])
                if note:  # в той же строке, слева от полосы: справа места нет
                    x_note = a - (PEACE_FADE / 2 if fs else 0) - 6
                    b.append(text(x_note, yc + 4, note, muted, 11, "end", italic=True))
            else:
                b.append(mark("diamond", a, yc, c, c, t["bg"], 4.2))
                note = PEACE_ON_BAR.get(ev["id"])
                if note:
                    b.append(text(a - 10, yc + 4, note, muted, 11, "end", italic=True))
        y_top = yb + gap

    # легенда
    ly = h - 52
    items = [
        ("war", "война, набеги"),
        ("peace", "«мир покупкой» и его плоды"),
        ("event", "другие события"),
    ]
    for k, (kind, s1) in enumerate(items):
        lx = 16 + k * 220
        b.append(rect(lx, ly - 5, 22, 10, t[PEACE_COLOR[kind]], 0))
        b.append(text(lx + 30, ly + 4, s1, ink, 12.5))
    b.append(
        text(16, h - 28, "Шкалы — в разном масштабе: верхняя — 60 лет, нижняя — 120.", muted, 12)
    )
    b.append(
        text(
            16,
            h - 12,
            "Размытый край — срок известен лишь примерно; "
            "конец набегов источники главы не называют.",
            muted,
            12,
        )
    )
    desc = "; ".join(
        f"{peace_when(e)} — {e['label']}"
        + (f" ({PEACE_ON_BAR[e['id']]})" if e["id"] in PEACE_ON_BAR else "")
        for e in tl
    )
    return svg(
        w,
        h,
        t,
        b,
        "Дважды «мир покупкой»: конец Чичимекской войны и мир с апачами и команчами",
        "Две шкалы, 1540–1600 и 1740–1860; строка на событие, цвет — война и набеги, «мир "
        f"покупкой» или другие события. {desc}.",
    )


# ── Рис. 4.12. Граница поперёк земли оодхам (схема: линии условные)

BOR_W, BOR_MAP_H, BOR_KEY_H = 760, 470, 150
BOR_CENTER = (-111.6, 32.2)
BOR_FIT = [(-117.4, 34.25), (-105.9, 34.25), (-117.4, 30.25), (-105.9, 30.25)]
BOR_STRIP = (-114.8, -106.45)  # долготы, между которыми нынешняя граница — линия Гадсдена


def border_pts(pair=("MEX", "USA")) -> list[list[tuple[float, float]]]:
    """Точки нынешней границы двух стран (lon, lat) — по частям линии."""
    fc = json.loads(BORDERS.read_text(encoding="utf-8"))
    out = []
    for f in fc["features"]:
        if f["properties"]["between"] != sorted(pair):
            continue
        g = f["geometry"]
        out += [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
    return out


def gadsden_strip(tr: dict) -> list[tuple[float, float]]:
    """Полоса между линией 1848 г. и нынешней границей. Линия 1848 г. в данных идёт от
    Эль-Пасо на запад; её разворачиваем (с запада на восток) и замыкаем нынешней границей
    обратно на запад — её отрезок между Колорадо и Эль-Пасо."""
    l48 = next(ln for ln in tr["lines"] if ln["id"] == "border1848")["coords"]
    lo, hi = BOR_STRIP
    now = [
        (lon, lat) for part in border_pts() for lon, lat in part if lo <= lon <= hi and lat < 32.75
    ]
    now.sort(key=lambda q: -q[0])  # с востока на запад
    return [(lon, lat) for lon, lat in l48[::-1]] + now


def fig_border(t: dict) -> str:
    tr = transition()
    w, mh = BOR_W, BOR_MAP_H
    h = mh + BOR_KEY_H
    pr = map_projection(BOR_CENTER, BOR_FIT, w, mh)
    places = {p["id"]: p for p in tr["places"]}
    areas = {a["id"]: a for a in tr["areas"]}
    ink, muted, strip_c, land_c = t["ink"], t["muted"], t["z-n"], t["z-t"]
    l48 = next(ln for ln in tr["lines"] if ln["id"] == "border1848")
    hatch = (
        '<pattern id="strip" width="6" height="6" patternUnits="userSpaceOnUse" '
        f'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="{strip_c}" '
        'stroke-width="2.2"/></pattern>'
    )
    b = map_base(t, w, mh, pr, [hatch, arrow_marker("head-land", land_c, 5)])
    strip = [pr(lon, lat) for lon, lat in gadsden_strip(tr)]
    b += [
        '<g clip-path="url(#landclip)">',
        f'<g fill="{land_c}" opacity=".42" filter="url(#soft)">'
        f"{blobs_d(pr, areas['tohono_oodham']['blobs'])}</g>",
        f'<path d="{path_d(strip, True)}" fill="url(#strip)" opacity=".55"/>',
        region_blob(pr, places["gila_villages"], land_c, 0.5),
        "</g>",
    ]
    b += map_coast(t, pr, w, mh)
    b.append('<g clip-path="url(#frame)">')
    b += rivers_layer(t, pr, tr, ["rio_grande", "gila"])
    b.append(
        f'<path d="{border_d(pr, ("MEX", "USA"))}" fill="none" stroke="{ink}" '
        'stroke-width="1.8" stroke-linejoin="round"/>'
    )
    b.append(
        f'<path d="{path_d([pr(*q) for q in l48["coords"]])}" fill="none" stroke="{ink}" '
        'stroke-width="2" stroke-dasharray="7 4" stroke-linejoin="round"/>'
    )
    b.append("</g>")

    # паломничество — направление
    pil = next(m for m in tr["moves"] if m["id"] == "salt_pilgrimage")
    xa, ya = pr(-112.15, 31.55)
    xz, yz = pr(places[pil["to"]]["lon"], places[pil["to"]]["lat"])
    b.append(move_path(xa, ya, xz, yz, 0.18, land_c, 2.4, "6 4", "head-land", 4, 6))

    # подписи
    def lab(lon, lat, rows, anchor="start", size=12.5):
        x, y = pr(lon, lat)
        return label_lines(x, y, rows, t, anchor, size, 14)

    b += lab(
        -116.5,
        33.2,
        [
            ("граница 1848 г. — по Хиле", ink, 700),
            ("по ст. V договора Гуадалупе-Идальго", muted, 400),
        ],
    )
    b += lab(
        -109.2,
        31.1,
        [("граница с 1854 г. — нынешняя", ink, 700), ("по ст. I договора Гадсдена", muted, 400)],
    )
    b += lab(
        -110.7,
        32.55,
        [
            ("полоса покупки Гадсдена", strip_c, 700),
            ("подписан 30 декабря 1853 г.,", muted, 400),
            ("в силу — 1854 г.", muted, 400),
        ],
    )
    b += lab(
        -111.25,
        30.68,
        [
            ("земли тохоно-оодхам", land_c, 700),
            ("по обе стороны границы, около 100 км", muted, 400),
            ("вдоль неё; резервация ≈1,1 млн га —", muted, 400),
            ("лишь часть родовых земель", muted, 400),
        ],
    )
    gv = places["gila_villages"]
    b += lab(
        gv["lon"] - 0.1,
        gv["lat"] + 0.55,
        [("долина Хилы: деревни", ink, 700), ("акимел-оодхам отошли США", muted, 400)],
    )
    xg, yg = pr(-113.55, 31.0)
    b.append(text(xg, yg, "паломники — к заливу", ink, 12, "end", 600, halo=t["bg"]))
    b.append(text(xg, yg + 14, "за солью и раковинами", muted, 11.5, "end", halo=t["bg"]))
    b.append(sea_label(pr, -114.1, 30.45, "Калифорнийский залив", t, 13))
    b.append(sea_label(pr, -116.9, 31.2, "Тихий", t, 13))
    b.append(sea_label(pr, -116.9, 30.95, "океан", t, 13))
    for s1, lon, lat in (("США", -107.9, 33.75), ("Мексика", -107.4, 30.55)):
        x, y = pr(lon, lat)
        b.append(text(x, y, s1, muted, 15, "middle", 600, halo=t["bg"]))
    for s1, lon, lat, rot in (("Рио-Гранде", -106.6, 33.3, -84), ("Колорадо", -114.95, 32.2, -60)):
        x, y = pr(lon, lat)
        b.append(
            f'<g transform="translate({x:.1f},{y:.1f}) rotate({rot})">'
            + text(0, 0, s1, land_c, 11.5, "middle", italic=True, halo=t["bg"])
            + "</g>"
        )
    b.append(text(20, 34, "Схема: линии условные", ink, 20, "start", 700, halo=t["bg"]))
    b.append(
        text(
            20,
            54,
            "граница США и Мексики в 1848 г. и после покупки Гадсдена",
            ink,
            13.5,
            halo=t["bg"],
        )
    )
    b.append(
        f'<rect x=".5" y=".5" width="{w - 1}" height="{mh - 1}" fill="none" stroke="{t["rule"]}"/>'
    )

    # легенда
    ky0 = mh + 26
    rows = [
        ("l48", "граница 1848 г. — по описанию договора"),
        ("l53", "граница с 1854 г. — нынешняя"),
        ("strip", "полоса, купленная по договору Гадсдена"),
        ("land", "земли оодхам — размыто, без границ"),
        ("move", "направление, а не путь"),
        ("river", "реки — для ориентира"),
    ]
    for k, (kind, s1) in enumerate(rows):
        lx = 20 + (k // 3) * 372
        yy = ky0 + (k % 3) * 22
        if kind == "l48":
            b.append(line(lx, yy, lx + 26, yy, ink, 2, "7 4"))
        elif kind == "l53":
            b.append(line(lx, yy, lx + 26, yy, ink, 1.8))
        elif kind == "strip":
            b.append(rect(lx, yy - 7, 26, 14, "url(#strip)", 0, 0.55))
        elif kind == "land":
            b.append(
                f'<ellipse cx="{lx + 13}" cy="{yy}" rx="13" ry="7" fill="{land_c}" opacity=".45" '
                'filter="url(#soft-key)"/>'
            )
        elif kind == "move":
            b.append(
                f'<path d="M{lx},{yy}L{lx + 22},{yy}" stroke="{land_c}" stroke-width="2.4" '
                'stroke-dasharray="6 4" marker-end="url(#head-land)"/>'
            )
        else:
            b.append(line(lx, yy, lx + 26, yy, land_c, 1.3, opacity=0.55))
        b.append(text(lx + 36, yy + 4, s1, ink, 12.5))
    notes = [
        "Линия 1848 г.: вверх по Рио-Гранде до южной границы Нью-Мексико, по ней на запад, на "
        "север до Хилы и по Хиле",
        "до Колорадо. Границы Нью-Мексико договор берёт с карты 1847 г.; здесь эти отрезки "
        "условные. По Хиле — по линии реки.",
        "Западнее Колорадо и ниже Эль-Пасо обе линии совпадают. Пятна земель оодхам — схема.",
    ]
    for k, s1 in enumerate(notes):
        b.append(text(20, ky0 + 74 + k * 15, s1, muted, 11.5))
    return svg(
        w,
        h,
        t,
        b,
        "Граница поперёк земли оодхам (схема: линии условные)",
        "Карта юга Аризоны и Нью-Мексико и севера Соноры и Чиуауа. Пунктиром — граница 1848 г. "
        "по ст. V договора Гуадалупе-Идальго: вверх по Рио-Гранде от Эль-Пасо, условно на запад "
        "и на север до Хилы, по Хиле до Колорадо. Сплошной линией — нынешняя граница, "
        "проведённая по ст. I договора Гадсдена (подписан 30 декабря 1853 г., в силу — 1854 г.). "
        "Штриховкой между ними — полоса покупки Гадсдена; в ней долина Хилы с деревнями "
        "акимел-оодхам. Размытым пятном по обе стороны нынешней границы — земли тохоно-оодхам: "
        "около 100 км вдоль границы; резервация около 1,1 млн га — лишь часть родовых земель. "
        "Стрелка от них — к Калифорнийскому заливу: паломники ходят за солью и раковинами. "
        "Схема: линии условные.",
    )


FIGURES: dict[str, Callable[[dict], str]] = {
    "00-radiocarbon": fig_radiocarbon,
    "00-precision": fig_precision,
    "01-routes": fig_routes,
    "01-timeline": fig_timeline,
    "01-ancestry": fig_ancestry,
    "02-centers": fig_centers,
    "02-lag": fig_lag,
    "02-sisters": fig_sisters,
    "03-modes": fig_modes,
    "03-routes": fig_routes3,
    "03-people": fig_people,
    "03-sea": fig_sea,
    "03-population": fig_population,
    "03-inca-chronology": fig_inca,
    "04-zones": fig_zones,
    "04-canals": fig_canals,
    "04-mesaverde": fig_mesaverde,
    "04-migrations": fig_migrations,
    "04-chichimeca": fig_chichimeca,
    "04-jemez": fig_jemez,
    "04-revolt": fig_revolt,
    "04-peace": fig_peace,
    "04-border": fig_border,
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
