# vNext 目标架构

- 状态：设计草案（第一阶段仅文档与定位修正，**未实现任何目标能力**）
- 对应决策：[ADR 0001 — vNext 基础决策](adr/0001-vnext-foundation.md)
- 当前已发布架构：[v0.8 架构与数据流（中文）](zh-CN/architecture.md) · [English](en/architecture.md)
- 基线：mihomo-userctl v0.8.0，commit `5c7a7ac`

本文档描述 vNext 的目标形态。**文中所有标注为"计划"的能力在当前发布版本中都不存在**，
已发布命令的行为以 [v0.8 架构文档](zh-CN/architecture.md) 为准。

## 1. 定位声明

vNext 的定位是：

> 面向共享 Linux Server 与 Remote Development 的
> **用户级 Mihomo Runtime Manager + Workload-aware Proxy Control & Verification Layer**

拆开看是两个职责：

1. **用户级 Mihomo Runtime Manager** —— 负责一个 Linux 用户自己的 Mihomo 内核、配置、
   订阅、geodata、服务与端口的完整生命周期，不需要 root。
2. **Workload-aware Proxy Control & Verification Layer** —— 负责让指定工作负载
   （Codex、OpenCode、Claude Code、VS Code Remote 等）以受控方式进入代理，
   并给出**有证据等级区分**的验证结论。

## 2. 现状审计结论

### 2.1 mihomo-userctl v0.8 当前模块职责

| 模块 | 职责 | 边界 |
| --- | --- | --- |
| `src/mihomoctl` | Bash 入口：参数解析、命令分发、`usage` 与退出码路由；信任检查后加载 `common.bash` | 不含业务判断；安全检查后 `source` |
| `src/common.bash` | 白名单解析 `mihomo-shell.conf` 与 `client.env`；owner/权限校验；八个代理变量的激活与清除；service/listener/readiness 公共检查 | 纯函数式检查，不写文件 |
| `src/shell.bash` | 交互式 Shell 入口：`proxy_on/off/status`、`with_proxy`、`mihomo_*` 兼容函数、已验证的 `CODEX_REMOTE_PAYLOAD` hook | 只能在经过 owner/权限校验后被 source |
| `bootstrap.py` | 解析最新已发布正式版本、固定到不可变 commit、建议端口、调用既有安装器 | 只安装控制层 |
| `install.sh` | 控制层安装入口；端口参数校验；首次安装强制 `--port`；既有安装必须与现有配置一致；失败回滚 | 不安装或升级 Mihomo 核心 |
| `scripts/install_support.py` | 安装事务实现：`preflight`、`generations/<id>` 准备、`publish`、`finish`、`rollback`、操作锁 | 拥有锁与备份 |
| `scripts/update.py` | 从官方 release 下载；校验 tag 格式、SHA256、归档大小与解压边界；调用同一安装器发布；保留 active/enabled 状态 | 只升级控制层 |
| `scripts/migrate.py` | 一次性、显式路径迁移：把扁平旧布局迁移到 generation 布局 | 拒绝 generation 布局的重复调用 |
| `scripts/offline_install.py` | 从本地存包目录安装；逐包 SHA256 校验；解压成员数量与总大小上限 | 缺包时报告，不转联网 |
| `scripts/acceptance.py` | 服务/监听/认证/HTTP 与 SOCKS 探针；PASS/FAIL/UNVERIFIED/DEFERRED 报告；`diagnose url` 的共用实现 | 同时服务完整验收与窄探针 |
| `scripts/diagnostics.py` | 当前 UID `/proc` 进程诊断；`codex` 快照；`codex preflight` 的唯一策略实现 | 只返回计数与分类，不返回环境值、命令行或远端地址 |
| `scripts/reporting.py` | JSON schema 常量与统一 stdout 单对象输出 | 人工说明走 stderr |
| `scripts/controller.py` | Controller client；`nodes/groups/select/latency/connections/traffic`；`setup` 与 SHA256 校验的 Dashboard 安装；TUI 与 `--plain`；policy candidate 预览/备份/应用；JS 覆写 runner | 需 PyYAML 的命令才依赖它 |
| `scripts/rules.py` | 文档约定的自定义规则三文件只读检查器（`custom-direct/proxy/reject.yaml`） | 不创建规则、不改 `config.yaml`、不下载 provider |
| `scripts/acceptance.sh` | 验收的 Shell 包装入口 | 转发参数与退出码 |

