# 首次运行：验证代理是否真正生效

完成 [安装初始化](setup.md)、[订阅导入](subscriptions.md) 和 [路由规则](rules.md) 后，分四层验证：

1. 运行态：`mihomoctl status` 应显示预期核心、配置、运行态和 listener。启动失败先用 `mihomoctl logs --lines 50` 检查。
2. 本地认证代理：`mihomoctl health check` 检查本地运行时、controller 和 listener；`mihomoctl env show` 默认脱敏。通过 `mihomoctl exec -- curl --fail --head https://example.com` 发出真实 HTTPS 请求，验证注入的代理环境可用。请求成功仍可能是 DIRECT。
3. 目标路由：核查活动核心的 mode、rules、provider 顺序及组内选择。高级 CLI 的 `init` 默认为 `MATCH,DIRECT`；新用户终端向导的简单订阅导入建立 `MATCH,Proxy`。已有自定义路由在明确修改前保留。先用 `mihomoctl groups`、`mihomoctl nodes` 查看，再用 `mihomoctl select Proxy NODE_NAME` 选择真实远端节点；只选节点不会改变命中的 DIRECT 规则。目标规则须在 fallback 前匹配并指向该组；NO_PROXY 也可能完全绕过代理。
4. 真实客户端：用 exec 启动 Codex，触发真实请求，对照时间、目标和 Controller 连接链。`mihomoctl connections --details` 会显示私有目标和规则，仅在本地审阅，不发布原始输出。成功的客户端操作及对应远端连接链，只能证明该次已观察的请求。

Codex 必须已独立安装并能在 PATH 找到：

```bash
mihomoctl exec -- codex
mihomoctl exec -- codex --help
mihomoctl exec -- codex "检查当前项目"
mihomoctl direct -- codex
```

`codex --help` 验证启动和参数透传，不一定联网。exec 的本地健康检查失败时拒绝启动；`--` 后参数原样传递，保留子进程退出码和信号语义。direct 清除 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY、NO_PROXY 及四个小写变量，不能绕过透明路由、VPN 或客户端自身代理设置。

```bash
mihomoctl health check --egress-url https://example.com
mihomoctl doctor
```

外部探测只证明该探测的结果。Listener 成功、选中节点或外部探测成功，均不能单独证明 Codex 使用远端节点。没有观察真实 Codex 请求时记录 **UNVERIFIED** 并说明缺少的证据。需要停止时显式 `mihomoctl stop`。systemd、容器与 CI 请用 [binding](operations/integrations.md)，准备好后由操作者明确重启应用。


## 通过代理安装第三方 CLI

先完成 Mihomo 初始化、显式启动和本地健康检查；若下载站应走远端节点，还需先配置订阅与匹配的路由。安装核心本身不能依赖尚未运行的自身代理。这里只演示显式请求安装 Claude Code 的场景，不会在安装 mihomoctl 时自动安装第三方应用。

`exec` 将代理变量交给其启动的进程及后代，不改变父 Shell 或已运行的 daemon。外层 `|`、`&&`、`;` 由当前 Shell 处理。因此，把左侧 curl 包进 exec 后再在外层接 Bash，右侧及其下载不会继承代理。完整管道必须位于受代理 Shell 内：

```bash
mihomoctl exec -- bash -o pipefail -c 'curl -fsSL https://claude.ai/install.sh | bash'
```

该写法修复环境作用范围，并通过 pipefail 报告管道失败；它仍会流式执行已收到的内容。`curl -f` 只拒绝 HTTP 错误状态，不拒绝 HTTP 200 的地区限制或登录 HTML 页面，pipefail 也不能阻止已经发生的执行。推荐分步下载、审阅、执行。

先下载到私有目录，并拒绝空文件、明显 HTML 和 Bash 语法错误。此步骤不执行安装脚本：

```bash
# installer-download
umask 077
installer_dir=$(mktemp -d "$HOME/claude-installer.XXXXXXXX")
mihomoctl exec -- bash -euo pipefail -c '
  curl -fsSL --dump-header "$1/headers" --output "$1/install.sh" https://claude.ai/install.sh
  test -s "$1/install.sh"
  if LC_ALL=C grep -Eiq "<(!doctype[[:space:]]+html|html|head|body)([[:space:]>])" "$1/install.sh"; then
    printf "%s\n" "Refusing an HTML response; inspect network/routing." >&2
    exit 1
  fi
  bash -n "$1/install.sh"
  touch "$1/download-checked"
' bash "$installer_dir"
```

只有上一块成功后，才在本地审阅 `$installer_dir/headers` 的最终响应与 `$installer_dir/install.sh` 的内容和来源。若返回地区限制页面、登录页或未知脚本则停止，检查目标规则、NO_PROXY 和下载站/后续资产站的连接；不要换成盲目直连执行或关闭 TLS 校验。上述检查、Content-Type 和 bash -n 都不能认证脚本，也不能保证网络一定走远端节点。

确认该私有文件是预期安装器后，在同一终端显式执行；Bash 和后续下载继承代理环境：

```bash
# installer-execute-after-review
if test -f "$installer_dir/download-checked"; then
  mihomoctl exec -- bash "$installer_dir/install.sh"
else
  printf '%s\n' 'Download checks did not pass; stop and inspect the previous failure.' >&2
  false
fi
```

`download-checked` 仅记录下载/格式检查通过，人工审阅仍是必要步骤。保留文件供排障，使用后自行清理该独立目录。通过 `claude --version` 检查安装；登录和真实联网请求另行验证。第三方安装器对 PATH 或其他文件的修改由其自身决定，不属于 mihomoctl 的安装器保证。

官方说明：[安装](https://code.claude.com/docs/en/setup)、[代理与 HTML/403 排障](https://code.claude.com/docs/en/troubleshoot-install)。`Could not resolve host` 需要检查代理继承与 DNS；`syntax error near unexpected token '<'` 常意味着把网页当脚本执行，不能简单归因于 Bash 版本。
