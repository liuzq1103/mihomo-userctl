# 首次运行：验证代理是否真正生效

完成 [安装初始化](setup.md)、[订阅导入](subscriptions.md) 和 [路由规则](rules.md) 后，分四层验证：

1. 运行态：`mihomoctl status` 应显示预期核心、配置、运行态和 listener。启动失败先用 `mihomoctl logs --lines 50` 检查。
2. 本地认证代理：`mihomoctl health check` 检查本地运行时、controller 和 listener；`mihomoctl env show` 默认脱敏。通过 `mihomoctl exec -- curl --fail --head https://example.com` 发出真实 HTTPS 请求，验证注入的代理环境可用。请求成功仍可能是 DIRECT。
3. 目标路由：核查活动核心的 mode、rules、provider 顺序及组内选择。新 init 默认 `MATCH,DIRECT`。先用 `mihomoctl groups`、`mihomoctl nodes` 查看，再用 `mihomoctl select Proxy NODE_NAME` 选择真实远端节点；只选节点不会改变命中的 DIRECT 规则。目标规则须在 fallback 前匹配并指向该组；NO_PROXY 也可能完全绕过代理。
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