结构性问题：**读写权限没有分离**。`controller.py` 同时具备读配置和写配置的路径，
`install_support.py` 具备写文件路径，二者之间没有统一的 policy envelope；
这是 vNext 必须先解决的问题（见 §7）。

### 2.2 Mihoro 模块职责

基于审计 commit `c2b65e374d9d8a27f4eb3d2d2b5136d028563438`（v0.14.0）：

| 模块 | 职责 |
| --- | --- |
| `main.rs` / `cmd.rs` | CLI 入口与命令分发 |
| `init.rs` | 初始化与 provisioning |
| `config.rs` | 配置解析 |
| `mihoro.rs` | 业务编排 |
| `resolve_mihomo_bin.rs` | 解析 Mihomo 可执行文件位置 |
| `utils.rs` | 通用工具 |
| `systemctl.rs` | systemd 生命周期管理 |
| `ui.rs` | 终端界面 |
| `proxy.rs` | 代理环境处理 |
| `cron.rs` | crontab 自动更新 |
| `upgrade.rs` | 升级路径 |

### 2.3 功能矩阵

| 能力 | userctl v0.8 现状 | Mihoro 审计结果 | vNext 决策 |
| --- | --- | --- | --- |
| 用户级 no-root 安装 | 已实现；`systemd --user`、操作锁、generation 事务与回滚 | `init.rs` + `systemctl.rs` 覆盖 provisioning | 保留，抽象为 provisioning（P1） |
| 端口选择 | **仅"建议一个空闲端口"**：`install.sh` 的端口建议步骤打印候选、`controller.py:choose_port` 试探 bind；**启动前没有统一冲突门禁**，`start` 直接执行 `systemctl --user start` | 由 `init.rs` 与 `resolve_mihomo_bin.rs` 处理 | P0：同 UID 操作锁 + 启动前门禁 + 启动后身份确认 |
| Mihomo core 安装/更新 | **不安装也不升级 core**；`install.sh` 只装控制层 | `init.rs` + `upgrade.rs` 支持；审计**未发现 core 更新的 checksum 校验与 `mihomo -t` 门禁** | P1：实现，并强制 checksum + `mihomo -t` 门禁 |
| 订阅下载 | **不提供订阅下载器**，用户自备配置 | 支持 | P1：raw subscription 与 generated config 分离 |
| geodata 更新 | 不提供 | 支持 | P1：不依赖 workload |
| 自动更新 | **显式触发**（`mihomoctl update`），无 cron | `cron.rs` 使用 `crontab -r` 覆盖式重建 | **不移植**；保持显式、可预览、可回滚 |
| Controller client / 节点切换 | 已实现（v0.7+）：`controller setup/status/token`、`nodes`、`groups`、`select`、`latency`、`connections`、`traffic` | `ui.rs` 提供终端 UI | 保留 |
| TUI | 已实现（v0.7+）：全屏 TUI 与 `--plain` 降级路径 | `ui.rs` | P4：TUI 不自建 readiness |
| Dashboard | 已实现：经 SHA256 校验的 MetaCubeXD 静态包安装与本地 URL | 审计未发现等价的校验安装路径 | 保留 |
| per-process 代理 | 已实现：`exec` / `direct` 强制 `--`，透传子进程退出码 | 审计未发现等价能力 | 保留（差异化核心） |
| Codex fail-closed preflight | 已实现：四层状态，`0 / SAFE_TO_LAUNCH`、`1 / BLOCKED`、`2 / UNVERIFIED` | 审计未发现等价能力 | 保留，抽象为 WorkloadAdapter（P2） |
| workload-aware diagnostics | 已实现：仅同 UID `/proc`，返回计数与分类 | 审计未发现等价能力 | 保留 + adapter 化 |
| 机器可读 `--json` | 已实现：`reporting.py` 统一 schema | 审计未发现等价能力 | 保留 |
| policy 覆写 | 已实现：`override --script` 与 `--flclash-compat`；Node `vm` 明确不是安全沙箱 | 审计未发现等价能力 | P1：降级为可选 policy adapter |
| 自定义规则只读检查 | 已实现：`rules status/check` | 审计未发现等价能力 | 保留 |
| 验收证据 | 已实现：PASS/FAIL/UNVERIFIED/DEFERRED | 审计未发现等价能力 | 保留，扩展证据等级（P3） |
| 一次性布局迁移 | `migrate.py`：扁平 → generation | 审计未发现等价能力 | P0：配置迁移作为独立门禁 |
| 多用户 / 共享运行时 | `shared-runtime.md` 文档约定；**没有自动化多 UID 测试** | 审计未发现等价能力 | P0：ownership + 真实多 UID 测试 |
| TUN / 透明代理 / 系统代理 | **均不实现** | 审计未发现引入 | 明确 non-goal |

