#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
failed=0

expected=(
  README.md
  architecture.md
  codex-install-prompt.md
  mihoro-inspiration.md
  security.md
  setup.md
  troubleshooting.md
)

for language in en zh-CN; do
  for topic in "${expected[@]}"; do
    if [[ ! -f "$root/docs/$language/$topic" ]]; then
      printf 'missing %s document: docs/%s/%s\n' "$language" "$language" "$topic" >&2
      failed=1
    fi
  done
done

while IFS= read -r -d '' document; do
  while IFS= read -r raw_link; do
    target=${raw_link#']('}
    target=${target%%#*}
    case $target in
      ''|http://*|https://*|mailto:*) continue ;;
    esac
    if [[ ! -e "$(dirname -- "$document")/$target" ]]; then
      printf 'broken relative link: %s -> %s\n' "${document#"$root/"}" "$target" >&2
      failed=1
    fi
  done < <(grep -oE '\]\([^)]+' "$document" || true)
done < <(find "$root" -type f -name '*.md' -print0)

if grep -RInE '17890|docs/(en|zh-CN)/migration\.md' \
  "$root/README.md" "$root/README.zh-CN.md" "$root/docs" "$root/examples"; then
  printf 'public documentation contains a personal port or removed migration guide\n' >&2
  failed=1
fi

for language in en zh-CN; do
  prompt="$root/docs/$language/codex-install-prompt.md"
  if [[ $language == en ]]; then
    plan_label='Plan mode'
    checkout_label='pinned released tag'
  else
    plan_label='Plan 模式'
    checkout_label='已发布标签'
  fi
  if ! grep -Fq "$plan_label" "$prompt" || ! grep -Fq 'request_user_input' "$prompt"; then
    printf 'installation prompt lacks Plan mode interactive-input guidance: %s\n' "$language" >&2
    failed=1
  fi
  checkout_line=$(grep -n -m1 "$checkout_label" "$prompt" | cut -d: -f1)
  suggest_line=$(grep -n -m1 './install.sh --suggest-port' "$prompt" | cut -d: -f1)
  if [[ -z $checkout_line || -z $suggest_line || $checkout_line -ge $suggest_line ]]; then
    printf 'installation prompt uses project scripts before obtaining the checkout: %s\n' "$language" >&2
    failed=1
  fi
done

if ((failed)); then
  exit 1
fi

printf 'documentation: bilingual topic set and relative links are complete\n'
