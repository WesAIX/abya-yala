"""Глоссарий как словарь терминов — общий код сборщика сайта и валидатора.

Термин — подзаголовок третьего уровня в glossary.md; его адрес (якорь)
строится так же, как GitHub строит якоря заголовков, поэтому ссылка
`../glossary.md#глоттохронология` работает и на GitHub, и на сайте.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = ROOT / "glossary.md"
TERM_LINK = re.compile(r"\]\((?:\.\./)?glossary\.md#([^)\s]+)\)")


def slug(heading: str) -> str:
    """Якорь заголовка, как у GitHub: строчные буквы, без пунктуации, пробелы → «-»."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def plain(md: str) -> str:
    """Markdown абзаца → простой текст для всплывающей подсказки."""
    s = re.sub(r"\[\^[^\]]+\]", "", md)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def short(text: str, limit: int = 330) -> str:
    """Первые предложения определения, не длиннее limit знаков."""
    sentences = re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z«(])", text)
    out = ""
    for s in sentences:
        if out and len(out) + 1 + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


def terms() -> dict[str, dict[str, str]]:
    """Якорь → {title, definition}: определение — первый абзац под заголовком."""
    text = GLOSSARY.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^### (.+)\n\n((?:.+\n)+)", text, re.M):
        title = m.group(1).strip()
        out[slug(title)] = {"title": title, "definition": short(plain(m.group(2)))}
    return out