### 2.4 重复、userctl 独有与 Mihoro 独有

**重复部分**

- 用户级 no-root 安装与 `systemd --user` 生命周期管理。
- CLI 层的 `status` / `logs` / 配置路径解析与常规排错输出。
- 代理环境变量的生成与导出。
- 节点选择的终端入口。

**userctl 独有**

- shared-server 多用户共存约定与 per-user 凭据。
- per-process 代理（`exec` / `direct`）与父 Shell 不变的语义。
- workload-aware preflight 与只读诊断（fail-closed）。
- 机器可读 `--json` 输出契约。
- TUI 与浏览器 Dashboard 的组合入口。
- 安装/更新的 generation 事务与确定性回滚。

**Mihoro 独有**

- provisioning（init）与 Mihomo core 安装/更新。
- 订阅与 geodata 下载更新。
- 自定义规则只读检查以外的策略生成生态。

### 2.5 三条路线成本对比

| 维度 | Route A：现状堆功能 | Route B：fork Mihoro | Route C（已选）：保留本仓库内部重构 |
| --- | --- | --- | --- |
| 短期交付速度 | 最快 | 快 | 慢（先做重构） |
| 已发布能力回归风险 | 高（同文件持续改动） | 高（重写差异化能力） | 低（按门禁切分） |
| 安全默认值风险 | 中（需额外加固） | **高**（`0.0.0.0:9090` + 可空 secret） | 低（显式 envelope） |
| 对用户已有 crontab 的影响 | 无 | **高**（`crontab -r`） | 无 |
| Mihoro 用户迁移成本 | 无（两套并存） | 高（需重装/改造） | 低（非破坏性 adoption） |
| 长期可维护性 | 差（结构持续恶化） | 中（需长期同步上游） | 好（边界清晰） |

**不 fork 的核心理由**：安全默认值不可接受、覆盖式自动更新不可接受、差异化能力需要
重写而不是继承、且长期同步上游的成本与 provenance 风险都不成立。详见
[ADR 0001](adr/0001-vnext-foundation.md) 的 Route B 否决理由。

### 2.6 审计证据边界声明

**本节是对代码与测试结构的审查，不是运行验收报告。**

因此：

- 不能据此宣称真实多 UID 共存已在多台主机上验证通过；v0.8 的相关测试是
  **单用户内的模拟**，不构成同主机多用户测试。
