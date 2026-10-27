# 下次更新待办

本记录来自 MainServer 的使用反馈，所有事项均为**待处理**，目标为下一次更新，暂不指定版本号。这里只登记问题、证据、修复目标和验收要求；服务器临时处理、代码修复、升级和发布另行开展。

## 环境与现场状态

- mihomoctl 1.4.1，Mihomo v1.19.32，Linux amd64，user scope，process backend。
- 脚本来源：[FlClash-rules override.js](https://github.com/liuzq1103/FlClash-rules/blob/main/dist/override.js)。本次检查的脚本声明版本为 `1.1.0`；该链接指向可变的 main 分支，后续回归应固定脚本版本或摘要。
- `override --apply` 首次出现 `core-timeout: -t -d`，用户反馈第二次成功；随后 `restart` 再次出现同样的超时。
- 最后一次 `status` 显示 `runtime running=True`、控制器 `authenticated=True`。**覆写是否已被运行中的核心加载尚未验证**，不能仅凭磁盘保存成功或核心仍在运行判定已生效。
- 正式核心工作目录中已有 `geoip.metadb`（8,426,776 bytes）和 `cache.db`（65,536 bytes）。

## 待更新事项

| 编号 | 优先级 | 状态 | 问题与证据 | 后续修复目标 |
| --- | --- | --- | --- | --- |
| NEXT-001 | P1 | 待处理 | `override --apply` 和 `restart` 出现 `core-timeout: -t -d`。当前校验超时为 60 秒，每次使用全新空临时目录，没有复用正式工作目录中的地理数据库。校验子进程还会清除代理环境变量。 | 保留隔离校验，安全复用可信地理数据库；确认是否因重复下载导致超时，提供脱敏的校验阶段和耗时信息。 |
| NEXT-002 | P1 | 待处理 | `restart` 在停止旧核心前校验一次，随后调用 `start` 再校验一次；process 和 systemd 后端均有此调用路径。 | 消除重复校验，保留停止旧核心前的配置检查，并处理校验后配置发生变化的情况。 |
| NEXT-003 | P1 | 待处理 | FlClash-rules 脚本成功执行后新增 `__flclashRules` 状态标记，触发 `override-may-only-change-groups-rules-rule-providers`；`--flclash-compat` 也不会移除或接纳该标记。内嵌节点和 provider 两种模拟配置均已在内存中复现字段越界。 | 明确兼容此状态标记，继续拒绝修改监听、认证、TUN 等非策略字段；补充真实脚本回归用例。 |
| NEXT-004 | P2 | 待处理 | 脚本权限为 `664` 时只报 `controller-operation-unavailable: InstallError`；改为 `600` 后通过该项检查。桥接层隐藏了底层具体路径安全错误。 | 显示具体权限或路径检查原因及修复提示，保留现有属主、权限和禁止符号链接等安全要求。 |
| NEXT-005 | P2 | 待处理 | 当前 override 文档缺少完整使用教程；历史材料中的成功应用后保留备份等说明已不符合当前行为，容易被误用。 | 补充脚本权限、预览、应用、重启、兼容参数适用范围，以及成功应用后不保留历史备份的说明；明确历史文档的适用版本。 |
| NEXT-006 | P1 | 待处理 | 使用 provider 策略后，界面批量测速的多个节点均显示 `failed / unknown-node`。现场 `providers --json` 显示 HTTP 类型的 `subscription` 已加载 44 个节点，而 `nodes --json` 只显示 6 个内置动作。界面节点列表取自分组成员，单点及批量测速却先仅查询 `/proxies`，未合并 provider 节点；不在该表中的节点会在发起延迟请求前被拒绝。 | 将 provider 节点纳入节点发现、链路证据和测速目标解析；使用适用的 provider 节点测速接口，保留真实缺失、请求失败与连通性失败的区别。 |

### 证据边界

- 已从代码确认：临时校验目录不复用缓存、单次校验默认超时为 60 秒、重启存在重复校验。
- **重复下载地理数据库是待验证的服务器超时原因**。本次未取得实际超时校验进程的下载日志，不能将其写为已确认根因。
- 用户随后反馈 TUI 导入预览成功，但保存提示“操作未完成：core-timeout；请检查核心与私有配置”。代码确认订阅保存按钮实际执行保存并启动或重启：保存前校验一次，已有运行核心时重启路径再校验两次；provider 模式的预览本身也会执行一次核心校验。因此不能将预览概括为只做 YAML 解析，也不能从这条通用提示判断具体哪次校验超时或断言属于权限错误。该次 TUI 操作的实际输入模式、超时子进程和失败后的运行状态尚未取得。
- `__flclashRules` 的复现属于本地内存模拟，不等同于完整服务器应用或核心加载验收；移除标记后的模拟结果只涉及允许的策略字段。
- NEXT-006 的现场证据包括测速截图、`providers --json`、`nodes --json` 和 `latency "Ai+"` 的输出：provider 已加载 44 个节点，全局节点列表仅有 6 个内置动作；`Ai+` 当前出口访问 `https://www.gstatic.com/generate_204` 的延迟为 554 ms。结合代码中的全局表前置检查，已确认存在 provider 节点发现与测速入口的兼容缺口；不能将截图中的 `unknown-node` 视为节点连通性失败。尚未逐个测试 44 个节点，也未验证 ChatGPT 等业务可用性。
- Mihomo 上游提供独立的 [provider 节点与健康检查路由](https://github.com/MetaCubeX/mihomo/blob/Meta/hub/route/provider.go)，NEXT-006 后续实现应核对项目固定核心版本。
- 未记录订阅地址、节点密码、控制器密钥或完整配置；后续诊断和回归证据也应遵循此要求。

## 后续修复验收要求

- NEXT-001：已有可信地理数据库且配置所需资源齐全时，在断网环境完成校验；正式工作目录内容不被校验修改。缺少必要缓存且无法下载时，应明确失败并给出脱敏诊断。覆盖不可信文件、符号链接和 user/system 身份边界。补充 TUI 预览成功、保存或激活阶段超时的用例，显示实际失败阶段和恢复后的运行状态，避免统一提示误导为权限问题。
- NEXT-002：process 和 systemd 后端的重启不重复校验同一配置；校验失败发生在停止旧核心之前。校验后配置变化时，不得将旧校验结果用于启动未经校验的新配置。
- NEXT-003：固定真实脚本版本或摘要，覆盖内嵌节点、provider 和兼容模式；接纳状态标记不会放宽其他非策略字段的限制，候选配置仍须通过核心校验。
- NEXT-004：覆盖 `664` 脚本、错误属主、不安全父目录和符号链接；错误应解释具体原因，`600` 且路径可信的脚本能通过权限检查，不泄露文件内容或凭据。
- NEXT-005：按教程完成预览、应用和重启；明确区分保存成功、待重启及运行配置已生效，并核对当前备份行为。中英文文档保持一致。
- NEXT-006：覆盖只存在于 provider、同时存在于全局表、provider 刷新后消失及真正未知的节点；单点和批量测速均能解析正确目标。覆盖不同 provider 的同名节点、特殊字符名称及不支持的接口；界面链路和缺失引用提示不能把已加载的 provider 节点判为缺失，真实失败仍应正确呈现。

## 定位入口

- 校验隔离、超时和环境清理：[核心 runner](../mihomoctl/lifecycle/runner.py)；重复校验：[process 后端](../mihomoctl/lifecycle/process.py)、[systemd 后端](../mihomoctl/lifecycle/systemd.py)。
- 脚本字段白名单及兼容处理：[策略生成](../mihomoctl/controller/controller_policy.py)；权限错误：[路径检查](../mihomoctl/controller/files.py)、[控制器桥接](../mihomoctl/bridge.py)。
- provider 节点发现、链路和测速：[控制器服务](../mihomoctl/controller/controller_service.py)、[链路证据](../mihomoctl/controller/controller_health.py)；节点列表来源：[Textual 界面](../mihomoctl/controller/controller_textual.py)。CLI 单点测速也应同步核对：[控制器入口](../mihomoctl/controller/controller.py)。
- 当前使用文档：[CLI 参考](zh-CN/reference/cli.md)、[排障](zh-CN/troubleshooting.md)；旧教程仅供历史核对：[归档覆写教程](archive/pre-v1.1/docs/zh-CN/tui-overrides.md)。

## 1.4.2 本仓库实施记录（审核与发布尚未完成）

已实现多行 YAML、可信资源隔离校验、进程内校验复用、provider 来源测速、权限原因、保存恢复状态及脚本元数据/策略片段支持。批量测速增加逐行失败原因与统计；中断恢复对已运行核心重新检查认证，未确认时保留日志。新增单元回归和断网真实核心验收已有通过证据；审核、完整 CI 与发布仍在执行，以上原始待办暂不标记已修复。MiniMax 额度耗尽后，用户明确授权以 GPT 与 GLM 两方独立及交叉审核均通过放行；既有 MiniMax 意见仍保留，不伪记最新通过。现场根因和实际订阅的业务端到端可用性仍未确认，未操作生产服务器。
