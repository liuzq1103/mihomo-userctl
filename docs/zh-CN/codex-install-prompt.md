# 可直接复制的 Codex 安装 Prompt

适合在全新服务器上让 Codex 完成审计、安装和验收。建议先把 Codex 任务切换到
**Plan 模式**，再原样粘贴下面的 Prompt。Plan 模式和交互弹窗属于 Codex 客户端
能力，不是 Mihomo 的安装要求；如果当前客户端没有这些能力，应先停止并让用户
决定是否改用普通对话逐项确认。

不要预先替换端口等占位符：Prompt 会要求 Codex 审计后用交互弹窗收集。不要把
订阅 URL 或密码粘贴进 Prompt、弹窗或聊天；敏感信息只应进入服务器权限 `600` 的
本地文件。

```text
请为我当前登录的 Linux 用户安装用户级 Mihomo 和 mihomo-userctl。

交互和规划规则：
- 开始时确认当前任务处于 Plan 模式；如果不是，先停止并建议我切换 Plan 模式；
- 完成只读审计后，先给出完整实施 Plan，得到我确认后才能修改文件；
- 遇到任何需要我自定义的非敏感选项，必须使用 request_user_input 或当前客户端
  等效的交互弹窗，不得直接猜测或在实现中硬编码；
- 每个弹窗只问 1–3 个简短问题，提供推荐选项和影响说明，同时允许我填写自定义值；
- 至少通过弹窗确认：用户端口、readiness URL、服务名、订阅接入方式、现有配置
  的保留/合并方案，以及任何策略取舍；
- 订阅 URL、Listener 密码、令牌（token）等敏感信息绝不通过弹窗或聊天收集；在服务器本地
  生成或由我写入权限 600 的文件，Codex 只接收文件路径并验证权限；
- 如果当前环境不能显示交互弹窗，暂停并明确报告，不要用默认值替我决定。

必须达到的结果：
- 普通登录、新 Shell、axel、S3 和大型科研数据始终默认服务器直连；
- 只有 with_proxy、proxy_on 和明确批准的远程工具钩子使用 Mihomo；
- Mihomo 只有一个带认证的 Mixed Listener：127.0.0.1:<用户确认的端口>；
- 只用 systemctl --user，mihomo.service 必须保持 disabled；
- 不使用 sudo、root service、linger、cron、TUN、controller、系统代理或路由修改；
- 不读取、不修改、不停止其他用户，也不以其他用户身份登录或认证；
- 不停止未知监听、ssh/sshd、下载任务和无关会话；
- 已有 127.0.0.1:7890 一律视为范围外，除非我另行明确授权；
- 订阅 URL 和代理凭据不得出现在命令参数、输出、日志、Git 或报告中。

严格按以下顺序实施：
1. 完整阅读本仓库 README.zh-CN.md 和 docs/zh-CN/setup.md。
2. 只读检查系统、CPU 架构、libc 兼容性、Bash、systemd 用户管理器、依赖、
   当前代理变量、候选端口、用户服务、下载进程和现有配置。
3. 先通过交互弹窗确认代码检出目录，再克隆或使用已有的
   mihomo-userctl，固定到已发布标签，核对来源并审阅文件；不使用 `curl | bash`。
4. 从上述已验证代码目录运行 ./install.sh --suggest-port 取得候选端口；
   同时检查当前监听。通过交互
   弹窗让我确认候选值或填写自定义端口。同一服务器用户必须避开彼此端口；
   建议结果不是预留，正式绑定前必须再次检查。
5. 使用交互弹窗收集其他非敏感选项，给出完整 Plan 和精确修改范围；任何步骤
   需要管理员权限，或现有配置归属不明时立即停止。
6. 修改前对范围内文件创建权限收紧的备份。
7. 从 MetaCubeX 官方 Release 安装固定版本 Mihomo：下载匹配资产，核对官方
   SHA256，验证候选版本和配置后再原子安装到 ~/.local/bin。
8. 创建仅回环、必须认证的配置、用户专用 provider/cache、用户 systemd unit 和
   权限 600 的 client.env，全程不显示敏感信息。
9. 先运行 mihomo-userctl 测试，再把已确认端口显式传给
   install.sh --dry-run --port 和 install.sh --port --bashrc "$HOME/.bashrc"。
10. 不 enable、不设置自动启动；仅为测试手动启动服务。
11. 验证：未认证 HTTP/SOCKS 被拒绝；认证 HTTP/SOCKS5H 成功；服务 disabled；
   新 Shell direct；with_proxy 不污染父 Shell；普通 axel/S3 直连；日志和 Git
   不含敏感信息。
12. 提供精确回滚命令和脱敏验收报告。

readiness URL 必须由我通过交互弹窗确认。Mihomo 末尾保持 MATCH,DIRECT。策略
规则和订阅均属于用户已有配置；未经脱敏 diff 和我的批准，不得替换。
```

这个 Prompt 只负责让 Codex 正确编排；真正写入仍由可测试的脚本完成。项目不
推荐 `curl | bash`，因为它难以在执行前审计。
