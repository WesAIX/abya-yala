#!/usr/bin/env bash
# SessionStart: включить git-хуки репозитория (настройка не переживает клон)
# и показать состояние глав и сверки.
set -uo pipefail
. "$(dirname "$0")/lib.sh"
cat >/dev/null 2>&1 || true

root=$(repo_root) || exit 0
[ -d "$root/.githooks" ] && git -C "$root" config core.hooksPath .githooks 2>/dev/null
uv=$(find_uv) || {
  echo 'uv не найден: проверки в хуках отключены (CI их всё равно запускает). Установка: sudo pacman -S uv' |
    json_context SessionStart
  exit 0
}
summary=$(cd "$root" && "$uv" run --quiet tools/validate.py 2>&1 | sed -n '/^Сверка глав/,$p')
statuses=$(grep -H -o '\*\*Статус:\*\* [а-яё]*' "$root"/chapters/[0-9][0-9]-*.md 2>/dev/null |
  sed -E 's#.*/([0-9]{2}-[^.]*)\.md:\*\*Статус:\*\* #  \1: #')
printf 'Статусы глав:\n%s\n%s\n' "$statuses" "$summary" | json_context SessionStart
