"""Сборка сайта в _site/: статические файлы + главы, глоссарий и библиография в HTML.

    uv run tools/build_site.py                 # собрать _site/
    uv run tools/build_site.py --drafts        # то же с черновиками — только для предпросмотра
    uv run python -m http.server -d _site   # посмотреть на http://localhost:8000/

Markdown в репозитории — единственный источник текста; HTML генерируется
только здесь и не коммитится. На сайт попадают главы со статусом «принято»
или «готово»; планы и черновики остаются только на GitHub. Глоссарий и
библиография публикуются всегда.
"""

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path
from string import Template
from urllib.parse import unquote

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.footnote import footnote_plugin

from claims import audit_status
from glossary_terms import slug, terms

ROOT = Path(__file__).resolve().parent.parent
CHAPTERS_DIR = ROOT / "chapters"
GH_BLOB = "https://github.com/WesAIX/abya-yala/blob/main/"
GH_EDIT = "https://github.com/WesAIX/abya-yala/edit/main/"
STATIC = ["index.html", "visuals", "data"]
PUBLISHED = {"принято", "готово"}

STATUS_RE = re.compile(r"^>\s*\*\*Статус:\*\*\s*([а-яё]+)[^\n]*(?:\n>[^\n]*)*\n*", re.M)
TITLE_RE = re.compile(r"^#\s+(.+)\n+", re.M)
FOOTDEF_RE = re.compile(r"^\[\^([a-z][a-z0-9_-]*)\]:\s*(.*)$", re.M)
ALERT_RE = re.compile(
    r"<blockquote>\n<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\n(.*?)</blockquote>", re.S
)
HREF_RE = re.compile(r'href="([^"#]*)(#[^"]*)?"')
TERM_A_RE = re.compile(r'<a href="([^"#]*glossary\.md)#([^"]+)">')
TERMS = terms()


def markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    md.use(footnote_plugin)
    # якоря заголовков — как у GitHub, чтобы ссылки вида glossary.md#термин работали везде
    md.use(anchors_plugin, min_level=2, max_level=3, slug_func=slug)

    def footnote_ref(self, tokens, idx, options, env):
        meta = tokens[idx].meta
        n = meta["id"] + 1
        ref_id = f"fnref{n}" + (f":{meta['subId']}" if meta["subId"] > 0 else "")
        return f'<sup class="fn"><a href="#fn{n}" id="{ref_id}">{n}</a></sup>'

    md.add_render_rule("footnote_ref", footnote_ref)
    return md


MD = markdown()


# ── Главы


def chapters(drafts: bool = False) -> list[dict]:
    out = []
    for path in sorted(CHAPTERS_DIR.glob("[0-9][0-9]-*.md")):
        text = path.read_text(encoding="utf-8")
        title = TITLE_RE.search(text).group(1).strip()
        status = STATUS_RE.search(text)
        out.append(
            {
                "n": int(path.name[:2]),
                "slug": path.stem,
                "title": re.sub(r"^\d+\.\s*", "", title),
                "status": status.group(1) if status else "план",
                "path": path,
            }
        )
    for c in out:
        c["published"] = c["status"] in PUBLISHED or (drafts and c["status"] == "черновик")
        c["url"] = (
            f"chapters/{c['slug']}.html" if c["published"] else f"{GH_BLOB}chapters/{c['slug']}.md"
        )
    return out


def footnote_keys(text: str) -> list[str]:
    return [m.group(1) for m in FOOTDEF_RE.finditer(text)]


def source_note(path: Path, keys: list[str], bib: dict) -> str:
    """Честная отметка о сверке: утверждения — по журналу сверки, издания — по библиографии."""
    if not keys:
        return "Ссылок на источники в главе пока нет."
    st = audit_status(path)
    v = list(st["verdicts"].values())
    ok = v.count("подтверждено")
    bad = v.count("расходится") + v.count("неверная атрибуция")
    unk = v.count("не подтверждено")
    left = len(st["missing"]) + len(st["stale"])
    parts = [f"По текстам источников подтверждено {ok} из {st['total']} утверждений со сносками"]
    if bad:
        parts.append(f"расходятся с источником — {bad}")
    if unk:
        parts.append(f"проверить не удалось (нет доступа к тексту) — {unk}")
    if left:
        parts.append(f"ещё не сверялись — {left}")
    books = sum(bib.get(k, {}).get("checked", False) for k in keys)
    return "; ".join(parts) + f". Описания изданий сверены с каталогами: {books} из {len(keys)}."