- 不能据此宣称模型 E2E 已通过；`codex preflight` 的 PASS 只覆盖本地代理前置条件。
- 涉及 Mihoro 的结论均为"审计未发现"式的静态审查结论，不等于对方在所有版本和
  所有配置下都必然如此；升级对方版本后需要重新审计。
- 涉及本项目的"现状"描述来自文件与测试结构的阅读，不等于在真实服务器上跑过。

## 3. 目标架构分层

```text
┌─────────────────────────────────────────────────────────────┐
│ 接入层 Interface：CLI 子命令 / --json 输出 / TUI / Dashboard  │
└───────────────────────────┬─────────────────────────────────┘
                            │ 只消费已计算的状态
┌───────────────────────────▼─────────────────────────────────┐
│ 应用服务层 Application：runtime 生命周期编排                  │
│                              workload 启动编排               │
│                              diagnostics 编排                 │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 领域层 Domain：Runtime ownership / WorkloadAdapter          │
│                Evidence / Trace / 端口协调                   │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 能力层 Capability：controller client / policy / 事务引擎      │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ 资源层 Resource：Mihomo / systemd --user / procfs / 文件系统  │
└─────────────────────────────────────────────────────────────┘
```

### 依赖规则

这些规则是架构约束，不是建议：

1. **TUI 不自建 readiness。** TUI 只渲染已经由诊断层计算好的状态；它不得为了"显示
   绿灯"而自己发起探测或改变判定。
2. **workload 不解析订阅。** WorkloadAdapter 不知道 raw subscription 的存在，
   只消费 generated config 提供的 endpoint 与凭据。
3. **geodata 不依赖 workload。** geodata 更新是 runtime 领域的事，不经过 workload 层。
4. **policy 不自行启动服务。** policy 层只产出候选配置，不调用 `systemctl`。
5. **诊断层不产生副作用。** 诊断只读；任何改变状态的动作必须经过事务引擎。
6. **接入层不含业务规则。** CLI 只做参数解析与退出码映射，判定逻辑在领域层。
7. **能力层不得越过安全 envelope。** 见 §7。

## 4. Runtime ownership 模型

### 4.1 RuntimeDescriptor

一个 runtime 由一个显式描述符描述，至少包含：

| 字段 | 含义 |
| --- | --- |
| `id` | 本地稳定标识 |
| `kind` | `managed` 或 `adopted` |
| `binary` | 内核可执行文件路径与期望版本 |
| `config_root` | Mihomo 配置根目录 |
| `mixed_endpoint` | loopback mixed listener 与认证方式 |
| `service` | `systemd --user` 单元名 |
| `workloads` | 已知接入的工作负载 adapter 列表 |
| `source` | 追溯信息（例如 Mihoro adoption 的来源描述） |

### 4.2 按资源授权

**不使用单一 overall ownership 标记。** 四类资源各自独立：

| 资源 | `managed` 默认 | `adopted` 默认 |
| --- | --- | --- |
| binary | 可读写、可升级 | **只读引用** |
| config | 可写（经 policy envelope） | **只读引用** |
| service | 可 start/stop/restart/enable | 只读状态；写操作需显式接管 |
| workload | 可生成启动环境 | 只读观察 |

adopt 的默认行为是**只读引用**：可以 `status`、`doctor`、跑诊断、看节点，但不会
接管写权限、不会替换文件、不会改服务状态。要接管必须对具体资源显式选择，
不提供"一次性接管全部"的隐式路径。

### 4.3 零破坏检测

adopt 前必须完成的检测，任一失败即拒绝接管：

- 目标路径存在且归属预期 UID。
- 现有文件权限不宽于预期（不出现 group/other 可写）。
- 现有服务单元名与描述符一致。
- 若存在 `current`/软链接布局，确认本工具不是它的父级管理者。
- 检测结果必须先展示给用户，再要求显式确认。

## 5. 端口协调设计

**前提：回环端口是全主机资源，非特权用户无法预留。** 本设计不提供、也不宣称提供
无 root 的强端口预约；它提供的是**内核裁决 + 应用尽力协调**。

