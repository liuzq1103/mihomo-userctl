#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
failed=0

expected=(
  README.md
  agent-install-prompt.md
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
  prompt="$root/docs/$language/agent-install-prompt.md"
  compatibility="$root/docs/$language/codex-install-prompt.md"
  if [[ $language == en ]]; then
    checkout_label='pinned released tag'
    required=(
      'capability gate'
      'read-only audit'
      'explicit approval'
      'Sensitive information'
      'rollback'
      'final acceptance'
    )
  else
    checkout_label='已发布标签'
    required=('能力检查' '只读审计' '明确批准' '敏感信息' '回滚' '最终验收')
  fi

  if grep -Ein \
    'Plan mode|Plan 模式|request_user_input|interactive popup|交互弹窗|CODEX_REMOTE_PAYLOAD|Codex' \
    "$prompt"; then
    printf 'generic installation prompt contains a product-specific interface: %s\n' "$language" >&2
    failed=1
  fi
  for marker in "${required[@]}"; do
    if ! grep -Fiq "$marker" "$prompt"; then
      printf 'generic installation prompt lacks required marker %s: %s\n' "$marker" "$language" >&2
      failed=1
    fi
  done
  if ! grep -Fq '](agent-install-prompt.md)' "$compatibility"; then
    printf 'legacy prompt page does not point to the generic prompt: %s\n' "$language" >&2
    failed=1
  fi
  if grep -Fq '```text' "$compatibility"; then
    printf 'legacy prompt page duplicates an executable prompt: %s\n' "$language" >&2
    failed=1
  fi

  checkout_line=$(grep -n -m1 "$checkout_label" "$prompt" | cut -d: -f1 || true)
  suggest_line=$(grep -n -m1 './install.sh --suggest-port' "$prompt" | cut -d: -f1 || true)
  if [[ -z $checkout_line || -z $suggest_line || $checkout_line -ge $suggest_line ]]; then
    printf 'installation prompt uses project scripts before obtaining the checkout: %s\n' "$language" >&2
    failed=1
  fi
done

if ! grep -Fq 'docs/en/agent-install-prompt.md' "$root/README.md" ||
   ! grep -Fq 'docs/zh-CN/agent-install-prompt.md' "$root/README.zh-CN.md"; then
  printf 'top-level README does not use the generic installation prompt as the main entry\n' >&2
  failed=1
fi

if ! grep -Fq 'CODEX_REMOTE_PAYLOAD' "$root/src/shell.bash"; then
  printf 'remote-runtime compatibility hook was removed unexpectedly\n' >&2
  failed=1
fi

if ((failed)); then
  exit 1
fi

printf 'documentation: bilingual topic set and relative links are complete\n'