# ── Преобразование Markdown → HTML


def render(text: str, link_map, depth: int) -> str:
    up = "../" * depth
    # сноски-ключи ведут в библиографию на сайте
    text = FOOTDEF_RE.sub(
        lambda m: (
            f"[^{m.group(1)}]: {m.group(2)} "
            f'<a class="bib" href="{up}bibliography.html#{m.group(1)}">в библиографии</a>'
        ),
        text,
    )
    out = MD.render(text)

    def alert(m):
        kind = m.group(1).lower()
        return f'<aside class="callout {kind}">\n<p>{m.group(2)}</aside>'

    out = ALERT_RE.sub(alert, out)

    def term(m):
        # ссылка на статью глоссария → термин с подсказкой; адрес поправит HREF_RE ниже
        t = TERMS.get(unquote(m.group(2)))
        if not t:
            return m.group(0)
        attrs = f'data-title="{html.escape(t["title"])}" data-def="{html.escape(t["definition"])}"'
        return f'<a class="term" {attrs} href="{m.group(1)}#{m.group(2)}">'

    out = TERM_A_RE.sub(term, out)

    def href(m):
        target, frag = m.group(1), m.group(2) or ""
        return f'href="{link_map(target, frag)}"'

    out = HREF_RE.sub(href, out)
    out = out.replace("<table>", '<div class="table"><table>').replace("</table>", "</table></div>")
    return out


def make_link_map(source: Path, chapters_by_file: dict, depth: int):
    """Ссылки между .md в репозитории → страницы сайта или GitHub."""
    up = "../" * depth

    def link_map(target: str, frag: str) -> str:
        if not target or re.match(r"^[a-z]+:", target):
            return target + frag
        resolved = (source.parent / target).resolve()
        rel = resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else target
        if rel == "glossary.md":
            return f"{up}glossary.html{frag}"
        if rel == "sources/BIBLIOGRAPHY.md":
            return f"{up}bibliography.html{frag}"
        if rel == "chapters/README.md" and not frag:
            return f"{up}#chapters"
        if rel in chapters_by_file:
            c = chapters_by_file[rel]
            return (f"{up}{c['url']}" if c["published"] else c["url"]) + frag
        if rel.startswith("visuals/") or rel.startswith("data/"):
            return f"{up}{rel}{frag}"
        return f"{GH_BLOB}{rel}{frag}"

    return link_map


# ── Шаблон страницы


TEMPLATE = Template((Path(__file__).parent / "page.html").read_text(encoding="utf-8"))
NAV = [
    ("chapters", "#chapters", "Главы"),
    ("glossary", "glossary.html", "Глоссарий"),
    ("bibliography", "bibliography.html", "Библиография"),
]


def page(*, title, body, depth, current, source_rel, kicker="", status="", pager="", license_note):
    up = "../" * depth
    links = "".join(
        f'<a href="{up}{href}"'
        + (' aria-current="page"' if key == current else "")
        + f">{label}</a>"
        for key, href, label in NAV
    )
    return TEMPLATE.substitute(
        title=html.escape(title),
        up=up,
        nav=links,
        kicker=f'<p class="kicker">{kicker}</p>' if kicker else "",
        status=status,
        body=body,
        pager=pager,
        license=license_note,
        source=f"{GH_BLOB}{source_rel}",
        edit=f"{GH_EDIT}{source_rel}",
    )


TEXT_LICENSE = "Текст — CC BY-SA 4.0."