| 阶段 | 行为 | 失败处理 |
| --- | --- | --- |
| 选端口 | 在允许区间内由内核分配（bind port 0）得到候选 | 分配失败即报错，不猜测 |
| 检查 | 记录当前占用者信息到 state，供后续比对 | 记录失败不阻断，但标记证据为 inferred |
| 启动前门禁 | 在同 UID 操作锁内再次确认端口空闲；非空则拒绝启动 | **fail closed**，不尝试"清理" |
| 启动后身份确认 | 服务 up 后确认监听者确实是本用户的预期进程 | 不匹配则报告并停止，不杀他人进程 |
| 冲突处理 | 明确告知占用事实与可选动作，由用户决定 | 任何情况下不终止非本用户进程 |

硬约束：

- 绝不为了腾出端口而杀死他人进程。
- 端口冲突一律 fail closed，不降级为"带警告继续"。
- 日志与报告中的端口必须来自本次实际观测，不来自配置文件的记忆值。

## 6. 配置与状态布局

```text
$XDG_CONFIG_HOME/mihomo-userctl/          # config：人写、期望状态
    runtime.conf                          # RuntimeDescriptor
    credentials.env                       # per-user 认证（0600）
    policy/                               # local policy（人写）
        custom-direct.yaml
        custom-proxy.yaml
        custom-reject.yaml

$XDG_DATA_HOME/mihomo-userctl/            # data：安装物
    generations/<id>/                     # 控制层版本目录
    current -> generations/<id>

$XDG_CACHE_HOME/mihomo-userctl/           # cache：可重建
    subscription/raw/                     # raw subscription（0700/0600）
    geodata/
    policy-cache/

$XDG_STATE_HOME/mihomo-userctl/           # state：运行事实
    ports.json                            # 端口占用观测
    ownership.json                        # Managed/Adopted 授权
    evidence/<timestamp>.json              # 证据记录
    backups/

runtime（内存 + 临时目录）                # locks
    lock                                   # 同 UID 操作锁
```

规则：

- **敏感内容即使位于 cache 或 state 也保持 `0700` / `0600`。** raw subscription
  含节点凭据，geodata 缓存体积大但不含凭据，两者都按私有目录处理。
- **raw subscription、local policy、generated config 三者分离**，不得合并为一个文件：
  - raw subscription：外部来源，内容不可控；
  - local policy：用户手写，安全 envelope 的作用对象；
  - generated config：由前两者合成的产物，可随时重建。
- config / data / cache / state 生命周期不同：删除 cache 与 state 不得导致配置丢失，
  删除 cache 后必须能够重建。

## 7. Subscription / policy / generated config 数据流与安全 envelope

```text
raw subscription ──┐
                   ├──► policy 合成 ──► generated config ──► Mihomo
local policy ──────┘        ▲               │
                            │               ▼
                   安全 envelope        Mihomo -t 校验
                   （拒绝改写敏感键）
```

### 7.1 安全 envelope

policy 层**不得**改写以下内容（硬性拒绝，不是警告）：

- listener 地址与端口（`mixed-port`、`bind-address`、`allow-lan`）
- 认证相关配置
- `external-controller` 与 `secret`
- TUN / 透明代理相关设置
- 任何额外的监听项

policy 层的允许范围是：`proxy-groups`、`rules`、`rule-providers`（与 v0.8
`controller.py` 的 `POLICY_KEYS` 一致），并对 `external-controller` 与认证相关键做
**存在性检查**：不允许新增、不允许删除、不允许改值。

违反 envelope 的候选配置一律拒绝，并且报告具体被拒绝的键。

### 7.2 数据流规则

- raw subscription 只读，写入路径由 cache 层管理。
- generated config 是产物，可以删除重建；删除后不影响 raw 与 policy。
- 每次生成都经过 `mihomo -t` 语义校验（由用户环境中的 Mihomo 执行）。
- 替换顺序为 stage → verify → validate → commit，旧文件在 commit 前不被移除。

