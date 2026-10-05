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
from referencing import Registry, Resource

from claims import AUDITS, audit_status
from glossary_terms import TERM_LINK, terms

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SCHEMA = DATA / "schema"
BIB = ROOT / "sources" / "bibliography.json"
CHAPTERS = {int(p.name[:2]): p for p in (ROOT / "chapters").glob("[0-9][0-9]-*.md")}
TEXTS = [*sorted((ROOT / "chapters").glob("*.md")), ROOT / "glossary.md", ROOT / "README.md"]
FOOTNOTE = re.compile(r"\[\^([a-z][a-z0-9_-]*)\]")
IMAGE = re.compile(r"""(?:!\[[^\]]*\]\(([^)\s]+)|(?:src|srcset)=["']([^"'\s]+))""")
STATUS = re.compile(r"\*\*Статус:\*\*\s*([а-яё]+)")
STATUSES = ("план", "черновик", "принято", "готово")  # «принято» и «готово» публикуются на сайте
FOOTDEF = re.compile(r"^\[\^([a-z][a-z0-9_-]*)\]:", re.M)
EXACT_BEFORE = 1500  # раньше этого года точная дата — только из надписи или дендрохронологии


def load(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def registry() -> Registry:
    """Все схемы data/schema по их $id — для ссылок вида genealogy.schema.json#/$defs/…"""
    schemas = [load(p) for p in SCHEMA.glob("*.schema.json")]
    return Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)


REGISTRY = registry()


def check_schema(doc, schema_path: Path, label: str) -> list[str]:
    validator = Draft202012Validator(load(schema_path), registry=REGISTRY)
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


def iter_genealogy(g):
    """Все записи графа, у которых есть поле sources: (метка, запись)."""
    for n in g["nodes"]:
        yield f"узел {n['id']}", n
        for ev in n["events"]:
            yield f"событие {n['id']}@{ev['year']}", ev
    for link in g["links"]:
        yield f"связь {link['from']}→{link['to']}", link
    for m in g["milestones"]:
        yield f"веха {m['year']}", m


def check_genealogy(g) -> list[str]:
    errors: list[str] = []
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
        errors += exact_early(n["start"], n["sources"], f"{where} (начало)")
        errors += exact_early(n["end"], n["sources"], f"{where} (конец)")
        for ev in n["events"]:
            errors += exact_early(ev, ev["sources"], f"{where} (событие)")
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
    return errors


def iter_zones(z):
    for zone in z["zones"]:
        yield f"зона {zone['id']}", zone


def check_zones(z) -> list[str]:
    errors = unique([zone["id"] for zone in z["zones"]], "zones: id зоны")
    for zone in z["zones"]:
        errors += check_chapters(zone["chapters"], f"zones: зона {zone['id']}")
    return errors


def iter_theses(t):
    for th in t["theses"]:
        yield f"тезис {th['n']}", th


def check_theses(t) -> list[str]:
    errors = unique([th["n"] for th in t["theses"]], "theses: номер тезиса")
    for th in t["theses"]:
        where = f"theses: тезис {th['n']}"
        errors += check_chapters(th["chapters"], where)
        for d in (th["start"], th["end"], *th["markers"]):
            errors += exact_early(d, th["sources"], where)
        if th["end"] is not None and th["end"]["year"] < th["start"]["year"]:
            errors.append(f"{where}: конец раньше начала")
    return errors


def iter_peopling(p):
    for s in p["sites"]:
        yield f"стоянка {s['id']}", s
    for c in p["corridor"]:
        yield f"коридор {c['id']}", c
    for ev in p["events"]:
        yield f"событие {ev['id']}", ev
    for n in p["lineages"]["nodes"]:
        yield f"линия {n['id']}", n
    for link in p["lineages"]["links"]:
        yield f"связь {link['from']}→{link['to']}", link


