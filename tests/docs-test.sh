#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
failed=0

# grep 1 means no match; 2+ means the check did not run successfully.
checked_grep() {
  local rc=0
  command grep "$@" || rc=$?
  if (( rc > 1 )); then
    printf 'documentation: grep failed; refusing a success report\n' >&2
    exit 2
  fi
  return "$rc"
}

documents=$(mktemp)
links=$(mktemp) || { rm -f -- "$documents"; exit 2; }
trap 'rm -f -- "$documents" "$links"' EXIT
# Process substitution hides the producer's exit status, even with pipefail.
if ! find "$root" -type f -name '*.md' -print0 > "$documents"; then
  printf 'documentation: file enumeration failed\n' >&2
  exit 2
fi
[[ -s $documents ]] || { printf 'documentation: no documents found\n' >&2; exit 2; }

expected=(
  README.md
  acceptance.md
  agent-install-prompt.md
  agent-update-prompt.md
  architecture.md
  codex-install-prompt.md
  mihoro-inspiration.md
  rules.md
  security.md
  setup.md
  troubleshooting.md
  update.md
  vscode-remote.md
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
  checked_grep -oE '\]\([^)]+' "$document" > "$links" || true
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
  done < "$links"
done < "$documents"

if checked_grep -RInE '17890|docs/(en|zh-CN)/migration\.md' \
  "$root/README.md" "$root/README.zh-CN.md" "$root/docs" "$root/examples"; then
  printf 'public documentation contains a personal port or removed migration guide\n' >&2
  failed=1
fi

# Source archives have no Git index. Scan all public Markdown in either layout.
if checked_grep -RInE --include='*.md' \
  'SEA[-_ ]?AD|sea-ad-single-cell|Ai\+|学术搜索|学术访问|Academic (Search|Access)' \
  "$root/README.md" "$root/README.zh-CN.md" "$root/docs"; then
  printf 'public documentation contains maintainer-specific routing policy\n' >&2
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
      'CODEX_REMOTE_PAYLOAD'
      'proxy_on || exit 1'
      'must never start Mihomo automatically'
      '127.0.0.1:7890'
      'libc compatibility'
      'current proxy variables'
      'active downloads'
      'ssh/sshd processes'
      'existing policy rules'
      'redacted diff'
      'complete test suite'
      'service name'
      'subscription integration method'
      'preserve/merge strategy'
      'MATCH,DIRECT'
      'systemctl --user'
      'is-enabled mihomo remains'
      'official release source'
      'published checksum'
      'VS Code Remote'
      'http.proxy'
    )
  else
    checkout_label='已发布标签'
    required=(
      '能力检查'
      '只读审计'
      '明确批准'
      '敏感信息'
      '回滚'
      '最终验收'
      'CODEX_REMOTE_PAYLOAD'
      'proxy_on || exit 1'
      '绝不自动'
      '127.0.0.1:7890'
      'libc 兼容性'
      '当前代理变量'
      '正在运行的下载'
      'ssh/sshd 进程'
      '已有策略规则'
      '脱敏 diff'
      '完整测试套件'
      '服务名'
      '订阅接入方式'
      '保留/合并方案'
      'MATCH,DIRECT'
      'systemctl --user'
      'disabled'
      '官方 Release'
      '官方摘要'
      'VS Code Remote'
      'http.proxy'
    )
  fi

  required+=('scripts/acceptance.sh' 'PASS' 'FAIL' 'UNVERIFIED' 'DEFERRED' '--expect-status' 'PIPESTATUS' 'SHA256')
  if checked_grep -Ein \
    'Plan mode|Plan 模式|request_user_input|interactive popup|交互弹窗|Codex client|Codex 客户端|Skills?' \
    "$prompt"; then
    printf 'generic installation prompt contains a product-specific interface: %s\n' "$language" >&2
    failed=1
  fi
  for marker in "${required[@]}"; do
    if ! checked_grep -Fiq -- "$marker" "$prompt"; then
      printf 'generic installation prompt lacks required marker %s: %s\n' "$marker" "$language" >&2
      failed=1
    fi
  done
  if ! checked_grep -Fq '](agent-install-prompt.md)' "$compatibility"; then
    printf 'legacy prompt page does not point to the generic prompt: %s\n' "$language" >&2
    failed=1
  fi
  if checked_grep -Fq '```text' "$compatibility"; then
    printf 'legacy prompt page duplicates an executable prompt: %s\n' "$language" >&2
    failed=1
  fi

  checkout_line=$(awk -v text="$checkout_label" 'index($0, text) { print NR; exit }' "$prompt")
  suggest_line=$(awk 'index($0, "./install.sh --suggest-port") { print NR; exit }' "$prompt")
  if [[ -z $checkout_line || -z $suggest_line || $checkout_line -ge $suggest_line ]]; then
    printf 'installation prompt uses project scripts before obtaining the checkout: %s\n' "$language" >&2
    failed=1
  fi
done

if ! checked_grep -Fq 'docs/en/agent-install-prompt.md' "$root/README.md" ||
   ! checked_grep -Fq 'docs/zh-CN/agent-install-prompt.md' "$root/README.zh-CN.md"; then
  printf 'top-level README does not use the generic installation prompt as the main entry\n' >&2
  failed=1
fi

for language in en zh-CN; do
  for topic in update.md agent-update-prompt.md; do
    for marker in 'mihomoctl update --check' '--dry-run' '--version' 'scripts/migrate.py' \
                  'PASS' 'FAIL' 'UNVERIFIED' 'DEFERRED' 'active/enabled'; do
      if ! checked_grep -Fq -- "$marker" "$root/docs/$language/$topic"; then
        printf 'update document lacks required marker %s: %s/%s\n' "$marker" "$language" "$topic" >&2
        failed=1
      fi
    done
  done
  guide="$root/docs/$language/vscode-remote.md"
  if [[ $language == en ]]; then
    permission_marker='mode `600`'
  else
    permission_marker='权限 `600`'
  fi
  for marker in 'http.proxy' 'http.proxyStrictSSL' "$permission_marker" \
                'proxy_vars=2/2' 'CODEX_REMOTE_PAYLOAD' 'server-env-setup'; do
    if ! checked_grep -Fq "$marker" "$guide"; then
      printf 'VS Code Remote guide lacks required marker %s: %s\n' "$marker" "$language" >&2
      failed=1
    fi
  done
done

if ! checked_grep -Fq 'if [[ -n ${CODEX_REMOTE_PAYLOAD:-} ]]' "$root/src/shell.bash" ||
   ! checked_grep -Fq 'proxy_on || exit 1' "$root/src/shell.bash"; then
  printf 'remote-runtime compatibility hook was removed unexpectedly\n' >&2
  failed=1
fi

if ((failed)); then
  exit 1
fi

printf 'documentation: bilingual topic set and relative links are complete\n'