## 8. 生命周期事务协议与失败处理

统一阶段：

```text
discover → plan → stage → verify → validate → commit → activate → acceptance → finalize
```

| 阶段 | 含义 | 失败时 |
| --- | --- | --- |
| discover | 采集现状：runtime 描述符、端口、服务、当前配置 | 不产生任何写操作，直接失败 |
| plan | 计算目标状态与差异，向用户展示 | 展示差异，不执行 |
| stage | 写入暂存位置，**完成全部网络下载** | 丢弃暂存，旧运行不受影响 |
| verify | 校验暂存物完整性（大小、哈希、成员边界） | 丢弃暂存 |
| validate | 语义校验（`mihomo -t`、策略 envelope） | 丢弃暂存 |
| commit | 原子发布 / 切换指针 | 触发回滚 |
| activate | 重启服务使其生效 | 触发回滚 |
| acceptance | 采集证据并报告 | **报告失败，但保留已发布状态供人工判断** |
| finalize | 清理暂存与备份，写入 state | 清理失败只报告，不回滚 |

关键规则：

1. **先完成全部网络下载，再停止旧代理。** 下载失败时旧代理仍在服务，用户的
   现有工作不中断。
2. **升级失败可回滚。** 回滚目标必须是 publish 之前的可验证状态。
3. **回滚失败必须显式报告。** 不允许静默降级、不允许"部分成功"式退出码。
   回滚失败是最高优先级告警，并给出人工恢复指引。
4. acceptance 阶段的 FAIL 不触发自动回滚（此时已 commit 且是用户期望的目标状态），
   但必须以 BLOCKED 语义报告。

## 9. WorkloadAdapter 抽象

```text
WorkloadAdapter
    ├─ 启动前置条件（required capabilities）
    ├─ 进程角色判定（cli / app-server / helper）
    ├─ 启动环境构造
    └─ 恢复指引（read-only）
```

优先级顺序：

| 顺序 | Adapter | 说明 |
| --- | --- | --- |
| 1 | `GenericExec` | 不绑定任何特定 workload，供 `exec` / `direct` 使用 |
| 1 | `Codex` | 迁移 v0.5+ 的 preflight 逻辑与 `diagnose codex` 快照 |
| 2 | `OpenCode` | 计划中 |
| 2 | `Claude Code` | 计划中 |
| 2 | `VS Code Remote` | 计划中 |

### 现有 Codex 逻辑的迁移方向

v0.8 的 Codex 逻辑位于 `src/mihomoctl`（`cmd_codex`）与
`scripts/diagnostics.py`（`codex_snapshot`、`codex_preflight`）。迁移方向：

- **保持不变**：判定策略、四层状态名称、`SAFE_TO_LAUNCH` / `BLOCKED` / `UNVERIFIED`
  与退出码 `0` / `1` / `2`、只读与不杀进程约束。
- **需要抽取**：`codex_preflight` 中的角色判定（`cli-or-helper` / `app-server`）
  与 `expected_environment()` 属于 adapter 契约；进程枚举与 `/proc` 读取属于通用能力。
- **需要泛化**：当前 `preflight_error()` 把 `codex` 键名硬编码在公共预检结构里，
  泛化后由 adapter 提供键名集合，但 JSON 字段名保持不变以维持兼容。
- **不做**：不把 Codex 特有判断抽象成一个"通用 AI CLI 基类"——各家的进程角色与
  恢复路径差异很大，通用部分仅限于进程枚举、环境比较和证据渲染。

## 10. Evidence / Trace 层级

### 10.1 两个正交维度

**check 状态**（回答"检查本身是否通过"）：

