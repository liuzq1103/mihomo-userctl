# 控制台

## 选择界面

`mihomoctl tui` 能导入 Textual 时使用任务界面，否则进入编号菜单。启动界面不会自动安装任何依赖。适合 SSH PTY、tmux 和无桌面的 Linux；需要交互终端。

| 入口 | 适用场景 | 测速 |
| --- | --- | --- |
| `mihomoctl tui --engine plain` 或 `--plain` | 无额外 UI 依赖的编号菜单：状态、节点选择、订阅、控制器初始化、启停、模式、恢复、探测配置、日志和接入 | **没有测速功能** |
| `mihomoctl tui --engine curses` | 使用标准库 curses 的双栏分组/节点界面，无需额外安装 | `t` 测试当前节点，`c` 连接，`f` 流量 |
| `mihomoctl tui --engine textual` | 完整页面、搜索、单点/批量测速、诊断与事务预览 | `t` 单点，`T` 批量 |

不知道命令时运行 `mihomoctl --help`，按常用、服务与配置、节点与路由、环境与接入、安装与发行分组浏览英文说明。直接运行 `mihomoctl` 也显示该指南，随后以退出码 2 提示缺少命令。

## 用户私有安装 Textual

基础 CLI 要求 Python 3.10+。在与目标解释器、架构匹配的联网准备环境下载锁定的 wheel（此步骤由用户显式执行）：

```bash
python3 -m pip download --require-hashes --only-binary=:all: \
  -r scripts/textual-requirements.txt -d /ABS/wheelhouse
bash install.sh --user --python /usr/bin/python3 --wheelhouse /ABS/wheelhouse --extras tui
mihomoctl tui --engine textual
```

私有安装的统一命令为 `bash install.sh --user --python <python> --wheelhouse <wheelhouse-dir> --extras tui`。

在完整发行源码目录执行安装。`--extras` 可重复；`tui` 固定为 textual==8.2.8。明确请求 extra 时，wheelhouse 须含 PyYAML、Textual 及全部依赖；缺包以 `extra-wheels-unavailable` 报告组名和缺失依赖。安装器只读取本地 wheel，绝不下载、不运行系统 pip、不写系统 site-packages，因此无需 sudo。依赖和主程序一起解包到当前用户 generation 的 `lib/`，按同一所有权、摘要与只读机制管理；启动器将该目录加入导入路径。未知 extra 报 `unknown-extra`。未选择 extra 的新装不会额外安装 UI；升级未指定 extras 时沿用当前选择，当前 wheelhouse 缺少可选依赖时，将旧代中已归属该 extra 且通过摘要验证的模块与分发元数据复制到新代，并用 `extras_carried_forward` 报告，因此 PyYAML-only 离线包也能升级。若没有已归属的副本，则移除该组，并在结果和记录中明确报告 `extras-dropped`。`extra_packages` 记录每组贡献的顶层文件/目录，`bootstrap.py verify/status` 可查看 extras。

`mihomoctl update --extras tui --wheelhouse /ABS/wheelhouse` 明确选择，`mihomoctl update --no-extras` 明确清空；可与本地来源或 `--latest` 配合。bootstrap `install` 支持同样的互斥选项。两者都省略才表示继承，明确清空不会重新继承。

若当前解释器不能导入 textual/rich，可直接用 `mihomoctl tui --engine curses` 并按 `t` 测速，或按上面的私有安装命令补齐。当前离线发行包不额外携带 Textual wheels。

## 页面与测速

主入口为首页、节点、订阅、接入；“更多”包含其余页面。80×24 使用完整布局，60×14 使用紧凑布局。`--ascii` 使用 ASCII 标记；`--theme dark|light` 选择主题，`NO_COLOR=1` 关闭颜色。无需特殊字体。

| 页面 / `page` 名称 | 内容 |
| --- | --- |
| 首页 / overview | 控制器与服务状态、速率、内存、连接、初始化、启停重启、模式 |
| 节点 / proxies | 双栏分组与节点，搜索、排序、选择确认、测速、手动组和可信 JS 预览 |
| 订阅 / subscriptions | 来源、导入策略、计数、预览、保存与待重启状态；旧名称 profiles 仍映射到此页 |
| 接入 / profile | 脱敏代理档案、接入声明与环境注入边界，不管理第三方程序生命周期 |
| 连接 / connections | 只读链路与流量，搜索、排序、暂停；不关闭连接 |
| 规则 / rules | 规则类型计数与 Provider 状态，不显示私有规则正文 |
| 日志 / logs | 实时日志、级别、暂停；`: journal` 查询服务历史 |
| 提供商 / providers | 类型、节点数、更新时间及显式刷新 |
| 诊断 / diagnostics | 通用健康检查和证据等级 |
| 服务 / runtime | 核心、控制器、监听、生效配置、代理模式、TUN、错误七项事实 |

