# 安装与运行排障

- 完整包找不到核心：保留整个解压目录，检查摘要与权限，再使用首次运行向导。源码、wheel 及旧式 wheelhouse 套件不含核心。新装按 [初始化教程](setup.md) 复用可信核心或显式安装固定版本，再 init 一次；已有 manager 不重复初始化，也不盲目 core install。
- NAS 或 wheelhouse 权限被拒：复制所需整套材料到本人私有目录再核验，不递归放宽权限。核对 [两种离线包布局](offline-install.md)。
- Python/目标不匹配：受支持的 Ubuntu x86_64 机器优先使用完整包；源码/wheelhouse 安装还需核对系统 Python；不要把其他目标套件强装。严格离线缺核心或依赖时提前准备。
- 安装脚本后续下载 DNS 失败：检查整个安装 Shell 是否在 exec 内；外层管道右侧不会继承左侧变量。
- Bash 报 `<` / HTML 语法错误：下载到的可能是地区限制或登录网页。curl -f 不拒绝 HTTP 200 HTML。停止执行，按 [下载审阅与代理继承教程](first-run.md#通过代理安装第三方-cli) 检查，不关闭 TLS 校验。
- init 成功但 exec 被健康门阻止：默认初始化不启动。准备好后显式 start，检查配置、端口和日志。不要用尚未运行的代理下载自身核心。
- 本地请求成功却未走远端：高级 CLI init 默认为 MATCH,DIRECT，新用户简单向导配置 Proxy 路由；以实际活动配置为准，检查订阅、规则、NO_PROXY 和真实客户端连接链，见 [分层验证](first-run.md)。

## 所有节点测速失败 / unknown-node / 引用对象缺失

先运行 `mihomoctl nodes --json`，将核心实际名称与错误中显示的请求名称逐字符核对，包括空格、旗帜 emoji 与地区缩写（例如 🇺🇸 与 US 不同）。`unknown-node` 表示查询前核心表中就没有该名称；延迟接口的 404 为 `node-not-in-core`，表示请求时节点已不在核心表。分组的 `missing_member_count` 和最多五个 `missing_members` 可在分组结果中查看，编号菜单提示及 Textual `: chain` 会解释缺失引用。

检查 `mihomoctl providers --json`、订阅/提供商加载状态和 `mihomoctl logs`，确认上游没有重命名节点、Provider 缓存可读且已加载。必要时显式 `mihomoctl provider refresh NAME`，或审阅后重新导入订阅；配置保存后运行 `mihomoctl restart`，再核对核心节点表。不要只凭磁盘配置或界面旧快照判定节点存在。

503 `node-unreachable` 是节点存在但探测失败，504 `delay-timeout` 是探测超时；此时检查节点可达性、出站网络及公共目标 `https://www.gstatic.com/generate_204` 的可达性，不应按“核心不支持 API”处理。延迟成功也不验证模型业务。完整包已内置 Textual，运行 `mihomoctl` 在节点页执行单点或批量测速；编号菜单用于基本选择，`mihomoctl tui --engine curses` 还提供 `t` 测速快捷键。见 [终端指南](console.md)。探测配置必须写 `group "名称"` 或 `provider "名称"`；Selector 应探测其背后的 provider。

报告控制器、核心、初始化、运行态及真实远端请求各阶段的 PASS/FAIL/UNVERIFIED。不要上传原始凭据或连接明细。

## 更新或恢复无法继续

`installation-console-open` 表示本账号其他界面仍打开，关闭后再试；核心可继续运行。`operation-committed-cleanup-pending` 表示修改已提交、清理尚待重试，不能据此认为旧版本仍在运行；下次加锁操作会继续清理。恢复错误或漂移提示会保留临时材料，避免覆盖无关手动修改，请先检查脱敏错误再重试。不再提供历史回滚命令或恢复备份按钮。
