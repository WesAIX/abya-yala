#!/usr/bin/env bash
# PostToolUse на Write|Edit: после правки главы, глоссария, данных или
# библиографии прогнать валидатор и вернуть ошибки в контекст, пока правка
# свежа. Ничего не блокирует.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

file=$(python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
inp = d.get("tool_input") or {}; resp = d.get("tool_response") or {}
print(inp.get("file_path") or resp.get("filePath") or "")' 2>/dev/null)

root=$(repo_root) || exit 0
case "$file" in
  "$root"/chapters/*.md|"$root"/glossary.md|"$root"/data/*.json|"$root"/sources/*.json|"$root"/sources/audits/*.json) ;;
  *) exit 0 ;;
esac
uv=$(find_uv) || exit 0

out=$(run_checks "$root" "$uv")
[ -n "$out" ] || exit 0
printf 'Проверка после правки (tools/validate.py):\n%s\n' "$out" | json_context PostToolUse
