"""Статические рисунки для глав: SVG в двух темах из одного описания.

    uv run tools/figures.py           # перерисовать chapters/img/*.svg
    uv run tools/figures.py --check   # код 1, если файлы устарели (для CI)

Цвета берутся из visuals/shared/tokens.css, чтобы рисунки глав и визуализации
сайта были в одной палитре. Каждый рисунок — функция, которая получает тему
(словарь токенов) и возвращает SVG; в главу он вставляется через <picture>,
чтобы на GitHub показывалась версия под тему читателя.
"""

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "visuals" / "shared" / "tokens.css"
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
    (0.00, 0.95),
    (0.12, 0.84),
    (0.24, 0.72),
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
    (0.78, 0.018, "образец А", "z-t"),
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
    w, h = 760, 430
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
                py(y0 + s) - 6,
                f"{name}: измеренный возраст ± погрешность",
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
    ("Дендрохронология", 0.9, 1.25, "где сохранилась древесина: юго-запад США и др.", False),
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


FIGURES: dict[str, Callable[[dict], str]] = {
    "00-radiocarbon": fig_radiocarbon,
    "00-precision": fig_precision,
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
