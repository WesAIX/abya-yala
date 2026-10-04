#!/usr/bin/env bash
# PreToolUse на Bash: не дать закоммитить репозиторий с ошибками проверок.
# Второй рубеж после .githooks/pre-commit — ловит и --no-verify.
set -uo pipefail
. "$(dirname "$0")/lib.sh"

cmd=$(python3 -c 'import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
print((d.get("tool_input") or {}).get("command") or "")' 2>/dev/null)

# commit должен идти после git внутри одной команды
printf '%s' "$cmd" | grep -qE 'git\b[^;&|]*[[:space:]]+commit([[:space:]]|$)' || exit 0
root=$(repo_root) || exit 0
uv=$(find_uv) || exit 0

if out=$(run_checks "$root" "$uv" full); then
  exit 0
fi
printf '%s' "$out" | python3 -c 'import json,sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
  "permissionDecisionReason": "Проверки не проходят, коммит остановлен. Почини и повтори:\n" + sys.stdin.read().strip()}}))'