def check_peopling(p) -> list[str]:
    """Время — в тыс. лет назад: начало не моложе конца; связи ведут к существующим линиям."""
    errors = unique([s["id"] for s in p["sites"]], "peopling: стоянка")
    errors += unique([c["id"] for c in p["corridor"]], "peopling: точка коридора")
    errors += unique([ev["id"] for ev in p["events"]], "peopling: событие")
    nodes = [n["id"] for n in p["lineages"]["nodes"]]
    errors += unique(nodes, "peopling: линия")
    for label, rec in iter_peopling(p):
        t = rec.get("time")
        if t is None:
            continue
        if t["dating"] == "documented":  # всё в наборе старше 1500 г.
            errors.append(f"peopling: {label}: точная дата до {EXACT_BEFORE} г.")
        if t["to"] is not None and t["to"] > t["from"]:
            errors.append(f"peopling: {label}: конец ({t['to']}) старше начала ({t['from']})")
        if t.get("point") and t["to"] is not None:
            errors.append(f"peopling: {label}: точечная оценка с концом периода")
        if rec.get("contested_since") and not rec.get("contested"):
            errors.append(f"peopling: {label}: contested_since без contested")
    # стоянка на карте и её событие на шкале — одна датировка и один статус спора
    sites = {s["id"]: s for s in p["sites"]}
    for ev in p["events"]:
        site = sites.get(ev["id"])
        if site is None:
            continue
        for field in ("time", "contested", "contested_since"):
            if site.get(field) != ev.get(field):
                errors.append(f"peopling: стоянка и событие {ev['id']!r}: расходится {field}")
    for link in p["lineages"]["links"]:
        for side in ("from", "to"):
            if link[side] not in nodes:
                errors.append(f"peopling: связь: неизвестная линия {link[side]!r}")
        share = link.get("share")
        if share and share["low"] > share["high"]:
            errors.append(f"peopling: связь {link['from']}→{link['to']}: доля low > high")
        if share and link["kind"] != "admixture":
            errors.append(f"peopling: связь {link['from']}→{link['to']}: доля только у смешения")
    return errors


def unique(values: list, what: str) -> list[str]:
    seen: set = set()
    errors = []
    for v in values:
        if v in seen:
            errors.append(f"{what} {v!r} повторяется")
        seen.add(v)
    return errors


def check_chapters(nums: list[int], where: str) -> list[str]:
    return [f"{where}: нет главы {n}" for n in nums if n not in CHAPTERS]


# Набор данных: файл data/<имя>.json, схема data/schema/<имя>.schema.json,
# обход записей с полем sources и собственные проверки.
DATASETS = {
    "genealogy": (iter_genealogy, check_genealogy),
    "zones": (iter_zones, check_zones),
    "theses": (iter_theses, check_theses),
    "peopling": (iter_peopling, check_peopling),
}


def check_dataset(name: str, doc, bib_keys: set[str]) -> list[str]:
    iterate, extra = DATASETS[name]
    errors = check_schema(doc, SCHEMA / f"{name}.schema.json", name)
    if errors:
        return errors  # дальнейшие проверки полагаются на корректную структуру
    errors = extra(doc)
    for label, rec in iterate(doc):
        for s in rec["sources"]:
            if s["ref"] not in bib_keys:
                errors.append(f"{name}: {label}: ссылка на неизвестный источник {s['ref']!r}")
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
    """Сноски ведут в библиографию, ссылки на термины — на существующие статьи глоссария."""
    errors = []
    glossary = terms()
    for path in TEXTS:
        if not path.exists():
            continue
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for key in FOOTNOTE.findall(line):
                if key not in bib_keys:
                    errors.append(f"{rel}:{lineno}: сноска на неизвестный источник {key!r}")
            for anchor in TERM_LINK.findall(line):
                if anchor not in glossary:
                    errors.append(f"{rel}:{lineno}: в глоссарии нет термина с якорем {anchor!r}")
    return errors


def check_images() -> list[str]:
    """Картинки в главах существуют; глава вне статуса «план» обязана иметь иллюстрацию."""
    errors = []
    for num, path in sorted(CHAPTERS.items()):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        refs = [m.group(1) or m.group(2) for m in IMAGE.finditer(text)]
        for ref in refs:
            if ref.startswith(("http://", "https://")):
                continue
            if not (path.parent / ref).exists():
                errors.append(f"{rel}: нет файла иллюстрации {ref!r}")
        status = STATUS.search(text)
        if status and status.group(1) != "план" and not refs:
            errors.append(f"{rel}: глава {num} без иллюстраций — они обязательны (CLAUDE.md)")
    return errors


