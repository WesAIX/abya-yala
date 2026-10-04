# Общее для хуков: корень репозитория и uv, где бы он ни стоял.
repo_root() {
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "$CLAUDE_PROJECT_DIR/tools" ]; then
    printf '%s\n' "$CLAUDE_PROJECT_DIR"
    return 0
  fi
  git rev-parse --show-toplevel 2>/dev/null
}

# uv: из PATH или из стандартного места установки. Нет uv — хуки молча
# пропускают проверку: главный рубеж всё равно CI.
find_uv() {
  command -v uv 2>/dev/null && return 0
  [ -x "$HOME/.local/bin/uv" ] && { printf '%s\n' "$HOME/.local/bin/uv"; return 0; }
  return 1
}

# Все проверки репозитория; печатает только ошибки и предупреждения.
run_checks() {
  local root=$1 uv=$2 out status=0
  out=$(cd "$root" && "$uv" run --quiet tools/validate.py 2>&1) || status=1
  printf '%s\n' "$out" | grep -E '^(ОШИБКА|ВНИМАНИЕ)' || true
  if [ "${3:-}" = full ]; then
    (cd "$root" && "$uv" run --quiet tools/figures.py --check 2>&1) || status=1
    (cd "$root" && "$uv" run --quiet tools/bibliography.py --check 2>&1) || status=1
  fi
  return $status
}

json_context() {
  # $1 — событие хука; текст — со stdin
  python3 -c 'import json,sys
event, text = sys.argv[1], sys.stdin.read().strip()
print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}, "suppressOutput": True}))' "$1"
}
