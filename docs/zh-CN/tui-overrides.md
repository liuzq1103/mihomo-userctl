# TUI 手动选节点与 JavaScript 覆写

Linux Mihomo 接收 YAML；Clash Verge Rev/FlClash 的 `main(config)` 是客户端的配置生成步骤。
本项目通过本地 Node.js 执行用户指定的可信脚本，仅允许变更策略组、规则和 rule-providers。
监听端口、认证、TUN、DNS、代理节点与 proxy-providers 等其他配置不可由脚本修改。
Node vm 不是安全沙箱：只使用自己审阅过的本地脚本，不自动下载或执行远程脚本。
脚本和配置要求当前用户所有、普通文件、权限 600；Node 仅覆写时需要。

## 节点选择

```bash
mihomoctl tui
```

左栏持续标记当前组，右栏 `[*]` 表示当前选择，高亮表示光标。
Tab 换栏，方向键浏览，Enter 切换手动组节点，`/` 搜索（空字符串清除），`t` 测延迟，
`c` 查看连接链路，`f` 查看流量，`r` 刷新，`q` 退出。布局参考开源
[mihomoTui](https://github.com/shuideyimei/mihomoTui) 的节点过滤、组状态和连接查看交互，未复制源代码。
搜索会隐藏不匹配的节点，但不会改变真实选择。

自动组显示 AUTO/read-only。按 `m` 预览将当前配置组改为 `select`，按 `y` 校验、备份并保存。
保留原 provider/member/filter 配置，移除自动测速参数。GLOBAL 是核心生成组，不能这样转换。
CLI 等价操作：

```bash
mihomoctl manual Proxy
mihomoctl manual Proxy --apply
# 保存后，准备好中断现有连接时执行
mihomoctl restart
mihomoctl tui
```

转换 Proxy 会影响所有命中该组的新请求。若希望按用途区分，用覆写生成单独的 AI 策略组。
正常 Enter 切换不会断开已有连接；重启 Mihomo 会断开它们。选择缓存仍取决于工作目录可写。

## 使用 FlClash-rules 的 override.js

将自己审阅的 [override.js](https://github.com/liuzq1103/FlClash-rules/blob/main/dist/override.js)
存放于自己的私有配置目录，然后：

```bash
chmod 600 ~/.config/mihomo/override.js
mihomoctl override --script ~/.config/mihomo/override.js --flclash-compat
mihomoctl override --script ~/.config/mihomo/override.js --flclash-compat --apply
mihomoctl restart
mihomoctl tui
```

也可以从 TUI 预览和保存：

```bash
mihomoctl tui --script ~/.config/mihomo/override.js --flclash-compat
```

按 `o` 执行脚本并显示摘要，`y` 校验并保存，退出后按需重启再打开 TUI。
默认仅预览，不输出完整配置、节点凭据、订阅地址或脚本错误内容。应用前运行 `mihomo -t`，
校验通过且配置未被并发修改才创建 `config.yaml.before-policy-*` 私有备份并原子替换。
失败不替换配置；备份含私密配置，勿分享。撤回可恢复输出中的备份，再校验并按需重启。

`--flclash-compat` 针对当前 FlClash-rules 脚本：补齐缺少的脚本入口组和默认回退组，
从本地 provider YAML 缓存提供节点作为脚本输入。生成的策略组恢复为 provider `use` 和精确名称
`filter`，避免把节点密码复制进配置。需要订阅缓存已存在、权限 600、格式为 `proxies` 列表；
未缓存、无 path 或不兼容格式会明确拒绝。非默认核心工作目录传 `--home-dir /ABSOLUTE/mihomo`。
缓存刷新后，新节点名称不自动进入已生成的精确过滤列表，需要重新预览和应用覆写。
这不是持续订阅刷新服务，也不是完整桌面客户端功能集。

脚本生成 AI 手动选择组和测速备用组；在 TUI 中确认 AI 入口组选中手动组，
再进入稳定组指定节点。脚本按节点名称排除部分地区，不证明实际出口位置或模型请求可用。
脚本捕获错误并 `console.error` 后原样返回时，本工具报告失败，不会假报覆写成功。

## 核对 Codex 请求

```bash
watch -n 1 'mihomoctl connections --details'
```

`--details` 显式显示目标域名与规则匹配内容，属于私密诊断信息，请审阅后分享。
确认 Codex 发请求时对应 chatgpt.com/openai.com 等真实目标的链路；第三方模型服务可能有不同域名。
只有域名和链路仍不足以证明请求的进程身份或 OpenAI 看到的出口 IP。
钩子仅设置代理入口，不执行地区解锁。香港节点名、实际服务器位置、最终出口 IP 和服务方地区判断
是不同的信息。不能从 Codex 可用反推香港受支持，也不能凭节点名断言它必定不可用。

## v0.8.0 验收修正

SOCKS5 的 `05 02` 表示要求账密认证（虽未按请求提供的方法协商），与 `05 00` 的无认证成功分别报告。
02 / FF 作为拒绝匿名访问的证据；00 为 FAIL，未知或不完整响应仍为 UNVERIFIED；另行验证真实认证请求。
v0.7.0 的已发布检查器和固定验收契约保持不变。

Codex 扫描先分类 comm/exe，再对候选读取身份和环境。对 exe 不可读的 sd-pam、fusermount3、sshd
辅助进程，要求 comm 与受限长度 cmdline 交叉确认后才排除；其他不可分类的存活进程、只有名称吻合的进程
和不可读的 Codex 候选仍为 UNVERIFIED。此分类不抵御同 UID 恶意伪装，不终止进程，也不代替模型端到端验收。