| 状态 | 含义 |
| --- | --- |
| `PASS` | 检查执行完成，且观察到预期结果 |
| `FAIL` | 检查执行完成，且观察到非预期结果 |
| `UNVERIFIED` | 检查无法完成，或所需观察手段不可用 |
| `SKIPPED` | 因前置条件不满足而未执行 |

**证据等级**（回答"结论有多可靠"）：

| 等级 | 含义 |
| --- | --- |
| `confirmed` | 直接观测到目标事实 |
| `inferred` | 由间接证据推导，**不得呈现为已验证** |
| `unavailable` | 观察手段不可用 |

`UNVERIFIED` 是合法终态，不是失败；但它**不得**被降级呈现为 `PASS`。

### 10.2 证据能力与边界

| 观察手段 | 能证明 | 不能证明 |
| --- | --- | --- |
| 服务状态查询 | systemd 单元处于 active | 监听端口属于谁、配置是否正确 |
| loopback 监听探测 | 某地址上有监听 | 监听者身份与预期一致 |
| 认证 HTTP 探针 | 该次请求经认证代理完成 | 流量经过哪个节点、是否出网 |
| 进程环境读取（创建时继承） | 进程**创建时**继承了什么 | 该进程当前实际使用的网络路径 |
| PPID / 进程树 | 父子创建关系 | **PPID 不证明复用**：父子关系不能证明 app-server 复用了父进程的代理 |
| Controller 节点选择状态 | 某策略组当前选中了某节点 | **节点 selection 不证明某次请求**：某次具体请求可能未经过该节点 |
| 连接进入 Mihomo | 请求进入了 Mihomo 进程 | **进入 Mihomo 不代表经过远端代理**：可能是 DIRECT 规则命中 |
| 未观察到 socket | 在观测窗口内没看到 | **未观察到 socket 不等于直连**：可能是观测失败、连接已关闭或权限不足 |
| `/proc/<pid>/environ` | 读取瞬间内核暴露的初始环境块 | **`/proc/<pid>/environ` 不是可靠的运行时环境观察接口**：进程内部 `setenv`/`unsetenv` 不会反映到该文件 |

### 10.3 Trace 层级

Trace 用于回答"这一次操作实际发生了什么"，分四级：

| 层级 | 含义 | 来源 |
| --- | --- | --- |
| L0 意图 | 用户请求的操作 | CLI 解析结果 |
| L1 决策 | 领域层判定与理由 | Evidence 汇总 |
| L2 执行 | 实际调用的外部命令与顺序 | 事务引擎记录 |
| L3 观测 | 事后观察到的系统事实 | 验收与诊断 |

L0/L1/L2 属于 `confirmed`（本工具自己的行为）；L3 常常只是 `inferred`。
报告必须分别标注，不允许把 L2 的成功直接表述为 L3 的成功。

## 11. 阶段计划

> **以下 P0–P5 全部尚未实现。** 当前发布版本 v0.8.0 不包含其中任何一项。
> 文档中出现这些名称仅为记录已批准的路线，不是可用命令。

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| **P0** | Runtime ownership 与 RuntimeDescriptor；按资源授权与 adopt 只读默认；端口协调（同 UID 锁、启动前门禁、启动后身份确认、fail closed）；config/data/cache/state 分层；事务契约定义 | **尚未实现** |
| **P1** | `init`（provisioning）、core 安装/更新（带 checksum 与 `mihomo -t` 门禁）、订阅下载（raw 与 generated 分离）、安全 controller（仅 `127.0.0.1` + per-user 认证）、geodata 更新；`policy/native` 与 `policy/flclash-js-compat` 拆分为可选 adapter | **尚未实现** |
| **P2** | WorkloadAdapter 抽象；把现有 Codex 逻辑迁移为 adapter，行为保持不变 | **尚未实现** |
| **P3** | Evidence 模型扩展（证据等级）、Trace 四级、统一报告渲染 | **尚未实现** |
| **P4** | TUI 强化：消费领域层状态，不自建 readiness | **尚未实现** |
| **P5** | OpenCode / Claude Code / VS Code Remote adapter | **尚未实现** |

