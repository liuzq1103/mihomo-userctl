# 安全模型

## 威胁范围

本项目重点防止：

- `.bashrc` 自动代理导致大文件误走付费流量；
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

## 停止策略

`mihomoctl stop` 只调用：

```text
systemctl --user stop <白名单校验后的服务名>
```

随后等待端口释放。端口仍被占用时报告错误，不运行 `kill`、`pkill`，不根据
进程名停止 `ssh`/`sshd`，也不使用 sudo。

## 安全报告

请不要在公开 issue 中提交订阅 URL、完整配置、代理 URL 或日志秘密。先阅读
仓库根目录 `SECURITY.md`，使用其中的私密报告方式。
