# Server-first Mihomo 控制台（v0.9.0）

已有 `mihomoctl tui` 继续默认使用 curses。可选 Textual 控制台适用于 SSH 分配的 PTY、tmux 和 headless Linux，不需要浏览器或额外监听端口。所有界面均调用同一服务层；普通 Shell 保持直连，切换节点保留现有连接。

## 安装和降级

基础 CLI 保持 Python 3.8+；Controller 功能仍需 PyYAML。Textual 单独使用 Python 3.9+，从当前源码目录显式安装：

安装可选环境后，Controller 命令和 start/restart 校验也使用该私有环境内锁定的 PyYAML，无需向系统 Python 安装依赖。

```bash
bash install.sh --port YOUR_PORT --with-textual --tui-python python3
mihomoctl tui --engine textual
mihomoctl tui --engine curses
mihomoctl tui --plain
```

已有安装省略 `--port`。安装器创建 generation 内的私有 venv，使用固定版本、SHA256 和仅 wheel 安装，不使用系统 pip、不执行 sudo、不启动或 enable Mihomo。缺少 Textual 时显式报错，运行界面不会联网安装依赖。发行版没有 ensurepip 时，使用已固定哈希的 pip wheel 在新 venv 内引导。

离线安装需提前在与目标 Python/架构相符的环境准备完整 wheelhouse：

```bash
python3 -m pip download --require-hashes --only-binary=:all: \
  -r scripts/textual-requirements.txt -d /ABSOLUTE/wheelhouse
bash install.sh --with-textual --tui-python python3 --wheelhouse /ABSOLUTE/wheelhouse
```

wheelhouse 包含 pip 引导 wheel 和全部依赖。目录须归当前用户所有、无不安全的可写祖先、无符号链接。离线模式不回退联网；缺包或哈希错误使安装失败并恢复活动安装。普通更新在锁文件不变时复用已安装的私有环境，不下载 UI 包；锁文件变化时须显式重新使用 `install.sh --with-textual`。旧 generation 和环境由现有回滚生命周期保留。

## 页面和键盘

| 页面 | 内容 |
| --- | --- |
| Overview | 服务观测、独立的监听/认证/就绪结论、版本、速率、内存、连接数和策略组选择 |
| Proxies | 双栏组/节点、搜索、排序、选择确认、单点和批量测速、手动组/JS 策略预览 |
| Connections | 只读链路与流量、搜索、排序、暂停；无关闭连接功能 |
| Rules | 按类型汇总运行规则及规则 Provider 状态；不显示私有规则正文 |
| Logs | Controller 实时日志、有界缓冲、级别过滤和暂停；`: journal` 查看用户服务最近 200 条日志 |
| Profiles | 磁盘配置计数；明确区分保存与当前运行状态 |
| Providers | 节点 Provider 类型、节点数、更新时间；显式刷新 |
| Diagnostics | 离线 doctor 与 Codex 诊断；preflight/ready 由显式命令触发 |
| Runtime | 用户服务状态；启停/重启由显式命令和确认触发 |

Tab/Shift+Tab 切焦点，方向键浏览，Enter 选择。`/` 搜索，`r` 刷新，`t` 单节点测速，`T` 确认后测试当前可见节点（最多 4 并发），`p` 暂停连接/日志展示，`s` 切换排序，`c` 查看连接，`f` 获取流量，`v` 查看完整操作结果。测速不代表模型 E2E。

保留 `m` 手动组预览、`o` 显式可信 JS 预览、`y` 查看并确认保存。Esc 取消输入、候选或排队测速，`q` 在非输入状态退出。输入框里的字母不会触发全局操作。`[`/`]` 切换组，紧凑布局也可用。`?` 帮助，`:` 打开命令输入：

```text
page proxies
group GROUP_NAME
start
stop
restart
mode rule
dns example.com A
provider PROVIDER_NAME
subscribe /ABSOLUTE/private-nodes.yaml
subscribe-url /ABSOLUTE/private-url.txt
cancel
log-level warning
ready
doctor
codex
rules-status
rules-check
theme light
```

鼠标为辅助操作；80×24 是完整布局，60×14 使用紧凑布局，更小终端显示指引。`--ascii` 使用 ASCII 选择标记；`--theme dark|light` 切主题，`NO_COLOR=1` 禁用颜色，不依赖 Nerd Font。`--details` 显式允许私有连接主机、规则匹配内容和日志正文；日志仍遮罩已知凭据。默认不导出日志。

刷新保留搜索、组、节点和滚动位置。失败保留旧快照并显示 stale、时间和错误；404/405 显示 unsupported，认证失败不是“不支持”。流量每秒采样，当前连接页每 2 秒刷新，组/服务每 5 秒刷新。日志最多 2,000 条，重连按 1/2/4/8/15 秒退避并重新验证。写操作不自动重放。

## 安全的节点订阅

首版仅接受顶层只有 `proxies` 的 Mihomo 节点 YAML（也包括这种格式的 Provider 内容）。不接收完整配置、Base64、URI 列表或外部 Provider 定义。现有同名节点替换，其余保留；不会删除节点或自动修改组成员。

```bash
chmod 600 /ABSOLUTE/private-nodes.yaml
mihomoctl subscription preview --source-file /ABSOLUTE/private-nodes.yaml --json
# 阅读逐节点变更，保留返回的 ID 和 SHA256，然后显式应用
mihomoctl subscription apply PREVIEW_ID --sha256 PREVIEW_SHA256 --json
```

HTTPS 来源通过 `--url-file` 指定私有文件，或用 `--stdin` 读取节点 YAML；URL 和凭据不进入 argv。下载直接连接、校验 TLS、拒绝重定向/压缩，限制 8 MiB 和超时。界面中的 `subscribe`/`subscribe-url` 先预览，`y` 确认保存。

raw、候选和计划位于私有 `mihomo-userctl-subscriptions` 目录（0700，文件 0600）。应用匹配候选和原配置摘要，并再次验证只能改 `proxies`；锁内执行 Mihomo 校验、漂移检查、备份、原子替换。失败保留活动配置；保存返回 `restart-required`，不自动重启或添加定时任务。JS 的既有策略三键白名单保持独立。

## 启动门禁和边界

start/restart 在同 UID 操作锁内检查 mixed/controller 端口。外 UID、通配/IPv6 监听冲突即阻断；同 UID 监听必须关联服务 MainPID/cgroup，归属不明返回 UNVERIFIED。启动后复核服务监听，已配置的 Controller 重新验证 UID、loopback 和匿名访问拒绝。不会静默改端口或终止占用进程；bind 探测不是端口预约。

磁盘配置存在时需 PyYAML 解析端口；缺少解析能力不能通过门禁。服务停止不新增门禁。runtime mode 只 PATCH `mode` 并回读，不修改 Shell 或磁盘。Provider 刷新由 Mihomo 执行，显式触发网络下载。DNS 查询不修改系统 DNS。

`: diagnose url PUBLIC_HTTPS_URL` 显式运行现有网络诊断，拒绝 userinfo、query 和 fragment；`: diagnose process PID` 复用现有当前 UID 进程诊断。报告保留原有证据状态，按 `v` 查看完整结果。

不实现 core 安装/adoption、TUN、系统代理、完整配置导入、任意远程 Controller 或常驻管理 daemon。loopback 认证不等于强 UID 防火墙。真实 systemd、多 UID 和 SSH 验收见 [控制台验收](console-acceptance.md)。
