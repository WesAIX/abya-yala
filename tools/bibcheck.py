"""Сверка описаний изданий в sources/bibliography.json с каталогами.

    uv run tools/bibcheck.py --chapter chapters/00-metodika.md   # только источники главы
    uv run tools/bibcheck.py --key jones2003 --key vansina1985   # отдельные записи
    uv run tools/bibcheck.py --all                               # вся библиография
    ... --apply   # записать checked: true там, где описание совпало полностью

Статьи сверяются с Crossref (по DOI) или OpenAlex (поиск по заглавию), книги —
с Open Library. Совпадением считается совпадение заглавия, года, фамилии первого
автора, а у статей ещё тома и страниц. Всё остальное — расхождение или «не
найдено», и решение принимает человек или агент source-audit: скрипт ничего
не исправляет в описаниях, он только отмечает полностью совпавшие.
Рукописи и издания без точного года в каталогах не ищутся — их сверяют вручную.
Нужна сеть.
"""

import argparse
import datetime as dt
import difflib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIB = ROOT / "sources" / "bibliography.json"
UA = "abya-yala-bibcheck/1.0 (https://github.com/WesAIX/abya-yala)"
FOOTDEF = re.compile(r"^\[\^([a-z][a-z0-9_-]*)\]:", re.M)
RU_LAT = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        [
            "a",
            "b",
            "v",
            "g",
            "d",
            "e",
            "e",
            "zh",
            "z",
            "i",
            "y",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "r",
            "s",
            "t",
            "u",
            "f",
            "kh",
            "ts",
            "ch",
            "sh",
            "shch",
            "",
            "y",
            "",
            "e",
            "yu",
            "ya",
        ],
        strict=True,
    )
)


def get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception:  # недоступный каталог — это «не найдено», а не падение
        return None


def norm(s: str) -> str:
    s = s.lower().replace("ё", "е").replace("'", "").replace("’", "")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def translit(s: str) -> str:
    """Кириллица → латиница, грубо: чтобы «Кнорозов» совпал с «Knorozov» в каталоге."""
    return "".join(RU_LAT.get(ch, ch) for ch in s.lower())


def title_sim(a: str, b: str) -> float:
    """Похожесть заглавий; подзаголовок после двоеточия может отсутствовать в каталоге."""
    cands_a = {norm(a), norm(a.split(":")[0])}
    cands_b = {norm(b), norm(b.split(":")[0])}
    return max(difflib.SequenceMatcher(None, x, y).ratio() for x in cands_a for y in cands_b)


def family(author: str) -> str:
    return norm(author.split(",")[0].replace("(ред.)", ""))


def same_family(ours: str, theirs: str) -> bool:
    """Фамилия первого автора — с учётом транслитерации кириллицы."""
    a, name = family(ours), f" {norm(theirs)} "
    return f" {a} " in name or f" {translit(a)} " in name


def pages(s: str | None) -> str:
    return re.sub(r"[–—-]+", "-", s or "").strip()


def is_article(e: dict) -> bool:
    return bool(e.get("container") and e.get("volume") and e.get("pages"))


# ── Каталоги. Найденное приводится к одному виду: title, year, authors, volume, issue, page, doi


def crossref_doi(doi: str) -> dict | None:
    m = (get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}") or {}).get("message")
    if not m:
        return None
    return {
        "title": (m.get("title") or [""])[0],
        "year": (m.get("issued", {}).get("date-parts") or [[None]])[0][0],
        "authors": [a.get("family", "") for a in m.get("author", [])],
        "volume": m.get("volume") or "",
        "issue": m.get("issue"),
        "page": m.get("page") or m.get("article-number"),
        "doi": m.get("DOI"),
    }


def openalex(title: str) -> dict | None:
    q = urllib.parse.urlencode({"search": title, "per-page": 5})
    results = (get(f"https://api.openalex.org/works?{q}") or {}).get("results", [])
    r = max(results, key=lambda r: title_sim(title, r.get("title") or ""), default=None)
    if not r:
        return None
    b = r.get("biblio") or {}
    fp, lp = b.get("first_page"), b.get("last_page")
    return {
        "title": r.get("title") or "",
        "year": r.get("publication_year"),
        "authors": [a["author"]["display_name"] for a in r.get("authorships", [])],
        "volume": b.get("volume") or "",
        "issue": b.get("issue"),
        "page": fp if not lp or fp == lp else f"{fp}-{lp}",
        "doi": (r.get("doi") or "").replace("https://doi.org/", "") or None,
    }


