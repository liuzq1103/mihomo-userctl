# 故障排查

## 安装在 `doctor` 阶段停止

安装器会把更新视为一个事务：自动恢复原有控制器、模块、补全、非敏感配置、
`.bashrc` 和受管目录的原权限，然后打印保留的备份路径。检查其中权限 `600`
的 `manifest.tsv` 和已脱敏的 `doctor` 输出；在查明原因前不要删除备份。该过程
不会启动或 enable Mihomo。

## 电脑或服务器停电重启后

服务设计为 `disabled`，所以不会自动启动：

```bash
mihomoctl status
mihomoctl start
```

启动成功只代表 loopback 代理可用，当前 Shell 仍为 direct。需要代理某条命令时
使用 `with_proxy`。

## `proxy_status` 显示 inconsistent

表示八个变量只设置了一部分、值不是当前凭据，或服务/listener 已不可用：

```bash
proxy_off
mihomoctl doctor
```

不要手工补齐几个变量；修复服务或凭据后重新执行 `proxy_on`。

## 服务 active，但 ready 失败

```bash
mihomoctl doctor
mihomoctl logs --lines 100
PROXY_PORT=$(awk -F= '$1 == "MIHOMO_PORT" { print $2 }' \
  "$HOME/.config/mihomo/mihomo-shell.conf")
ss -lntp "sport = :$PROXY_PORT"
```

常见原因：订阅失效、节点不可用、`config.yaml` 与 `client.env` 凭据不同、端口
不同、READY URL 被规则阻断。诊断输出不会显示密码。

## 端口被占用

停止用户服务：

```bash
mihomoctl stop
```

若仍提示占用，只做只读检查：

```bash
PROXY_PORT=$(awk -F= '$1 == "MIHOMO_PORT" { print $2 }' \
  "$HOME/.config/mihomo/mihomo-shell.conf")
ss -lntp "sport = :$PROXY_PORT"
```

不要杀死未知 sshd、其他用户进程或范围外端口。确认归属前停止切换并联系管理
员。`mihomo-userctl` 不会自动清理端口。

## Codex Remote 启动失败

Codex 专用 hook 采用 fail closed：

```bash
mihomoctl start
mihomoctl ready
mihomoctl doctor
```

三项通过后正常重连 Codex。不要让普通 `.bashrc` 自动启动服务；否则会改变
“重启后默认不运行”的设计。

### 非交互 `.bashrc` 提前返回

Ubuntu 常见 `.bashrc` 会在文件前部对非交互 Shell 执行 `return`。`v0.1.5`
会在首次安装和升级时把 managed loader 放到该 guard 之前。可只读检查顺序：

```bash
grep -nE 'mihomo-userctl managed loader|case \$-|(^|[;[:space:]])return([;[:space:]]|$)' \
  "$HOME/.bashrc"
```

不要把 `CODEX_REMOTE_PAYLOAD` 写入 `.bashrc` 或全局环境。测试时只能给一次性子
进程提供非敏感占位值，并确认父 Shell 仍为 direct。

### 终端已代理，但仍复用旧 App Server

环境变量不会注入已运行进程。安装前启动的 Codex App Server 即使在新终端执行
`with_proxy codex` 后也可能保持 `0/8`，并让新 CLI 通过本地 socket 复用它。
典型证据是新 CLI 连接本地 Listener，而旧 app-server 仍对公网 `:443` 发起
`SYN-SENT`。

先退出当前用户自己的 Codex 客户端并正常重连；只有确认 PID、UID 和父子关系后
才停止当前用户的残留进程。不要按进程名全局 `pkill`，不要停止其他用户或未知
SSH 会话。新进程应重新继承环境，并在 Mihomo 日志中出现目标域名。

## 终端 Codex 正常，但 VS Code Remote 扩展失败

VS Code Extension Host 不运行 `with_proxy`，也不应假定它会提供
`CODEX_REMOTE_PAYLOAD`。若远程 Codex 子进程没有代理变量，按
[VS Code Remote 推荐配置](vscode-remote.md)配置服务器侧 Machine
`http.proxy`，保护包含认证 URL 的设置文件为当前用户所有且权限 `600`，然后
重载窗口。当前实机验证的同版扩展会向 Codex 子进程传递两个大写变量，因此
预期为 `proxy_vars=2/2`，Extension Host 自身仍可能为 `0/2`。

若仍失败，重启当前用户自己的远程 VS Code 连接，再确认 Codex 子进程连接的是
`127.0.0.1:<用户端口>`。不要把代理写入全局 profile 或
`server-env-setup`，否则会扩大到普通任务和其他远程扩展进程。

## `client.env must have mode 600`

确认文件属于当前用户后：

```bash
chmod 600 "$HOME/.config/mihomo/client.env"
```

如果所有者不是当前用户，不要用管理员账户强行修改未知文件；先查明来源。

## 怎样确认 axel 没走 Mihomo

父 Shell 可能已经启用代理时，使用显式子进程边界：

```bash
mihomoctl direct -- axel -n 10 'https://example.org/large-file'
```

诊断当前用户的长期运行进程时无需打印环境值：

```bash
mihomoctl inspect-process PID --json
mihomoctl inspect-name codex --json
```

`proxy_state=inconsistent` 表示部分变量缺失或与当前凭据文件不一致。只正常重连或重启
已经确认的当前用户应用；检查命令不会结束进程。

自定义规则失败时先运行 `mihomoctl rules status`，再运行 `mihomoctl rules check`。
退出 `2` 并报告 `config-unsupported-yaml` 表示相关 provider 段落需要改成文档约定的
block style，并不等于 Mihomo 配置本身一定无效。

在运行下载的同一个 Shell：

```bash
proxy_status
env | grep -iE '^(http|https|all|no)_proxy='
```

应显示 `shell=direct` 且第二条无输出。还可观察 Mihomo 日志或连接统计，确认下载
域名未进入 Listener。Mihomo 正在监听并不代表普通下载会经过它。
