# 配置与兼容契约

Manager 配置版本仍为 `version: 1`，与发行版本 1.3.0 独立。公开 JSON 仍为 `mihomoctl/v1`，包含 command、scope、overall、data、checks 和 errors。PASS 退出 0，FAIL 退出 1，UNVERIFIED 退出 2；exec/direct 启动子进程后保留其退出码和信号语义。

以初始化产生的私有 manager.yaml 为准，不要整文件替换。Profile 引用核心中的具名 listener 和私有 credentials_file，不重复声明端口或内嵌密码。Binding 引用 profile 和 adapter，内建 adapter 为 exec、systemd、docker、kubernetes、supervisor、pm2、ci；完整实例见 [接入教程](../operations/integrations.md)。

未知字段、重复 YAML key、不安全 alias 和跨作用域秘密路径会拒绝。System 路径固定，不从 HOME 或当前目录发现。allow_non_loopback 是明确的地址授权，不会开放端口。核心配置决定路由，profile 只选择代理 listener；NO_PROXY 可能绕过该 listener。

[命令参考](cli.md) 由实际 dispatch 使用的集中解析定义生成。保留兼容映射：profiles → profile list，export --binding NAME → integration export NAME，dashboard → ui，health → health check。退役名称 codex/paseo/opencode/diagnose/ready 只作为迁移说明，执行仍拒绝；应用启动使用 exec/direct，持续接入使用 binding。不恢复应用 daemon 或自动 Shell hook。