阶段之间的门禁：P(n+1) 的实现不得在 P(n) 的门禁未通过时合入。门禁定义见 §12。

## 12. 测试分层要求

| 层次 | 内容 | 当前状态 |
| --- | --- | --- |
| 单元 / 契约 | 解析器、白名单校验、descriptor、policy envelope、事务阶段机 | 部分已有 |
| 故障注入 | 网络失败、磁盘满、权限错误、`systemctl` 不可用、回滚失败 | 部分已有（`audit-test.sh` 等） |
| 真实 Linux 集成 | 真实 `systemd --user`、`ss`、`curl`、`journalctl`、真实 Mihomo | 需专用 runner |
| **真实多 UID** | 同一主机上两个及以上真实 Linux 账户的共存验证 | **缺失** |
| workload 实测 | 真实 Codex 进程的启动、恢复与网络路径观察 | 部分已有 |
| v0.8 差分回归 | 已发布命令的输出、退出码、JSON schema 与 v0.8 保持一致 | 需在每个迁移门禁执行 |
| 泄露检查 | 凭据、个人路径、维护者私有策略字符串不得进入公开文档 | 已有（`secret-scan.sh`、`docs-test.sh`） |

### 模拟 UID 不能替代真实同主机多用户测试

v0.8 现有的多用户相关测试是在**单用户内模拟**身份与路径布局的。它无法覆盖：

- 真实的 loopback 端口在跨 UID 场景下的可观测性；
- `/proc` 可见性受 UID 隔离影响后的诊断行为；
- `systemctl --user` 在多 session 下的实际状态差异；
- 文件权限位在真实多账户下的实际效果。

因此**不得**用模拟测试结果宣称"多用户共存已验证"。该结论只能来自真实多 UID 测试。

## 13. Non-goals

以下内容 vNext 明确不做，任何文档都不应承诺：

1. 不做 FlClash / Clash Verge 的 replacement。
2. 不做桌面 GUI。
3. 不做 TUN 或透明代理，不修改系统路由。
4. 不做通用 YAML editor。
5. 不做无 root 的强 UID 网络隔离；认证不等于防火墙隔离。
6. 环境变量不是网络强制策略：它只在进程创建时继承，且进程可以自行修改。
7. readiness 通过不等于模型 E2E 成功。
8. 不接管用户的 crontab。
9. 不终止其他用户（或无法确认归属）的进程。
10. 不把推断结果呈现为已验证的证据。

---

## English summary

**architecture-vnext.md** describes the target design for mihomo-userctl vNext. The
positioning is a **user-level Mihomo Runtime Manager plus a workload-aware proxy control
and verification layer for shared Linux servers and remote development**. The document
records an honest audit of the current v0.8 module layout and of Mihoro at commit
`c2b65e37` (v0.14.0), a capability matrix of what exists today versus what is planned,
and an explicit statement that this is a **code and test structure review, not a runtime
acceptance report** — so it does not claim verified multi-UID coexistence or model E2E
success. It then specifies the layered target architecture with its dependency rules,
per-resource Managed/Adopted runtime ownership, best-effort port coordination (kernel
adjudicated, no claim of rootless strong reservation), XDG config/data/cache/state
layering, the subscription/policy/generated-config data flow with a security envelope,
the transaction protocol (download before stopping; rollback failure must be reported
explicitly), the WorkloadAdapter abstraction, and the Evidence/Trace model with its
explicit limits — for example a parent PID does not prove reuse, node selection does not
prove a specific request, entering Mihomo does not mean the traffic used a remote node,
an unobserved socket does not mean a direct connection, and `/proc/<pid>/environ` is not
a reliable runtime environment interface. Phases P0–P5 are listed and **every one of
them is not yet implemented**; the corresponding `mihomoctl` commands do not exist in
the current release.