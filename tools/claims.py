"""Утверждения главы, подлежащие сверке с источниками.

    uv run tools/claims.py chapters/00-metodika.md          # список для чтения
    uv run tools/claims.py chapters/00-metodika.md --json   # для журнала сверки
    uv run tools/claims.py chapters/00-metodika.md --unsourced   # только рискованное без сносок

Утверждение — предложение со сноской [^ключ]. Его идентификатор — «ключ#n»,
n-е по порядку использование этого ключа в главе; по нему журнал сверки
(sources/audits/<глава>.json) привязывает вердикт к месту в тексте.

Отдельно скрипт показывает предложения без сноски, в которых есть то, что
чаще всего оказывается ошибкой: годы и числа, превосходные степени («первый»,
«крупнейший», «последний»), цитаты. Он грубый и намеренно шумный: пропустить
факт хуже, чем показать лишнее, поэтому список разбирается глазами.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FOOTREF = re.compile(r"\[\^([a-z][a-z0-9_-]*)\](?!:)")
FOOTDEF = re.compile(r"^\[\^[^\]]+\]:.*$", re.M)
RISKY = [
    ("год", re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\s*(?:г\.|года|году|гг\.)|\bдо н\. э\.|\bвв?\.")),
    ("число", re.compile(r"\b\d[\d\s,.]*\s*(?:тыс\.|млн|процент|%|человек|км|лет)")),
    (
        "превосходная степень",
        re.compile(
            r"\b(?:перв(?:ый|ая|ое|ые|ым|ой)|последн\w+|крупнейш\w+|древнейш\w+|"
            r"единственн\w+|впервые|самы[йея]\s+\w+)",
            re.I,
        ),
    ),
    ("цитата", re.compile(r"«[^»]{25,}»")),
]


def prose(text: str) -> str:
    """Текст главы без шапки статуса, кода, HTML-вставок и определений сносок."""
    text = re.sub(r"^>\s*\*\*Статус:\*\*.*(?:\n>.*)*", "", text, flags=re.M)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"<picture>.*?</picture>", "", text, flags=re.S)
    text = FOOTDEF.sub("", text)
    return text


def plain(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`]|^>\s*|\[!\w+\]|^\s*(?:-|\d+\.)\s+", "", s, flags=re.M)
    return re.sub(r"\s+", " ", s).strip()


def sentences(text: str) -> list[tuple[int, str]]:
    """(номер строки, предложение) — абзацы режутся на предложения грубо, по точке."""
    out = []
    for block in re.finditer(r"(?:^(?!#|\|)[^\n]+\n?)+", text, re.M):
        start = text[: block.start()].count("\n") + 1
        para = block.group(0)
        pos = 0
        # конец предложения: точка (или «]» сноски после неё), пробел, заглавная буква
        for m in re.finditer(
            r"(?<=[.!?»\]])\s+(?=[А-ЯЁA-Z«(\[\d])|\n(?=\s*(?:[-*]|\d+\.)\s)|$", para
        ):
            chunk = para[pos : m.start()]
            if chunk.strip():
                out.append((start + para[:pos].count("\n"), chunk.strip()))
            pos = m.end()
    return out


def claims(path: Path) -> tuple[list[dict], list[dict]]:
    text = prose(path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    sourced, unsourced = [], []
    for line, s in sentences(text):
        keys = FOOTREF.findall(s)
        clean = plain(FOOTREF.sub("", s))
        if keys:
            for k in keys:
                counts[k] = counts.get(k, 0) + 1
                sourced.append({"id": f"{k}#{counts[k]}", "ref": k, "line": line, "text": clean})
        else:
            kinds = [name for name, rx in RISKY if rx.search(clean)]
            if kinds:
                unsourced.append({"line": line, "kinds": kinds, "text": clean})
    return sourced, unsourced


AUDITS = ROOT / "sources" / "audits"


def audit_status(path: Path) -> dict:
    """Состояние сверки главы по журналу: что подтверждено, что спорно, что не сверено.

    Вердикт засчитывается, только если предложение в главе не изменилось с момента
    сверки; иначе запись считается устаревшей.
    """
    current = {c["id"]: c for c in claims(path)[0]}
    log = AUDITS / f"{path.stem}.json"
    entries = json.loads(log.read_text(encoding="utf-8"))["claims"] if log.exists() else []
    by_id = {e["id"]: e for e in entries}
    # номер «ключ#n» сдвигается, если ту же сноску поставили выше по тексту, —
    # поэтому вердикт ищется и по самой фразе с тем же ключом
    by_text = {(e["ref"], e["text"]): e for e in entries}
    status = {"total": len(current), "verdicts": {}, "stale": [], "orphan": [], "missing": []}
    used = set()
    for cid, c in current.items():
        e = by_id.get(cid)
        if not e or e["text"] != c["text"]:
            e = by_text.get((c["ref"], c["text"])) or e
        if not e:
            status["missing"].append(cid)
        elif e["text"] != c["text"]:
            status["stale"].append(cid)
        else:
            status["verdicts"][cid] = e["verdict"]
            used.add(e["id"])
    current_texts = {(c["ref"], c["text"]) for c in current.values()}
    status["orphan"] = [
        e["id"]
        for e in entries
        if e["id"] not in used and (e["ref"], e["text"]) not in current_texts
    ]
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("chapter", type=Path)
    ap.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    ap.add_argument("--unsourced", action="store_true", help="только предложения без сносок")
    args = ap.parse_args()
    sourced, unsourced = claims(args.chapter)
    if args.json:
        print(json.dumps({"claims": sourced, "unsourced": unsourced}, ensure_ascii=False, indent=1))
        return 0
    if not args.unsourced:
        print(f"Утверждения со сносками: {len(sourced)}")
        for c in sourced:
            print(f"  {c['id']:<22} стр. {c['line']:>3}  {c['text']}")
        print()
    print(
        f"Без сноски, но с годами, числами, превосходными степенями или цитатами: {len(unsourced)}"
    )
    for c in unsourced:
        print(f"  стр. {c['line']:>3}  [{', '.join(c['kinds'])}]  {c['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