def check_audits() -> tuple[list[str], list[str]]:
    """Журналы сверки: схема, существование главы; устаревшие записи — предупреждения."""
    errors, warnings = [], []
    for log in sorted(AUDITS.glob("*.json")) if AUDITS.exists() else []:
        rel = log.relative_to(ROOT)
        doc = load(log)
        errors += check_schema(doc, SCHEMA / "audit.schema.json", str(rel))
        chapter = ROOT / "chapters" / f"{log.stem}.md"
        if doc.get("chapter") != log.stem or not chapter.exists():
            errors.append(f"{rel}: нет главы {log.stem}.md или поле chapter не совпадает с файлом")
            continue
        st = audit_status(chapter)
        for cid in st["stale"]:
            warnings.append(
                f"{rel}: {cid} — текст главы изменился после сверки, вердикт не засчитан"
            )
        for cid in st["orphan"]:
            warnings.append(f"{rel}: {cid} — такого утверждения в главе больше нет")
    return errors, warnings


def check_statuses(bib) -> list[str]:
    """Статус главы из списка; «готово» — все описания изданий и все утверждения сверены."""
    checked = {e["key"] for e in bib["entries"] if e.get("checked")}
    errors = []
    for path in CHAPTERS.values():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        m = STATUS.search(text)
        if not m:
            errors.append(f"{rel}: нет строки «**Статус:** …»")
            continue
        if m.group(1) not in STATUSES:
            errors.append(
                f"{rel}: неизвестный статус {m.group(1)!r}; допустимы: {', '.join(STATUSES)}"
            )
        if m.group(1) == "готово":
            unchecked = sorted(set(FOOTDEF.findall(text)) - checked)
            if unchecked:
                errors.append(
                    f"{rel}: статус «готово», но не сверены описания: {', '.join(unchecked)}"
                )
            st = audit_status(path)
            weak = [c for c, v in st["verdicts"].items() if v != "подтверждено"]
            weak += st["missing"] + st["stale"]
            if weak:
                errors.append(f"{rel}: «готово», но не подтверждены по тексту: {', '.join(weak)}")
    return errors


def exact_early(date, sources, where: str) -> list[str]:
    """Точная дата до 1500 г. — только со ссылкой на источник (надпись, дендрохронология)."""
    if date and date["dating"] == "documented" and date["year"] < EXACT_BEFORE and not sources:
        return [f"{where}: точная дата {date['year']} до {EXACT_BEFORE} г. без источника"]
    return []


def coverage(records) -> list[tuple[str, int, int]]:
    rows: dict[str, list[int]] = {}
    for label, rec in records:
        kind = label.split()[0]
        row = rows.setdefault(kind, [0, 0])
        row[0] += bool(rec["sources"])
        row[1] += 1
    return [(k, done, total) for k, (done, total) in rows.items()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="требовать источник у каждой записи")
    args = ap.parse_args()

    errors, bib_keys = check_bibliography(load(BIB))
    unknown = {p.stem for p in DATA.glob("*.json")} - DATASETS.keys()
    errors += [f"data/{name}.json: набор не описан в tools/validate.py" for name in sorted(unknown)]
    docs = {name: load(DATA / f"{name}.json") for name in DATASETS}
    for name, doc in docs.items():
        errors += check_dataset(name, doc, bib_keys)
    errors += check_texts(bib_keys)
    errors += check_images()
    errors += check_statuses(load(BIB))
    audit_errors, warnings = check_audits()
    errors += audit_errors

    for w in warnings:
        print(f"ВНИМАНИЕ  {w}")
    for e in errors:
        print(f"ОШИБКА  {e}")
    if errors:
        return 1

    missing = 0
    print("Покрытие источниками")
    for name, doc in docs.items():
        records = list(DATASETS[name][0](doc))
        todo = sum(len(rec.get("todo", [])) for _, rec in records)
        print(f"  {name}.json (пометок todo: {todo})")
        for kind, done, total in coverage(records):
            print(f"    {kind:<8} {done:>4} / {total:<4}")
            missing += total - done
    print("Сверка глав по текстам источников")
    for path in sorted(CHAPTERS.values()):
        st = audit_status(path)
        if not st["total"]:
            continue
        ok = sum(v == "подтверждено" for v in st["verdicts"].values())
        bad = sum(
            v in ("расходится", "неверная атрибуция") for v in st["verdicts"].values()
        )  # и то и другое — к правке
        print(f"  {path.stem:<28} подтверждено {ok:>3} / {st['total']:<3} к правке {bad}")
    if args.strict and missing:
        print(f"ОШИБКА  --strict: без источника {missing} записей")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