节点页先选组再选节点。Selector 回车选择，自动组只读，由核心选择。`t` 测当前节点，`T` 确认后测试当前可见节点，最多 4 路并发；延迟毫秒列显示 `delay_ms`。目标固定为 `https://www.gstatic.com/generate_204`，这是公共 HTTPS 连通延迟，不是带宽，也不是模型端到端请求；`model_request: UNVERIFIED` 表示未验证模型业务。`: cancel` 或 Esc 停止排队项，已开始的请求等待超时。可用 `v` 查看完整结果。

404 为 `node-not-in-core`（节点不在核心代理表中），503 为 `node-unreachable`（节点存在但探测失败），504 为 `delay-timeout`（探测超时）。请求前查不到名称则为 `unknown-node`，错误包含实际查询名称。批量失败行保留相同错误码。`: chain` 显示当前链路、已有自动路径、共享入口及缺失成员原因，不改变链路结论。恢复方法见 [排障](troubleshooting.md)。

## 键盘和命令

Textual：Tab/Shift+Tab 切焦点，方向键浏览，Enter 选择/确认；`/` 搜索，`r` 刷新，`t` 单点测速，`T` 批量，`[`/`]` 前后分组；`p` 暂停连接/日志，`s` 排序，`c` 连接，`f` 流量，`v` 完整结果；`m` 手动组转换预览，`o` 可信脚本预览，`y` 审阅确认保存；Esc 取消输入、预览或排队测速，`q`（非输入状态）/Ctrl+C 退出，`?` 帮助，`:` 输入命令。输入框中的字母不会触发全局操作。

curses：↑↓ 浏览，Tab/←/→ 切面板，Enter 进入节点或选择；`/` 搜索，`r` 刷新，`t` 测速，`c` 连接，`f` 流量，`m` 手动组预览，`o` 脚本预览，`y` 保存，`q`/Esc 退出。底部两行图例按显示宽度绘制。plain 按显示的编号操作，没有 Textual 的快捷键或测速。

Textual 的 `:` 命令（并非 Shell 命令）：

```text
page overview|proxies|subscriptions|profile|connections|rules|logs|providers|diagnostics|runtime
group GROUP_NAME
start
stop
restart
mode rule|global|direct
dns NAME [TYPE]
provider NAME
subscribe /ABS/private-nodes.yaml
subscribe-url /ABS/private-url.txt
chain
health-check group "Auto" --preset resilient
health-check provider "nodes" --timeout 5000
health
ready
doctor
status
profile
profiles
rules-status
rules-check
journal --since "2026-10-01" --until "2026-10-22"
diagnose url PUBLIC_HTTPS_URL
diagnose process PID
cancel
log-level debug|info|warning|error
theme dark|light
```

## 探测配置与保存

CLI 示例先预览，审阅后用 `--apply` 保存：

```bash
mihomoctl health-check group "Auto" --preset resilient --json
mihomoctl health-check provider "nodes" --timeout 5000 --json
```

编号菜单的“探测配置”以及 Textual `: health-check` 后，必须先写字面量 `group` 或 `provider`，再写名称，例如 `group "Ai+"`，不能只写 `Ai+`。`group` 仅接受配置中的 `url-test` / `fallback`，不接受 Selector；要探测 Selector，找它背后的 provider 并用 `provider NAME`。选项为 `--url`、`--expected-status`、`--interval`（秒）、`--timeout`（毫秒）、`--lazy true|false`、`--tolerance`（毫秒）及 `--preset resilient`。Textual 中 `y` 确认保存；保存后仍需显式重启，订阅再次导入可能覆盖探测调整。Provider 探测会影响引用它的所有分组。

刷新保留选择与搜索；失败保留旧快照并标记 stale 和错误，未观测事实保持 UNVERIFIED。写操作不自动重放；保存与运行生效分开，重启会中断连接。`--details` 显式允许私有连接/日志详情，已知凭据仍遮罩，默认不导出日志。

订阅、规则和策略事务使用相同 manager、核心路径和安全门禁。详见 [订阅](subscriptions.md)、[规则](rules.md) 和 [命令参考](reference/cli.md)。本地 JS override 只能执行可信代码，Node vm 不是沙箱。
