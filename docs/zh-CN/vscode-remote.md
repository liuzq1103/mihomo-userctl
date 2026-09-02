# VS Code Remote 推荐配置

本文适用于：Mihomo 和 `mihomo-userctl` 已安装在远程 Linux 账户中，终端里的
`with_proxy codex` 可以联网，但 VS Code Remote 中的 Codex 扩展仍然超时。

## 为什么终端成功而扩展失败

两条启动路径彼此独立：

```text
终端
  └─ with_proxy codex
       └─ Codex 继承八个代理变量

VS Code Remote
  └─ Extension Host
       └─ Codex 扩展启动内置 app-server
```

VS Code Extension Host 不执行 `with_proxy`，也不会因为用户安装了
`mihomo-userctl` 就自动设置代理。`CODEX_REMOTE_PAYLOAD` 是另一个经过本地验证
的 Codex Remote 兼容钩子；不要假设 VS Code 扩展会提供它。

OpenAI 官方文档说明，Codex App Server 是 VS Code 扩展等富客户端使用的接口，
CLI 与 IDE 扩展共享 Codex 的配置层：

- [Codex App Server](https://learn.chatgpt.com/zh-Hans/docs/app-server)
- [Codex 基础配置](https://learn.chatgpt.com/zh-Hans/docs/config-file/config-basic)

在 v0.1.5 实机验收中，同版扩展 `26.825.51511` 会读取 VS Code 的
`http.proxy`，并给它启动的 Codex app-server 设置 `HTTP_PROXY` 和
`HTTPS_PROXY`。这是版本相关的实测行为，不是本项目能够保证的稳定 OpenAI
接口；升级扩展后必须重新验收。

## 前提条件

先通过普通 SSH 登录服务器，手动启动并验证用户服务：

```bash
mihomoctl start
mihomoctl ready
```

服务必须保持 `disabled`。不要为了 VS Code 自动联网而 enable 服务、配置
linger、cron 或系统级服务。

## 备份远程 Machine Settings

VS Code Remote 的服务器侧 Machine Settings 位于：

```text
~/.vscode-server/data/Machine/settings.json
```

先备份并收紧权限：

```bash
settings="$HOME/.vscode-server/data/Machine/settings.json"
backup_dir="$HOME/.config/mihomo/backups/vscode"
timestamp=$(date +%Y%m%d-%H%M%S)

install -d -m 700 "$backup_dir"
cp -p -- "$settings" "$backup_dir/settings.json.before-proxy.$timestamp"
chmod 600 \
  "$backup_dir/settings.json.before-proxy.$timestamp" \
  "$settings"
```

如果文件不存在，先让 VS Code Remote 创建 Machine Settings，或者创建只属于
当前用户、权限为 `600` 的有效 JSON 对象。不要覆盖已有设置。

## 写入推荐配置

在服务器本地打开以下两个文件：

```text
~/.config/mihomo/client.env
~/.vscode-server/data/Machine/settings.json
```

从 `client.env` 读取 `MIHOMO_HTTPS_PROXY` 的完整值，将它写入
`settings.json` 的顶层 `http.proxy`。不要把该值粘贴到聊天、命令行、日志、
截图、Git 或报告。

结构示例：

```json
{
  "http.proxy": "http://<user>:<password>@127.0.0.1:<port>",
  "http.proxyStrictSSL": true
}
```

尖括号内容只是占位符，实际值必须与当前账户权限 `600` 的 `client.env` 完全
一致。若文件已有其他键，保留它们并确保 JSON/JSONC 语法有效。不要把
`http.proxyStrictSSL` 设为 `false`。

保存后再次检查权限，但不要打印配置内容：

```bash
chmod 600 "$HOME/.vscode-server/data/Machine/settings.json"
stat -c 'owner=%U mode=%a path=%n' \
  "$HOME/.vscode-server/data/Machine/settings.json"
```

预期当前用户所有且权限为 `600`。

## 重启和验收

先在 VS Code 命令面板执行：

```text
Developer: Reload Window
```

也可以使用 Codex 扩展的重启命令。配置相关的扩展重启流程可参考
[OpenAI MCP 文档](https://learn.chatgpt.com/zh-Hans/docs/extend/mcp)。

如果扩展仍复用旧进程，再使用：

```text
Remote-SSH: Kill VS Code Server on Host...
```

只选择当前账户自己的主机连接，确认没有重要任务后再执行；不要结束其他用户的
进程、SSH 会话或 VS Code Server。

取得最新的扩展 Codex PID：

```bash
vscode_codex_pid=$(
  pgrep -n -f \
    "$HOME/.vscode-server/extensions/openai.chatgpt-.*/bin/linux-x86_64/codex"
)
printf 'vscode_codex_pid=%s\n' "$vscode_codex_pid"
```

只检查变量是否存在，不打印认证 URL：

```bash
count=0
for name in HTTP_PROXY HTTPS_PROXY; do
  grep -zq "^${name}=" \
    "/proc/$vscode_codex_pid/environ" 2>/dev/null &&
    count=$((count + 1))
done
printf 'proxy_vars=%s/2\n' "$count"
```

当前实测预期为：

```text
proxy_vars=2/2
```

这里不要求 `8/8`。终端的 `proxy_on` 管理八个大小写变量，而当前 VS Code
扩展只给它启动的 app-server 注入两个大写 HTTP 代理变量。Extension Host
自身仍可能是 `0/8`。

最后验证真实连接和规则：

```bash
ss -ntp | grep -E "pid=${vscode_codex_pid}|127\.0\.0\.1:<port>"
mihomoctl logs --follow
```

将 `<port>` 换成当前账户配置的端口。Codex 请求应连接 loopback Listener，
Mihomo 日志中的 ChatGPT/OpenAI 域名应命中用户预期的代理策略。

## 安全和影响范围

- `settings.json` 现在含有 Listener 凭据，必须为当前用户所有且权限 `600`；
- `http.proxy` 是远程 VS Code 的 Machine Setting，其他遵循该设置的扩展流量也
  可能经过 Mihomo；
- 普通 SSH、新终端、`axel`、S3 和大型下载仍由 `.bashrc` 的默认直连模型保护；
- 不建议通过 `.profile` 全局导出代理，也不建议伪造
  `CODEX_REMOTE_PAYLOAD`；
- 不需要用 `server-env-setup` 给整个 Extension Host 注入八个变量；
- 不要在多人服务器上读取、修改或终止其他用户的 VS Code/Codex 进程。

## 长期驻留进程问题

环境变量只能在进程启动时继承。安装或修改代理配置前已经运行的 Codex
app-server 不会自动获得新环境。在一次实机排障中，新 CLI 已连接 Mihomo，但
它复用的旧 app-server 仍以 `0/8` 代理变量直接连接公网，表现为多个
`SYN-SENT` 和请求超时。

处理原则：先关闭或从客户端重启当前用户自己的 Codex/VS Code 连接，再验证新
PID；不得按名称批量杀死服务器上的 `codex`、`ssh` 或 `sshd`，不得操作其他
用户。

## 回滚

从 `settings.json` 中只移除本次加入的：

```json
"http.proxy"
"http.proxyStrictSSL"
```

或者恢复本次备份。恢复后保持权限 `600`，重新加载 VS Code 窗口，并确认扩展
进程不再包含代理变量。回滚 VS Code 设置不应停止 Mihomo，也不应修改
`.bashrc`、订阅、节点或其他用户配置。