def build_chapter(c, chapters_all, bib) -> str:
    text = c["path"].read_text(encoding="utf-8")
    keys = footnote_keys(text)
    text = TITLE_RE.sub("", text, count=1)
    text = STATUS_RE.sub("", text, count=1)
    by_file = {f"chapters/{x['slug']}.md": x for x in chapters_all}
    body = render(text, make_link_map(c["path"], by_file, 1), 1)

    label = {
        "черновик": "Черновик — предпросмотр, на сайте не опубликован",
        "принято": "Глава принята",
        "готово": "Глава готова",
    }[c["status"]]
    status = f'<p class="status"><b>{label}.</b> {source_note(c["path"], keys, bib)}</p>'

    pub = [x for x in chapters_all if x["published"]]
    i = pub.index(c)
    prev_, next_ = (pub[i - 1] if i > 0 else None), (pub[i + 1] if i + 1 < len(pub) else None)
    pager = '<nav class="pager" aria-label="Соседние главы">'
    for cls, ch, label in (("prev", prev_, "← Глава {n}"), ("next", next_, "Глава {n} →")):
        if ch:
            pager += (
                f'<a class="{cls}" href="{ch["slug"]}.html">'
                f"<small>{label.format(n=ch['n'])}</small>{html.escape(ch['title'])}</a>"
            )
    pager += "</nav>"
    return page(
        title=c["title"],
        body=body,
        depth=1,
        current="chapters",
        source_rel=f"chapters/{c['slug']}.md",
        kicker=f"Глава {c['n']}",
        status=status,
        pager=pager,
        license_note=TEXT_LICENSE,
    )


def build_reference(src: Path, current: str, chapters_all, license_note: str) -> str:
    text = src.read_text(encoding="utf-8")
    title = TITLE_RE.search(text).group(1).strip()
    text = TITLE_RE.sub("", text, count=1)
    by_file = {f"chapters/{x['slug']}.md": x for x in chapters_all}
    body = render(text, make_link_map(src, by_file, 0), 0)
    return page(
        title=title,
        body=body,
        depth=0,
        current=current,
        source_rel=src.relative_to(ROOT).as_posix(),
        license_note=license_note,
    )


def build(out: Path, drafts: bool = False) -> list[dict]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in STATIC:
        src = ROOT / name
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, out / name)
    (out / "sources").mkdir()
    shutil.copy2(ROOT / "sources" / "bibliography.json", out / "sources" / "bibliography.json")

    bib = {
        e["key"]: e
        for e in json.loads((ROOT / "sources" / "bibliography.json").read_text(encoding="utf-8"))[
            "entries"
        ]
    }
    all_ch = chapters(drafts)
    (out / "chapters").mkdir()
    if (CHAPTERS_DIR / "img").exists():
        shutil.copytree(CHAPTERS_DIR / "img", out / "chapters" / "img")
    for c in all_ch:
        if c["published"]:
            (out / "chapters" / f"{c['slug']}.html").write_text(
                build_chapter(c, all_ch, bib), encoding="utf-8"
            )

    (out / "glossary.html").write_text(
        build_reference(ROOT / "glossary.md", "glossary", all_ch, TEXT_LICENSE), encoding="utf-8"
    )
    (out / "bibliography.html").write_text(
        build_reference(
            ROOT / "sources" / "BIBLIOGRAPHY.md", "bibliography", all_ch, "Данные — CC BY 4.0."
        ),
        encoding="utf-8",
    )
    index = [
        {k: c[k] for k in ("n", "slug", "title", "status", "published", "url")} for c in all_ch
    ]
    (out / "chapters.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return all_ch


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument(
        "--out", type=Path, default=ROOT / "_site", help="куда собирать (по умолчанию _site/)"
    )
    ap.add_argument(
        "--drafts",
        action="store_true",
        help="включить черновики — только для локального предпросмотра, не для публикации",
    )
    args = ap.parse_args()
    all_ch = build(args.out, args.drafts)
    pub = [c for c in all_ch if c["published"]]
    print(
        f"{args.out}: глав на сайте {len(pub)} из {len(all_ch)}; глоссарий и библиография — всегда"
    )
    for c in all_ch:
        mark = "на сайте" if c["published"] else "только GitHub"
        print(f"  {c['n']:>2}. {c['title']} — {c['status']} ({mark})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
