"""Проверка данных и текстов: схема, ссылочная целостность, покрытие источниками.

uv run tools/validate.py            # ошибки → код 1, покрытие — отчёт
uv run tools/validate.py --strict   # отсутствие источников — тоже ошибка
"""

import argparse
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCHEMA = DATA / "schema"
BIB = ROOT / "sources" / "bibliography.json"
TEXTS = [*sorted((ROOT / "chapters").glob("*.md")), ROOT / "glossary.md", ROOT / "README.md"]
FOOTNOTE = re.compile(r"\[\^([a-z][a-z0-9_-]*)\]")


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def check_schema(doc, schema_path: Path, label: str) -> list[str]:
    validator = Draft202012Validator(load(schema_path))
    return [
        f"{label}: {'/'.join(map(str, e.absolute_path)) or '<корень>'}: {e.message}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path])
    ]


def check_bibliography(bib) -> tuple[list[str], set[str]]:
    errors = check_schema(bib, SCHEMA / "bibliography.schema.json", "bibliography")
    keys: set[str] = set()
    for entry in bib.get("entries", []):
        key = entry.get("key")
        if key in keys:
            errors.append(f"bibliography: ключ {key!r} повторяется")
        keys.add(key)
    return errors, keys


def iter_sourced(g):
    """Все записи графа, у которых есть поле sources: (метка, запись)."""
    for n in g["nodes"]:
        yield f"узел {n['id']}", n
        for ev in n["events"]:
            yield f"событие {n['id']}@{ev['year']}", ev
    for link in g["links"]:
        yield f"связь {link['from']}→{link['to']}", link
    for m in g["milestones"]:
        yield f"веха {m['year']}", m


def check_genealogy(g, bib_keys: set[str]) -> list[str]:
    errors = check_schema(g, SCHEMA / "genealogy.schema.json", "genealogy")
    if errors:
        return errors  # дальнейшие проверки полагаются на корректную структуру

    lanes = {lane["id"] for lane in g["lanes"]}
    ids: set[str] = set()
    for n in g["nodes"]:
        if n["id"] in ids:
            errors.append(f"genealogy: id {n['id']!r} повторяется")
        ids.add(n["id"])

    for n in g["nodes"]:
        where = f"genealogy: узел {n['id']}"
        if n["lane"] not in lanes:
            errors.append(f"{where}: неизвестный регион {n['lane']!r}")
        for p in n["parents"]:
            if p["id"] not in ids:
                errors.append(f"{where}: неизвестный родитель {p['id']!r}")
        end = n["end"]
        if end is None and n["fate"] != "extant":
            errors.append(f"{where}: end = null, но fate = {n['fate']!r}")
        if end is not None:
            if n["fate"] == "extant":
                errors.append(f"{where}: fate = extant, но указан конец {end['year']}")
            if end["year"] < n["start"]["year"]:
                errors.append(f"{where}: конец раньше начала")

    for link in g["links"]:
        for side in ("from", "to"):
            if link[side] not in ids:
                errors.append(f"genealogy: связь: неизвестный узел {link[side]!r}")

    errors += check_cycles(g["nodes"])

    for label, rec in iter_sourced(g):
        for s in rec["sources"]:
            if s["ref"] not in bib_keys:
                errors.append(f"genealogy: {label}: ссылка на неизвестный источник {s['ref']!r}")
    return errors


def check_cycles(nodes) -> list[str]:
    parents = {n["id"]: [p["id"] for p in n["parents"]] for n in nodes}
    state: dict[str, int] = {}  # 1 — в обходе, 2 — проверен
    errors: list[str] = []

    def visit(nid: str, path: list[str]) -> None:
        if state.get(nid) == 2:
            return
        if state.get(nid) == 1:
            errors.append("genealogy: цикл в родословной: " + " → ".join([*path, nid]))
            return
        state[nid] = 1
        for p in parents.get(nid, []):
            visit(p, [*path, nid])
        state[nid] = 2

    for nid in parents:
        visit(nid, [])
    return errors


def check_texts(bib_keys: set[str]) -> list[str]:
    """Сноски [^ключ] в главах и глоссарии должны указывать на запись библиографии."""
    errors = []
    for path in TEXTS:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for key in FOOTNOTE.findall(line):
                if key not in bib_keys:
                    rel = path.relative_to(ROOT)
                    errors.append(f"{rel}:{lineno}: сноска на неизвестный источник {key!r}")
    return errors


def coverage(g) -> list[tuple[str, int, int]]:
    rows: dict[str, list[int]] = {}
    for label, rec in iter_sourced(g):
        kind = label.split()[0]
        row = rows.setdefault(kind, [0, 0])
        row[0] += bool(rec["sources"])
        row[1] += 1
    return [(k, done, total) for k, (done, total) in rows.items()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="требовать источник у каждой записи")
    args = ap.parse_args()

    bib_errors, bib_keys = check_bibliography(load(BIB))
    g = load(DATA / "genealogy.json")
    errors = bib_errors + check_genealogy(g, bib_keys) + check_texts(bib_keys)

    for e in errors:
        print(f"ОШИБКА  {e}")

    if not errors:
        print("genealogy.json: покрытие источниками")
        missing = 0
        for kind, done, total in coverage(g):
            print(f"  {kind:<8} {done:>4} / {total:<4}")
            missing += total - done
        todo = sum(len(rec.get("todo", [])) for _, rec in iter_sourced(g))
        print(f"  открытых пометок todo: {todo}")
        if args.strict and missing:
            print(f"ОШИБКА  --strict: без источника {missing} записей")
            return 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
