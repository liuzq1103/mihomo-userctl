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

if git -C "$root" grep -InE \
  'SEA[-_ ]?AD|sea-ad-single-cell|Ai\+|学术搜索|学术访问|Academic (Search|Access)' \
  -- README.md README.zh-CN.md 'docs/*.md'; then
  printf 'tracked public documentation contains maintainer-specific routing policy\n' >&2
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

  if grep -Ein \
    'Plan mode|Plan 模式|request_user_input|interactive popup|交互弹窗|Codex client|Codex 客户端|Skills?' \
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

for language in en zh-CN; do
  guide="$root/docs/$language/vscode-remote.md"
  if [[ $language == en ]]; then
    permission_marker='mode `600`'
  else
    permission_marker='权限 `600`'
  fi
  for marker in 'http.proxy' 'http.proxyStrictSSL' "$permission_marker" \
                'proxy_vars=2/2' 'CODEX_REMOTE_PAYLOAD' 'server-env-setup'; do
    if ! grep -Fq "$marker" "$guide"; then
      printf 'VS Code Remote guide lacks required marker %s: %s\n' "$marker" "$language" >&2
      failed=1
    fi
  done
done

if ! grep -Fq 'if [[ -n ${CODEX_REMOTE_PAYLOAD:-} ]]' "$root/src/shell.bash" ||
   ! grep -Fq 'proxy_on || exit 1' "$root/src/shell.bash"; then
  printf 'remote-runtime compatibility hook was removed unexpectedly\n' >&2
  failed=1
fi

if ((failed)); then
  exit 1
fi

printf 'documentation: bilingual topic set and relative links are complete\n'
