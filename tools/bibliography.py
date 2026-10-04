"""Генерация sources/BIBLIOGRAPHY.md из sources/bibliography.json.

uv run tools/bibliography.py           # перезаписать BIBLIOGRAPHY.md
uv run tools/bibliography.py --check   # код 1, если файл устарел (для CI)
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "sources" / "bibliography.json"
OUT = ROOT / "sources" / "BIBLIOGRAPHY.md"

SECTIONS = [
    ("primary", "Первичные источники"),
    ("academic", "Исследования"),
    ("dataset", "Наборы данных"),
    ("popular", "Популярные издания"),
]

HEADER = """\
# Библиография

<!-- Файл сгенерирован tools/bibliography.py из bibliography.json. Не править вручную. -->

Все источники, на которые ссылаются главы, глоссарий и данные конспекта. У каждой
записи есть короткое имя — например, `thornton1987`: по нему на неё ссылаются
сноски. Пометка «не сверено» значит, что описание издания (авторы, год, страницы)
записано, но ещё не сверено с самим изданием.
"""


def fmt(e: dict) -> str:
    parts = [f"{'; '.join(e['authors'])} ({e['year']}). *{e['title']}*."]
    if c := e.get("container"):
        vol = f", {e['volume']}" if e.get("volume") else ""
        pages = f", {e['pages']}" if e.get("pages") else ""
        parts.append(f"{c}{vol}{pages}.")
    elif v := e.get("volume"):
        parts.append(f"Т. {v}.")
    if p := e.get("publisher"):
        parts.append(f"{p}.")
    if d := e.get("doi"):
        parts.append(f"doi:{d}.")
    if u := e.get("url"):
        parts.append(f"<{u}>.")
    line = f'- <a id="{e["key"]}"></a>`{e["key"]}` — ' + " ".join(parts)
    extra = []
    if lic := e.get("license"):
        extra.append(f"Лицензия: {lic}.")
    if note := e.get("note"):
        extra.append(note)
    if topics := e.get("topics"):
        extra.append("Главы: " + ", ".join(map(str, topics)) + ".")
    if not e["checked"]:
        extra.append("**Не сверено.**")
    if extra:
        line += "\n  " + " ".join(extra)
    return line


def render(entries: list[dict]) -> str:
    out = [HEADER.rstrip()]
    for kind, title in SECTIONS:
        items = sorted(
            (e for e in entries if e["kind"] == kind),
            key=lambda e: (e["authors"][0], str(e["year"])),
        )
        if items:
            out.append(f"\n## {title}\n")
            out.extend(fmt(e) for e in items)
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--check", action="store_true", help="только проверить актуальность")
    args = ap.parse_args()

    entries = json.loads(SRC.read_text(encoding="utf-8"))["entries"]
    text = render(entries)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("BIBLIOGRAPHY.md устарел: запустите uv run tools/bibliography.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(entries)} записей")
    return 0


if __name__ == "__main__":
    sys.exit(main())