def openlibrary(e: dict) -> dict | None:
    q = urllib.parse.urlencode(
        {"title": e["title"].split(":")[0], "author": family(e["authors"][0]), "limit": 5}
    )
    docs = (get(f"https://openlibrary.org/search.json?{q}") or {}).get("docs", [])
    d = max(docs, key=lambda x: title_sim(e["title"], x.get("title", "")), default=None)
    if not d:
        return None
    return {
        "title": d.get("title", ""),
        "years": sorted({*d.get("publish_year", []), d.get("first_publish_year")} - {None}),
        "authors": d.get("author_name", []),
    }


# ── Сравнение


def compare(e: dict, f: dict, article: bool) -> list[str]:
    diffs = []
    if title_sim(e["title"], f["title"]) < 0.9:
        diffs.append(f"заглавие в каталоге: «{f['title']}»")
    if article:
        if f["year"] != e["year"]:
            diffs.append(f"год в каталоге: {f['year']}")
    elif e["year"] not in f["years"]:
        diffs.append(f"года изданий в каталоге: {f['years'][:8]}")
    names = f["authors"][:1] if article else f["authors"]
    if not any(same_family(e["authors"][0], n) for n in names):
        diffs.append(f"авторы в каталоге: {f['authors'][:3]}")
    if article:
        vol = f["volume"] + (f"({f['issue']})" if f.get("issue") else "")
        if e["volume"] not in (vol, f["volume"]):
            diffs.append(f"том в каталоге: {vol or '—'}")
        if pages(e["pages"]) != pages(f.get("page")):
            diffs.append(f"страницы в каталоге: {f.get('page') or '—'}")
    return diffs


def check(e: dict) -> dict:
    if e["kind"] == "dataset" or not isinstance(e["year"], int):
        return {"result": "вручную", "note": "набор данных или издание без точного года"}
    article = is_article(e)
    if article:
        found, via = (crossref_doi(e["doi"]), "Crossref (DOI)") if e.get("doi") else (None, "")
        if not found:
            found, via = openalex(e["title"]), "OpenAlex"
    else:
        found, via = openlibrary(e), "Open Library"
    if not found or title_sim(e["title"], found["title"]) < 0.6:
        note = f"ближайшее в каталоге: «{found['title']}»" if found else ""
        return {"result": "не найдено", "via": via, "note": note}
    diffs = compare(e, found, article)
    out = {"result": "совпадает" if not diffs else "расходится", "via": via, "diffs": diffs}
    if article and found.get("doi") and not e.get("doi") and not diffs:
        out["doi"] = found["doi"]
    return out


def dump(doc: dict) -> str:
    """JSON в стиле файла: короткие списки скаляров — в одну строку."""
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    scalar = r"(?:\"[^\"\n]*\"|-?\d+)"
    return (
        re.sub(
            rf"\[\n\s+((?:{scalar},\n\s+)*{scalar})\n\s+\]",
            lambda m: "[" + re.sub(r",\n\s+", ", ", m.group(1)) + "]",
            text,
        )
        + "\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--chapter", type=Path, help="сверить источники, на которые ссылается глава")
    g.add_argument("--key", action="append", help="ключ записи; можно несколько раз")
    g.add_argument("--all", action="store_true", help="вся библиография")
    ap.add_argument(
        "--apply", action="store_true", help="записать checked: true для полных совпадений"
    )
    args = ap.parse_args()

    doc = json.loads(BIB.read_text(encoding="utf-8"))
    entries = doc["entries"]
    if args.chapter:
        keys = set(FOOTDEF.findall(args.chapter.read_text(encoding="utf-8")))
        entries = [e for e in entries if e["key"] in keys]
    elif args.key:
        entries = [e for e in entries if e["key"] in set(args.key)]

    today = dt.date.today().isoformat()
    changed = 0
    marks = {"совпадает": "✓", "расходится": "≠", "не найдено": "?", "вручную": "·"}
    for e in entries:
        r = check(e)
        via = f" ({r['via']})" if r.get("via") else ""
        print(f"{marks[r['result']]} {e['key']:<18} {r['result']}{via}")
        for line in [*r.get("diffs", []), r.get("note")]:
            if line:
                print(f"      {line}")
        if args.apply and r["result"] == "совпадает" and not e.get("checked"):
            e["checked"], e["checked_via"], e["checked_on"] = True, r["via"], today
            if r.get("doi"):
                e["doi"] = r["doi"]
            changed += 1
        time.sleep(0.4)  # вежливо к открытым API
    if args.apply and changed:
        BIB.write_text(dump(doc), encoding="utf-8")
        print(f"\nОтмечено как сверенное: {changed}. Пересоберите: uv run tools/bibliography.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
