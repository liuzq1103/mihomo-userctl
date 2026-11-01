# 1.5.0 release notes / 发布说明

mihomoctl remains a user-level Mihomo manager for shared Linux servers. The Python distribution and new release assets are named `mihomo-userctl`; the CLI, import package, XDG paths and service names remain `mihomoctl`. User/process mode, authenticated loopback listeners and per-user ownership checks remain the defaults. System operations still require explicit `--system` authorization.

mihomoctl 继续面向多人共享 Linux 服务器上的用户级 Mihomo 管理。Python 分发包与新发行资产统一使用 `mihomo-userctl`，CLI、import 包、XDG 路径和服务名保持 `mihomoctl`。默认仍为 user/process 模式、经过认证的回环监听及逐用户所有权检查；系统级操作仍须显式指定 `--system` 并满足权限要求。

Top-level and command help now explain Agent workflows, side effects and authorization boundaries. The existing `mihomoctl/v1` JSON envelope, legacy fields and exit semantics remain compatible. Observe the current state, make one authorized change, verify the result, then explicitly restore any temporary node selection. The terminal UI is an interactive human interface.

顶层与子命令帮助补充 Agent 工作流、副作用及授权边界，保留既有 `mihomoctl/v1` JSON envelope、历史字段和退出语义。操作流程为观察当前状态、执行一次已授权调整、验证结果，再显式恢复临时节点选择。终端界面面向交互式人类操作。

Selectors containing subgroups protect direct non-Direct leaf selection by default. `select GROUP NODE --allow-cross-level` authorizes only that hierarchy step; it cannot bypass scope, authentication, ownership, membership or ambiguity checks. CLI and terminal frontends share the selection guard and read-back verification. Current selection persistence is retained; no selection-history or cache-deletion subsystem is added.

包含子组的 Selector 默认保护对非 Direct 叶子节点的直接选择。`select GROUP NODE --allow-cross-level` 仅授权此项跨层操作，不能绕过 scope、认证、属主、成员及歧义检查。CLI 与各终端前端共用选择保护和写后读回复核。继续保留当前选择持久化，不新增选择历史或缓存删除系统。

Reset now requires a read-only `--dry-run` preview followed by explicitly authorized `--apply --plan-sha256 HASH`. The digest binds the acting user, scope, effective core and affected file state, including runtime state; drift requires a new preview. Strict file trust checks remain in force. Recovery failures retain journals and report safe errors, and refused selections keep the plain terminal menu interactive.

reset 现须先执行只读 `--dry-run` 预览，再经明确授权使用 `--apply --plan-sha256 HASH`。摘要绑定操作用户、scope、有效核心及受影响文件状态，也包含运行时状态；发生变化须重新预览。严格文件信任检查继续保留。恢复失败保留事务日志并返回安全错误，plain 终端菜单在选择被拒绝后仍可继续交互。

Standard Python installation supports uv, pipx, pip user where the interpreter permits it, venv, offline wheelhouses, source and editable installs. PyYAML remains required and Textual remains optional. External Python installations use their original package manager for upgrades and removal; built-in self-update refuses to take them over. Ubuntu PEP 668 may reject `pip --user`; use uv, pipx or a venv instead. See the [Python installation guide](en/python-install.md) and [中文安装指南](zh-CN/python-install.md).

标准 Python 安装支持 uv、pipx、解释器允许时的 pip user、venv、离线 wheelhouse、源码及 editable 安装。PyYAML 仍为必要依赖，Textual 仍为可选依赖。外部 Python 安装由原包管理器升级和卸载，内置更新器拒绝接管。Ubuntu PEP 668 也可能拒绝 `pip --user`，应使用 uv、pipx 或 venv，详见上述双语安装指南。

Complete offline bundles retain the pinned Python, Textual, dependencies and Mihomo core. The 1.4.x updater cannot discover the renamed release assets: verify and run the new complete bundle's installer for the one-time migration. Configuration, credentials, the running core and current selection are preserved by the tested migration; only current program code is retained. See [offline installation](en/offline-install.md) and [中文离线安装](zh-CN/offline-install.md).

完整离线包继续包含固定版本的 Python、Textual、依赖及 Mihomo 核心。1.4.x 更新器不能发现改名后的资产，须核验新版完整包并运行其安装器，完成一次性迁移。已验收的迁移保留配置、凭据、运行中的核心和当前节点选择；程序代码继续只保留当前版本。详见上述双语离线安装指南。

Publication requires exact-commit two-Ubuntu acceptance, reviewed asset inventories and valid independent reviews of the exact candidate SHA and actual draft asset hashes. PyPI uses manual Trusted Publishing with protected environment approval and the same accepted wheel/sdist, without rebuilding them. Development versions cannot be formally published. Quota failures and interrupted reviews are not approval; public-index installation is verified only after publication.

正式发布要求同提交的双 Ubuntu 验收、发行清单，以及对完整候选 SHA 和实际草稿资产摘要的有效独立审核。PyPI 使用手动 Trusted Publishing 和受保护环境审批，上传同批验收通过的 wheel/sdist，不重新构建。开发版不得正式发布；配额失败或中断的审核不算批准，公共索引安装仅在发布后验证。
