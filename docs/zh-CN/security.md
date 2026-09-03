# 安全模型

## 术语约定

- **敏感信息**：总称，包括订阅 URL、用户名、密码、令牌和完整代理 URL。
- **认证凭据**：能够证明身份或授予访问的值，本项目主要指 Listener 用户名和密码。
- **密钥**：只用于真正的 cryptographic key 或 API key。订阅 URL、密码和 token
  不应统称为“密钥”。

因此，本文用“敏感信息”作为上位词，在专指认证数据时使用“凭据”。

## 威胁范围

本项目重点防止：

- 继承或全局代理变量导致大文件误走个人代理流量；
- 凭据文件被错误权限暴露；
- 把配置文件当 Shell 程序执行；
- 代理密码出现在参数、日志、Git 或诊断输出；
- 在共享服务器上误停未知端口或其他用户进程；
- TUN、路由或系统代理产生难以察觉的全局影响。

它不能提供严格的跨 UID 端口访问隔离。Linux loopback 端口属于整台主机，其他
本地用户如果知道端口和有效凭据，仍可能连接。严格隔离需要管理员使用按 UID
防火墙规则；这超出本项目权限和范围。

## 默认直连

Shell 模块加载时首先清除：

```text
http_proxy https_proxy all_proxy no_proxy
HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
```

因此从已代理父进程启动的新普通 Shell 也会回到 direct。服务运行本身不会截获
流量，因为没有 TUN 或透明代理。

## 配置不是代码

`mihomo-shell.conf` 和 `client.env` 使用逐行白名单解析器。解析器不使用：

- `source`；
- `eval`；
- 命令替换；
- 动态变量名；
- 任意 Shell 表达式。

未知字段、重复字段、非法引号或空白均拒绝。只有固定变量名可通过 `printf -v`
写入内部状态。

## 凭据

- 文件必须属于当前 UID 且为 `600`；
- 只接受指向配置端口的 `127.0.0.1` URL；
- HTTP 和 HTTPS 使用 `http://user:password@...`；
- SOCKS 使用 `socks5h://user:password@...`，让代理端进行域名解析；
- readiness 的 URL 在命令参数中，但凭据只在子进程环境中；
- doctor、status 和错误信息不得回显 URL。

环境变量仍可能被同一 UID 的调试工具读取。因此同一 Linux 账户下的进程不被
视为彼此隔离；不要让不受信任的人共享同一个账户。

## VS Code Remote 凭据边界

可选的远程 Machine `http.proxy` 包含完整认证 URL，因此其
`~/.vscode-server/data/Machine/settings.json` 也属于敏感文件：必须属于当前
用户、权限为 `600`，备份同样需要 `600`。配置和验证时不得打印完整 URL。

该设置只比全局 Shell 代理更窄，并非只影响 Codex；其他遵循 VS Code
`http.proxy` 的远程扩展也可能使用它。普通 SSH Shell、`axel` 和 S3 仍默认
直连。不要为解决扩展联网而把代理写入 `.profile`、全局环境或
`server-env-setup`。完整做法见 [VS Code Remote 推荐配置](vscode-remote.md)。

## 停止策略

`mihomoctl stop` 只调用：

```text
systemctl --user stop <白名单校验后的服务名>
```

随后等待端口释放。端口仍被占用时报告错误，不运行 `kill`、`pkill`，不根据
进程名停止 `ssh`/`sshd`，也不使用 sudo。

## 安全报告

请不要在公开 issue 中提交订阅 URL、完整配置、代理 URL 或日志中的敏感信息。先阅读
仓库根目录 `SECURITY.md`，使用其中的私密报告方式。

## 自身更新的信任范围

更新只执行明确选定的官方发布代码，经 HTTPS 将标签解析为固定 GitHub commit。
记录实际计算的归档摘要，不声称完成独立官方摘要或签名验证。私有备份可能包含启动文件
中的个人设置。详见[更新来源与恢复](update.md)。
