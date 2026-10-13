# ADR 0001：vNext 基础决策（保留本仓库，Route C）

- 状态：**Proposed**（等待发布确认）
- 日期：2026-10-07
- 适用版本：vNext 第一阶段（本阶段仅文档与定位修正，不改变任何产品行为）
- 决策者：mihomo-userctl 维护者
- 相关文档：[vNext 目标架构](../architecture-vnext.md) · [当前架构（v0.8）](../zh-CN/architecture.md)

## 背景与决策驱动因素

mihomo-userctl v0.8.0 已经是一个可用但结构上"扁平"的用户级 Mihomo 控制层。
它把服务生命周期、凭据激活、Codex 门禁、诊断、控制面和策略覆写都放在同一个
Bash 入口加若干平铺 Python 模块里，功能持续增长而内部边界没有同步收敛。

同时，[Mihoro](https://github.com/spencerwooo/mihoro)（审计 commit
`c2b65e374d9d8a27f4eb3d2d2b5136d028563438`，v0.14.0）在 provisioning、Mihomo core
更新、订阅与 geodata 管理上覆盖了更大的生命周期范围。对同一个用户遇到同一类问题，
存在两条不同的产品路线可以走。

驱动本决策的因素：

1. **不能为了"更全"而牺牲已经验证过的差异化能力。** shared-server 多用户共存、
   per-process 代理、fail-closed preflight、机器可读输出和 TUI 是本项目已发布并
   有测试覆盖的资产。
2. **不能靠"更全"来掩盖"更不安全"。** 对比对象的若干默认值在本项目的威胁模型下
   不可接受，照搬会降低而不是提高安全性。
3. **用户已经在用 Mihoro。** 任何让既有用户被迫重装的方案都是失败的。
4. **本项目定位需要一次明确的收敛。** 继续在现状上叠加功能会让模块职责、配置分层、
   端口语义和证据语义继续纠缠，最终无法安全演进。
5. **技术栈迁移是手段而不是目的。** 决定做什么之后，才决定用什么写。

## 决策

**KEEP CURRENT REPO —— 采用 Route C。**

保留 mihomo-userctl 的产品定位与仓库主体，在其内部做模块化重构；吸收 Mihoro 的
生命周期管理设计（provisioning、core、subscription、geodata 的产品形态）；支持对
已经存在的 Mihoro runtime 进行非破坏性的 adoption；**不建立 permanent fork**。

"吸收设计"指吸收职责划分、事务顺序和用户可见形态，不指复制源码、品牌或资产。

## 被否决的方案

### Route A：继续在现状上堆功能

把 vNext 的 init / core / subscription / geodata 直接加进当前 `src/mihomoctl` 与
`scripts/*.py` 的现有结构。

**否决理由：**

- 职责边界无法收敛。新增的 core 更新、订阅下载和 geodata 更新都需要读取并校验
  配置、持有写权限、执行回滚，而当前结构里"能读配置"和"能改文件"的模块没有分离，
  安全 envelope 无处安放。
- 端口语义会继续含糊。当前只有"建议一个空闲端口"，没有统一的启动前门禁和启动后
  身份确认；在叠加 core/订阅流程后，端口冲突会变成难以定位的运行时故障。
- 迁移成本会被推迟而不是消除。结构不变时，每一次功能增加都会抬高下一次迁移的成本。
- 回归风险不可控。已发布的命令、退出码和 JSON schema 都在同一批文件里，改动面无法隔离。

### Route B：fork Mihoro

以 Mihoro 为基础建立本项目的 fork，在其代码上发展。

**否决理由：**

- **安全默认值不可接受。** 审计发现其默认 `external-controller: 0.0.0.0:9090` 且
  secret 可以为空。在共享服务器上这是把控制面直接暴露给同主机的其他 UID，与本项目
  "mixed/controller 仅监听 `127.0.0.1` + per-user 认证"的既定边界直接冲突。
- **自动更新方式不可接受。** 审计发现其自动更新路径使用 `crontab -r` 覆盖式重建
  crontab。在共享服务器上这可能连带破坏同一 UID 的其他计划任务，属于越权修改用户
  已有状态。本项目坚持 fail-closed 和显式授权，不接受这一行为。
- **差异化能力会被稀释。** shared-server 多用户共存、per-process 代理
  （`exec`/`direct`）、workload-aware diagnostics 和 TUI 在该代码库中不存在，
  fork 之后需要重写而不是继承。
- **provenance 与维护成本。** fork 需要长期同步上游，且会让"本项目是原创实现"的
  表述失去依据。
- **core 更新路径缺少必要门禁。** 审计未发现 core 更新带有 checksum 校验与
  `mihomo -t` 门禁，直接 fork 会把这些缺口一并继承。

## 决策要点

1. **保留现有差异化能力。** shared-server 多用户共存、per-process 代理
   （`mihomoctl exec` / `mihomoctl direct`）、workload-aware diagnostics、
   fail-closed preflight、机器可读 `--json` 与 TUI 继续作为产品基线，不在 vNext
   中被重写或降级。

2. **不照搬对比项目的安全默认值。** 审计到其默认 `external-controller: 0.0.0.0:9090`
   且 secret 可为空；vNext 的默认是 mixed 与 controller 仅监听 `127.0.0.1`，
   per-user 认证，且凭据缺失即 fail closed。

3. **不移植覆盖式自动更新。** 审计到其使用 `crontab -r` 可能破坏同一 UID 的其他
   计划任务。vNext 的更新保持显式触发、可预览、可回滚，不接管用户的 crontab。

4. **端口：内核裁决，应用尽力协调。** 由内核对端口的分配结果作为裁决依据，应用层
   只做尽力协调：同 UID 操作锁、启动前门禁、冲突时 fail closed、绝不杀死他人进程。
   **不得宣称无 root 的强端口预约**——回环端口是全主机资源，非特权用户无法预留。

5. **Managed / Adopted 按资源授权。** binary、config、service、workload 四类资源
   各自独立标记 ownership，不使用单一 overall 标记。adopt 默认只读引用现有资源，
   不接管写权限；接管必须显式选择。

6. **配置与状态分层。** 区分 XDG config、data、cache、state 与 runtime（locks）。
   raw subscription、local policy、generated config 三者分离存放，不合并为单一文件。
   敏感内容即使位于 cache 或 state 也保持目录 `0700`、文件 `0600`。

7. **事务协议。** 生命周期变更统一为
   discover → plan → stage → verify → validate → commit → activate → acceptance → finalize。
   关键约束：先完成全部网络下载再停止旧代理；升级失败可回滚；**回滚失败必须显式报告**，
   不得静默降级。

8. **安全 envelope。** policy 层不得改写 listener、认证、controller、TUN 或透明代理
   设置，也不得增加额外监听。这是策略生成与生命周期管理之间的硬边界。

9. **WorkloadAdapter 抽象。** 提供 `GenericExec` 与 `Codex` 两个优先 adapter，
   其后是 OpenCode、Claude Code、VS Code Remote。adapter 负责启动前置条件、
   进程角色判定与恢复指引，不负责生成 Mihomo 策略。

10. **Evidence 模型。** 明确区分两个正交维度：**check 状态**
    （`PASS` / `FAIL` / `UNVERIFIED` / `SKIPPED`）与**证据等级**
    （`confirmed` / `inferred` / `unavailable`）。禁止把推断呈现为已验证；
    `UNVERIFIED` 是合法的终态，不是失败。

11. **JavaScript override 降级为可选 policy adapter。** 拆分为
    `policy/native` 与 `policy/flclash-js-compat` 两个 adapter，Node 仅在该功能
    需要时作为依赖存在，而不是控制层的启动前提。（v0.8 已实现等价入口
    `mihomoctl override --script` 与 `--flclash-compat`，Node `vm` 明确不是安全沙箱。）

12. **不做全量 Rust rewrite。** 采用增量迁移，且与配置迁移、workload 迁移分阶段进行。
    每个迁移门禁独立定义：现有命令行为、退出码与 JSON schema 保持不变，并有差分回归
    覆盖。是否继续推进下一阶段取决于门禁结果，而不是取决于语言偏好。

13. **明确的 non-goals。** 不做 FlClash / Clash Verge replacement，不做桌面 GUI，
    不做 TUN 或透明代理，不做通用 YAML editor，不做无 root 的强 UID 网络隔离；
    环境变量不是网络强制策略；readiness 通过不等于模型 E2E 成功。

## 后果

### 正面

- 保留已发布并有测试覆盖的能力，用户既有部署不受影响。
- 安全边界在架构层显式化，而不是依赖实现者的自觉。
- Mihoro 用户可以非破坏性接入，不需要重装或换工具。
- 端口、配置分层和证据语义被一次性定义，后续功能有稳定落点。
- 迁移风险被切分为多个可独立验证的门禁。

### 负面

- 短期内维护两套形态：v0.8 的扁平结构与 vNext 的目标结构并存。
- "按资源授权"比单一 ownership 标记更复杂，descriptor 与用户可见文案都要变长。
- 不接管订阅和 core 更新意味着用户在 vNext 落地前仍需使用既有流程或对比项目。
- 事务协议增加了状态机复杂度，失败路径的测试成本显著上升。
- 增量迁移意味着在相当长时间内 Bash 与新实现并存。

## 备选方案与未来重新评估条件

本决策在被下列任一条件满足时应当重新评估：

- Route A 的结构性问题已被证明可以在不重写核心路径的前提下收敛，且增量迁移的
  门禁成本明显高于预期。
- 对比项目的安全默认值与更新行为发生实质改变，使 Route B 的风险前提消失。
- 真实多 UID 集成测试显示 per-user 认证 + loopback 监听无法满足实际共享服务器需求，
  此时需要重新评估端口与隔离模型，而不是继续叠加应用层协调。
- 用户调研显示绝大多数目标场景只需要 lifecycle provisioning，不需要 workload 层，
  此时 WorkloadAdapter 的优先级应当下调。

重新评估时，本 ADR 应被标记为 `Superseded` 并链接到新的决策记录，而不是原地修改。

---

## English summary

ADR 0001 records the vNext foundation decision: **keep this repository (Route C)**.
mihomo-userctl stays the product and the repo, refactored internally, while absorbing
Mihoro's lifecycle-management *design* and supporting non-destructive adoption of an
existing Mihoro runtime. No permanent fork.

Rejected: **Route A** (keep stacking features onto the current flat structure — module
boundaries, port semantics and the safety envelope cannot be defined, and migration cost
only grows) and **Route B** (fork Mihoro — its default `external-controller: 0.0.0.0:9090`
with an optional secret, and its `crontab -r` overwrite-style auto-update, are unacceptable
in a shared-server threat model, and the differentiated capabilities do not exist there).

Key points: keep the existing differentiated capabilities; do not copy the audited
insecure defaults; no crontab takeover; ports are kernel-adjudicated with best-effort
coordination and no claim of rootless strong reservation; Managed/Adopted is authorized
**per resource**; config/state layering with separated raw subscription, local policy and
generated config; a fixed transaction protocol that downloads before stopping and reports
rollback failure explicitly; a policy safety envelope; WorkloadAdapter with Codex first;
an Evidence model separating check status from evidence grade; JavaScript overrides
demoted to an optional policy adapter so Node is not a prerequisite; no full Rust rewrite,
only gated incremental migration. Status is **Proposed** pending release confirmation.
The detailed target design is in [architecture-vnext.md](../architecture-vnext.md).