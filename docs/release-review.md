# mihomoctl V1.0.0 独立发布审查

审查员：用户指定的 F 独立 Codex 审查员。初审落盘日期：2026-10-12（Asia/Shanghai）。

**最新结论（2026-10-12 12:30 +08:00）：代码审查允许推送所审 EnvironmentFile renderer、安装阶段安全诊断及 launcher 前置 trust 检查，运行下一轮实际 CI；定向 domain/installation 108 tests，OK，1 privileged skip，真实离线 parser 对照和三阶段恢复注入通过，未发现新增代码阻断。36bc 两平台已实际通过两 UID/process、system service/crash、完整 TUN 恢复与 foreign 拒绝；test20 环境继承和 test60 系统安装仍未通过。正式 Release 仍为 BLOCKED / 同提交完整真实 CI pending，不构成正式发布批准。以下保留初审、复现和修复记录，最新复审结论见文末。**

## 审查基线与边界

冻结契约为 `docs/architecture-v1.md`、`docs/adr/0002-v1-generic-runtime.md`。已读取两份契约，并审查工作区中的 V1 实现及定向修复。最近读取的 HEAD 为 `6ccc94d242796af66b4556ab8e46fa1b2d1b6a26`；被审对象包含尚未提交且持续修复的工作区内容，不能将下述结果等同于该提交或最终发布提交的验证结果。

覆盖范围包括 mihomoctl 包、保留 Controller/TUI/scripts 的兼容与发行边界、安装/发行/CI、身份与权限、作用域锁、文件和运行时事务、root 降权与代码信任、TUN、listener/profile/auth/env/脱敏、迁移 hook 精确删除及 rollback journal、coreinstall 供应链、wheel 白名单及安装回滚。静态检查与测试通过均不替代未执行的真实系统验收。

F 未修改业务代码或测试，未提交，唯一工作区写入为本报告。未操作本机系统服务或全局网络；故障注入中的 systemctl、TUN、socket 等相关动作使用替身。Linux 测试经 `scripts/v1_ci.py` 在私有 Linux 副本运行，避免 `/mnt/d` 权限误报。私有学习笔记内容未读取、输出、删除、移动或提交。

## 独立执行证据

环境为 WSL Ubuntu 22.04、Python 3.10.4、UID 1000，PID 1 为 init，**不是 systemd**。真实 core 使用既有 Mihomo 1.19.32 测试二进制。

| 检查 | F 独立结果 | 证据边界 |
| --- | --- | --- |
| 初次完整 unit | 285 tests，OK，18 skipped | 私有 Linux 副本；非最终提交 |
| 定向修复后的 domain | 15 tests，OK，0 skipped | 包括 uninstall、TUN commit 恢复、adapter 转义等；早于部分后续补丁 |
| 后续完整 unit | 291 tests，OK，18 skipped，65.138s | 取样时修复仍在继续；不能视为最新全部修复后的最终结果 |
| 初次 real-core | 59 tests，OK，0 skipped，71.671s | 真实 core，无 systemd PID 1 |
| 增加 coreinstall commit 失败注入后的 real-core | 59 tests，OK，0 skipped，77.864s | 独立重跑通过；验证原配置恢复、候选 core 移除及旧 core 可用 |
| integration 锁争用定向复测 | PASS | 持有真实作用域锁时，reload 次数为 0，未写入集成产物 |

执行入口：

```text
/tmp/mihomoctl-v1-test-env/bin/python scripts/v1_ci.py --unit
/tmp/mihomoctl-v1-test-env/bin/python scripts/v1_ci.py --unit --pattern test_v1_domain.py
/tmp/mihomoctl-v1-test-env/bin/python scripts/v1_ci.py --real-core --core /tmp/mihomoctl-v1-core-eqtki4h4/mihomo
```

另有实施方提供的 UX 94 OK/0 skip、安装 64 OK/1 privileged skip、unit 285 OK/18 skip 等结果；这些是外部报告，未冒充 F 独立执行结果。真实 core 测试通过不意味着真实 systemd、两 UID 或 TUN 已验收。

## 按严重度排列的问题与复审状态

下列行号为复现或最近读取时的位置；工作区修复会使行号移动。所有问题均已通过审查活动传递给实施方。表中“已验证修复”只适用于注明的快照与测试，仍须纳入最终冻结版本回归。

| 编号 | 严重度 | 文件与位置 | 独立证据及影响 | 初审状态 |
| --- | --- | --- | --- | --- |
| F1 | P1 | `mihomoctl/lifecycle/process.py:118-129`（原复现位置） | 子进程通过身份和监听检查后，状态写入抛 OSError；cleanup 调用 0、terminate 调用 0、state 不存在。可能留下无法通过状态文件管理的运行进程；原异常处理也未覆盖 KeyboardInterrupt。 | 已转修复；最新代码出现变更，尚未独立复测该补丁，pending |
| F2 | P1 | `mihomoctl/lifecycle/systemd.py:249-269`（原复现位置）；`mihomoctl/cli.py:592` | 同名外来 unit 存在时，start 路径实际发起 start，监听失败后又 stop；替身记录 show/start/show/stop，外来 unit 文件保持原样。文件未改动不能消除运行时干预，违反仅管理自有服务的契约。 | 已转修复；最近 start 位置移至约 270，最新所有权补丁 pending 复测 |
| F3 | P1 | `mihomoctl/cli.py:623`；`mihomoctl/lifecycle/systemd.py:191` | 原卸载先删除 unit 再 reload，reload 失败后 unit 未恢复，backend 变更不在同一事务。原复现 unit_restored=false。 | 已审定向修复：自有文件删除和 user backend 变更纳入同一事务，失败后恢复并 reload；domain 覆盖 reload/commit 失败通过。最终版本待回归 |
| F4 | P1 | `mihomoctl/lifecycle/tun.py:118-207` | 原 commit 失败只恢复文件，restart_states=[true]、恢复 restart 次数 0，运行时仍可能处于新 TUN 状态。 | 已审修复：commit 纳入恢复 try，失败 rollback 后 reload/restart 旧运行时并核验身份；domain 回归通过。真实 TUN 未执行 |
| F5 | P2 | `mihomoctl/integration/systemd_adapter.py:91` | 原 reload 失败只恢复文件、不二次 reload；首轮修复又在拿锁失败时 reload。独立锁争用复现 reload=1、artifacts_written=false。 | 最新锁内显式 Transaction 修复后独立复测 reload=0、artifacts_written=false；此前 domain 覆盖 install/remove/commit 回滚后二次 reload。最终完整回归 pending |
| F6 | P2 | `mihomoctl/integration/__init__.py:59`；`mihomoctl/integration/exporters.py:123` | 原自定义模板 raw replacement 缺格式转义，未知 `{unknown9}` 被保留；独立验证 JSON scalar 未正确转义。 | 已审按 kind 转义、拒绝未知占位符/控制字符/错误引号上下文的修复；domain roundtrip 和拒绝用例通过 |
| F7 | P2 | `mihomoctl/lifecycle/tun.py:63`、`:130` | 原 enabled no-change 快路径未检查设备、receipt ifindex、runtime；定向复现三个检查次数均为 0，仍返回 changed=false。 | 已审 `_verify_owned` 与 health 检查，替换 ifindex 拒绝用例通过；真实设备身份场景 pending |
| F8 | P2 | `mihomoctl/migrate.py:156-180` | 源配置认证为 user:pass，两个代理 env 都为 user:wrong 时迁移仍提交；manager_created=true，首次 resolve 报 profile-credentials-mismatch。只比较 HTTP/SOCKS 之间凭证，未与 listener 认证一致性核验。 | 已转修复；最新补丁与独立回归 pending |
| F9 | P2 | `mihomoctl/health.py:144` | egress Basic auth 直接使用 urlsplit 的 percent-encoded username/password；含编码字符的合法凭证产生错误 wire credentials。独立替身探测 wire_credentials_correct=false、probe_status=FAIL。 | 已转修复；unquote 补丁与独立回归 pending |

以上故障注入在临时副本和临时文件中执行，真实 core 用例另列；没有将替身结果宣称为真实 systemd/TUN 结果。

## 其余审查证据与限制

- coreinstall 的 `_publish_and_activate` 在 `mihomoctl/coreinstall.py:304` 附近将 `tx.commit()` 放在恢复 try 内；catch 同时恢复文件和此前运行的 core。`tests/test_v1_runtime_real.py:303` 附近的真实 core commit 注入回归已由 F 独立执行通过。
- 已检查迁移 rollback 的可信 journal、内容漂移和安全备份成员验证、事务 commit 写失败处理，以及未 init 的子命令 help 路径。后续发现的迁移 auth 漂移见 F8，不能以 journal 修复替代该问题修复。
- 已检查安装器的 archive 路径约束、wheel RECORD/载荷约束、代码信任、generation 切换与恢复路径；本轮未形成新的已证实安装器缺陷。相关静态审查不能替代最终发行包安装与回滚。
- `scripts/build_release.py` 使用精确白名单、源码扫描、wheel runtime 载荷验证、校验和及 receipt；`release-manifest.json:67` 列出本报告，此前唯一缺失项为本文件。domain 测试文件后已加入清单（约第 196 行）。本报告落盘解除“报告文件缺失”的构建阻断，不代表完整构建已通过。
- 已通过的 wheel 测试包含最小 runtime fixture 清单，不能据此宣称完整源码白名单 archive 构建通过。F 尚未独立完成最终完整源码包/wheel 构建、安装、回滚与产物 digest 验证。
- 已审 `.github/workflows/test.yml`、`scripts/verify_release.py` 的 Ubuntu 22.04/24.04、Python 3.10/3.12、固定 core digest、独立 real-core 入口、privileged systemd/两 UID/TUN 证据门禁，以及 commit/dirty/mandatory skipped/digest 约束。配置存在不等于 CI 已执行成功；尚无最终提交对应的真实 CI 证据可批准。

## 正式发布阻断清单

| 门禁 | 状态 | 解除所需证据 |
| --- | --- | --- |
| F1/F2/F8/F9 最新修复 | PENDING / BLOCKED | 独立读取最新补丁，针对原故障复现回归，并确认最终冻结版本包含修复 |
| 所有定向修复后冻结回归 | PENDING / BLOCKED | 最终明确快照或提交上的 unit、domain、real-core；独立 real-core 入口禁止 skip |
| Ubuntu 22.04 真实 user/system systemd | NOT RUN / BLOCKED | 真实 systemd PID 1 上 mandatory 验收，无相关 skip |
| Ubuntu 24.04 真实 user/system systemd | NOT RUN / BLOCKED | 对应真实 CI 验收及环境、提交证据 |
| 两个真实 UID 隔离与越权拒绝 | NOT RUN / BLOCKED | 真实两 UID 场景，含身份/权限/锁/运行时归属检查 |
| 隔离环境真实 TUN | NOT RUN / BLOCKED | 真实 enable/disable、设备身份、路由、失败恢复；补充受管 restart/crash 后 receipt 与 ifindex 一致性场景 |
| 完整源码包与 wheel | PENDING / BLOCKED | 最终精确清单构建、源码扫描、wheel 载荷、安装与回滚、SHA256/receipt 一致性 |
| 最终提交与发行身份 | PENDING / BLOCKED | clean 最终提交、Ubuntu 两套真实 CI evidence、产物同源校验以及 tag/Release 对应关系 |

不得将 WSL 无 systemd PID 1 的通过结果、mock 故障注入结果、privileged skip 或实施方口头报告填作上述真实验收的 PASS。本轮只完成真实初审和报告落盘；待最新修复及真实 CI 证据到齐后更新复审结论。

## ROOT FREEZE 后独立复审（2026-10-12 10:48 +08:00）

本节更新前文的初审状态。业务 freeze 后仅做读取、私有副本测试及本报告更新，未修改业务代码或测试。HEAD 仍为上述旧提交，审查对象是冻结工作区快照；随后实施方允许修复本节新增阻断及 YAML 诊断泄露，故测试结果不能冒充这些后续补丁的最终结果。

**当前代码审查结论：暂不放行推送 CI，等待 F10/F11/F12 定向修复回归。正式 Release 仍为 BLOCKED，真实 Ubuntu 22.04/24.04、systemd、两 UID、TUN 及同提交发行证据未完成。**

### 冻结快照独立结果

- F 独立完整 unit：**309 tests，OK，18 skipped，62.064s**。使用前述私有副本入口，只执行一次；包含当时 domain 32 项及 tooling 门禁测试。18 skip 不可填作 privileged 验收通过。
- F 独立 real-core：**59 tests，OK，0 skipped，77.487s**。只执行一次，包括真实 coreinstall commit 失败恢复旧实例的回归。
- F1：代码 `lifecycle/process.py:38-58,126-145,233-245` 已验证状态的 actor UID、private 权限、dict/schema、exe/config 一致性；OSError/KeyboardInterrupt 进入 BaseException 清理，仅停止身份仍匹配的子进程。unit 回归验证异常后 stop 一次、无未经验证的 terminate/kill、状态清理，以及身份漂移拒杀并报告独立恢复失败。
- F2：`lifecycle/systemd.py:300-337,344-423` 已拒绝磁盘 foreign unit、不同 loaded fragment、未知 loaded drop-in、活动 PID 身份漂移；unit 原复现回归通过。此项原缺陷修复，但新增“同路径缓存旧定义”见 F10，不能据此宣称 loaded definitions 边界完整。
- F3/F5：uninstall 与 integration 的 rollback/commit/reload 恢复在 operation lock 内，unit 验证文件/backend 恢复及锁争用时不 reload。service install 的相同边界遗漏另列 F12。
- F4/F7：`lifecycle/tun.py:63-141,170-180,186-276` 已采用强内核 FD 证据，原 commit 恢复、同名外来设备、persistent device、无 FD、跨 namespace、ifindex 漂移/只读 status 用例通过。真实 TUN 仍未在 F 的 WSL 中执行。
- F6：custom adapter 按目标格式转义，未知 placeholder、控制字符、错误引号上下文拒绝；roundtrip 原复现回归通过。
- F8：`migrate.py:163-170` 在发布任何文件前核验所选 legacy/listener 真实认证 pair，认证漂移拒绝用例通过；默认迁移只清理有历史 receipt 的 loader，精确字节 rollback 用例通过。
- F9：`health.py:145` 已对 URL username/password 做 unquote 再生成 Basic auth；percent-encoded 凭证原复现回归通过。
- process state 新边界：不安全文件/父目录、symlink、损坏 JSON、跨 UID、伪造 live PID start_time 均保留 receipt 并拒绝发送信号，含真实临时无关子进程存活验证。

### 新增阻断（已在 timeline 完整通知实施方）

| 编号 | 严重度 | 文件与位置 | 独立复现与影响 | 状态 |
| --- | --- | --- | --- | --- |
| F10 | P1 | `mihomoctl/lifecycle/systemd.py:292-338` | 同一 FragmentPath 的磁盘 unit 为精确 renderer 内容，但 manager 属性为 NeedDaemonReload=yes、旧 ExecStart=/foreign-old-definition，`_require_owned_unit()` 仍接受。属性查询未包含 NeedDaemonReload；只检查 fragment/drop-in 路径不能证明缓存定义等于磁盘。inactive start 可先执行旧定义再在运行时身份检查失败。 | 已交实施方；定向补丁及回归 pending |
| F11 | P2 | `mihomoctl/config.py:132,165,196`；`mihomoctl/endpoints.py:174-175` | 虚构含 token URL 的未知 manager key 原样进入异常。独立结果 sensitive_key_echoed=true；nested unknown fields 有同类拼接。未知 key 来自不可信输入，不是安全 schema 字段名。 | 已交实施方；schema/key/value 诊断不 echo 补丁及回归 pending |
| F12 | P2 | `mihomoctl/cli.py:612-621` | 持有真实 operation_lock 后调用 service install，得到 operation-in-progress，但外层恢复 handler 仍 daemon-reload 一次。独立结果 reload_calls_without_lock=1。可能加载另一事务尚未完成的定义；原 F5 的 integration 修复未覆盖此路径。 | 已完整补报实施方；定向修复及回归 pending |

F10 使用替身 manager 属性，F12 使用真实 flock 和替身 systemctl，均未操作主机服务。F11 使用专门虚构的敏感 key，只输出“是否泄露”的布尔证据，没有输出真实凭证。

另复核了 root 指出的 duplicate YAML key 泄露：原 `yamlutil.py:31` repr(key) 独立结果 sensitive_key_echoed=true。最近读取已改为仅 line/column（约第 32 行），但该补丁晚于上述完整测试快照，等待与 F11 一并定向复验。解析/未知键/引用值的所有公开诊断均应避免回显不可信数据；不能只修 duplicate 分支。

### TUN 与 namespace 证据模型审查

静态模型符合“不凭同名收养”的方向：必须为精确受管 unit，loaded fragment/drop-in 经过检查；PID/UID/start_time/exe/config 反复核验；core PID 与当前 CLI 位于相同 net namespace；设备非 persistent；该精确 PID 的 `/dev/net/tun` FD 及 fdinfo 的 iff 必须匹配设备名，FD 检查前后再核验进程身份。缺任何证据均拒绝。F10 的缓存定义问题仍须修复，才能关闭 loaded-definition 边界。

显式 restart 后可在锁内刷新 receipt；只读 tun status 不写 receipt；crash 后 ifindex/runtime receipt 漂移只在上述强证据成立时被接受，disable 也重新检查强归属。domain 的只读字节不变、foreign/persistent/无 FD 拒绝用例通过，不能替代真实内核设备验收。

namespace 只接受 system scope 固定 `60-mihomoctl-namespace.conf`、精确 marker、单一 `[Service]` 和唯一 `NetworkNamespacePath=/run/netns/<safe-name>`；文件/祖先/nsentry 必须 root trust，loaded 属性和 CLI/core PID namespace inode 一致，其他 override 拒绝。未发现测试专用放行分支。架构文档约第 166-173 行已说明管理员部署与显式 namespace 管理边界。

已读 privileged test40 的正式 renderer、受管 restart、SIGKILL 自动恢复、status/tun status/disable 和路由恢复断言；这是待执行的正式验收用例，**不是已执行 PASS**。

### 产物与发布 gate 增量

已读取实施方提供的 `/tmp/mihomoctl-v1-artifact-smoke-review-1.json`：三个完整格式 tar.gz/zip/wheel 的 cases 为 PASS，success=true、publishable_acceptance=false。它未包含完整最终 commit/tests/skipped 证据，不能满足正式发布 gate。对应 `/tmp/mihomoctl-v1-artifacts-review-1/build-receipt.json` 明确 source=worktree、publishable=false，记录三类产物 SHA256；这些都是开发构建证据，F 未冒充独立重跑其安装流程。

已静态复核新增 `scripts/verify_release.py:56-99`：两个 Ubuntu 都需 artifact-install.json，核验 commit/publishable_acceptance/success/三类格式/skipped/inventory/digest；所选源码 tar/zip 必须与两个安装报告一致，所选完整产物集合（含 wheel）必须至少在一套报告实际安装过。tooling 通过用例与 wrong commit、缺报告、非 publishable、资产漂移拒绝用例包含在上述 unit。

已读正在正式化的 `scripts/verify_artifact_install.py`：仅临时 HOME/XDG、离线安装/更新/generation 切换、原来源路径失效后的独立 recovery、卸载/恢复、保护已有文件，并输出明确开发/正式证据区别。CI 已接入安装报告上传。该工具仍待实施方完成通知和最终证据，F 未提前将未冻结工具记作正式验收完成。

后续只需对 F10/F11/F12 与 YAML 输出补丁作定向复验，并核验安装工具完成版本；无新的失败或范围变化时不重复全量。正式发布门禁继续保持前述 BLOCKED。

## 再冻结补丁定向复验（2026-10-12 11:05 +08:00）

F 只执行定向 domain，没有再次执行完整 unit 或 real-core：**37 tests，OK，0 skipped，0.655s**。独立入口为 `scripts/v1_ci.py --unit --pattern test_v1_domain.py --report /tmp/mihomoctl-v1-f-independent-targeted.json`，仍在私有 Linux 副本运行。

同时独立重跑原故障注入和真实 CLI 输出检查，结果如下：

| 项目 | 独立复验 | 当前状态 |
| --- | --- | --- |
| F10 缓存 definition | NeedDaemonReload=yes 或 missing 时拒绝；明确 no 时通过。`systemd.py:294,310-312` 查询并 fail closed；domain 验证 start/stop/restart 在缺失/空/yes 情况均零 lifecycle 调用。 | CLOSED，限已复审冻结补丁 |
| F12 service install 锁争用 | 真实 operation lock 持有期间，返回 operation-in-progress；systemctl_calls=0，manager_created=false，unit_created=false。`cli.py:614` 复用锁内 unit_transaction。 | CLOSED |
| duplicate YAML key | 虚构敏感 key 不再回显，line 2 column 1 保留；真实 CLI JSON/text 回归通过。 | CLOSED |
| F11 普通未知 key/type/reference | 顶层和已覆盖的 nested unknown key、listener type/reference 均不再回显虚构敏感输入。 | 部分修复；下述名称路径仍 OPEN / P2 |

**剩余确定阻断：F11 的非法 profile/binding 名称仍被诊断回显。** `mihomoctl/config.py:129,132,162,165` 在 `_require_name` 之前把原始 name 插入“must be a mapping / has unknown fields”。`parse_manager()` 中 `manager.profiles[_require_name(...)] = _parse_profile(...)`（binding 同类）先执行赋值右侧，不能靠左侧下标校验保护 RHS 的错误输出。

F 使用虚构含 token URL 作为 profile/binding key，调用真实 CLI `profile list --json`，独立结果：

```json
{"case":"invalid_profile_name_mapping","exit":2,"sensitive_echoed":true}
{"case":"invalid_profile_name_unknownfield","exit":2,"sensitive_echoed":true}
{"case":"invalid_binding_name_mapping","exit":2,"sensitive_echoed":true}
```

测试仅输出泄露布尔值，没有公开真实秘密。这些用例不在当时 domain37 覆盖集合中，因此 37 PASS 不足以关闭 F11。应在任何包含名称的诊断前校验名称，或不给不可信名称回显。**代码审查仍暂不放行推送 CI；只剩本项待修复及定向复验，无需重跑全量。正式 Release 仍 BLOCKED。**

另已静态核验两个 backend 的 restart 先确认身份/归属并在隔离 staging 验证候选，再 stop/start；domain 中 invalid semantic candidate 验证两个 backend 均未调用 stop/start。root 报告最新真实 core **59 OK/0 skip，80.814s**，`/tmp/mihomoctl-v1-real-final-f12.json`，新增实际原 PID 保持运行断言；F 未重复该真实测试，结果来源明确为 root。

正式化安装工具的实施方报告 `/tmp/mihomoctl-v1-artifact-install-review-1.json` 已读取：tests=3、skipped=0、errors=0、success=true，tar.gz/zip/wheel 均包含 update/generation switch、原来源路径失效后的 recovery、uninstall/restore 和保护文件检查；三类 digest 与此前 dev build receipt 一致。source=worktree、source_dirty=true、publishable_acceptance=false，因此仍仅为开发证据。工具已列入 source inventory，未纳入 wheel runtime；完成版 shape 与 gate 对应。root 另报告漏 `--worktree` 拒绝、secret scan/docs 通过，F 不冒充独立执行。

## F11 最终定向关闭与 CI 放行（2026-10-12 11:07 +08:00）

已读取再次冻结补丁：`mihomoctl/config.py:127,161` 在 `_parse_profile`、`_parse_binding` 函数入口立即以安全常量 context 调用 `_require_name`，早于 mapping/unknown-field 诊断；后续构造仅用已验证名称。因此不再依赖赋值左侧的迟执行校验。

F 在私有 Linux 副本独立重跑真实 CLI `profile list`：含虚构 token URL 的非法 profile/binding 名称，分别配 False 和 unknown-field mapping，共四种输入；每种分别执行 JSON、text 输出，合计 **8/8 PASS**。全部退出 2、稳定 config-invalid、敏感完整名称及 token 均未出现在 stdout/stderr。此次只复验本项原 CLI 输入，未重复完整 unit、domain 或 real-core。

**F11 CLOSED。F1–F12 与 duplicate 诊断的已证实阻断均已关闭，F 的代码审查允许将所审冻结工作区提交并推送发布分支运行实际 CI。** 此批准仅用于推分支验收，不是 tag/Release 正式发布批准，也不能将旧 HEAD 标记为已覆盖当前未提交内容。

正式 Release 继续 **BLOCKED / PENDING**：必须取得最终 clean 提交对应的 Ubuntu 22.04/24.04 真实 user/system systemd、两个真实 UID、隔离真实 TUN（含 restart/SIGKILL 恢复、强归属与安全 disable）、mandatory 无 skip、完整三类产物离线安装/回滚及 digest/receipt 一致性证据，并通过正式 release gate。此前 worktree/dev 产物与 WSL 非 systemd 测试不能替代这些门禁。

## 首轮 CI 后增量独立复审（2026-10-12 11:16 +08:00）

基线 HEAD 为 `bcfa5b30f07d8ec636b568df30f6b729679ad04f`，本次审查其上的未提交增量：`cli.py`、`app.py`、domain 测试及 workflow。root 报告首轮两个 Ubuntu 各 314 unit 只有 1 error：setup-python 的 `/opt` 祖先可被其他账户写入，安装器正确拒绝解释器；F 未独立下载 CI 日志，不将此转述冒充亲自执行的 CI 结果。

root 额外发现 public integration install 绕过 adapter 恢复事务，以及部分命令在锁外捕获旧 manager/binding 的边界遗漏。这也修正前文 F5 关闭的覆盖范围：此前已测 adapter API，但不足以证明 public CLI 的缓存恢复。现已纳入独立 CLI 定向验证。

F 只执行一次增量 domain：**39 tests，OK，0 skipped，0.710s**，报告 `/tmp/mihomoctl-v1-f-ci-incremental-domain.json`。没有重跑完整 unit 或 real-core。另在私有 Linux 副本使用真实 flock、替身 systemctl/backend 的独立注入检查如下：

| 增量 | 代码与证据 | 复审结论 |
| --- | --- | --- |
| Public integration install 恢复 | `cli.py:734-741` 改走 adapter `_transaction`，锁内重新读取 binding 并构建 env。独立注入使初始和锁内 binding target/profile 不同，证实使用锁内新值；首次 reload 抛错后共 reload 2 次，三个旧产物 bytes 全部恢复。 | CLOSED |
| Public integration 锁争用 | 持有真实 operation_lock 后调用 CLI install，拒绝并 reload=0；未修改原产物。domain 同时覆盖该公开入口。 | CLOSED |
| Profile set-default 旧 manager 覆盖 | `cli.py:400-403` 锁内重新 resolve。独立让锁外返回旧 core、锁内返回新 core/新 binding，发布后的 manager 保留新 core 和 binding，只更新 default。 | CLOSED |
| Service install/uninstall 旧 manager/active 状态 | `cli.py:610-617,639-647` 锁内重新 resolve、重新检查运行状态/TUN，并写 fresh manager。独立真实锁测试确认两个路径保留新 core/binding；静态核验 active 检查在锁内再次执行。 | CLOSED |
| Application.lifecycle 旧身份 | `app.py:146-148` 在 operation lock 内 resolve 和构造 backend。独立在 resolve 与 backend.start 内尝试竞争真实 flock，均确认锁被持有。 | CLOSED |
| CI interpreter trust | workflow 使用 `/usr/bin/python3 -m venv /tmp/mihomoctl-v1-ci-python`，激活并通过 GITHUB_PATH 供后续步骤使用，显式断言矩阵 Python 3.10/3.12。`installation.py:832-884` 的 interpreter/venv owner、writability、祖先与 symlink target 信任检查未被弱化。 | 静态审查通过；实际 Ubuntu CI 待运行 |

`git diff --check` 对上述增量通过。所有独立故障/竞争测试均使用临时 HOME/XDG 与私有副本，没有操作本机系统服务或全局网络，没有业务代码/测试写入和提交。

**本次增量未发现新增确定阻断，允许 root 提交并推送这些修复到发布分支，运行下一轮真实 CI。** 此批准仅表示代码审查可进入 CI，不能继承首轮失败提交的验收身份。正式 Release 仍 BLOCKED；Ubuntu 22.04/24.04 的完整 unit、real-core、真实 systemd/两 UID/TUN、产物安装报告及最终同提交 digest/release gate 必须重新取得全绿证据。

## df67aed CI 后三文件定向复审（2026-10-12 11:33 +08:00）

基线 HEAD 为 `df67aed1306558d8553ee2bd6a91c51c90d99727`，本次只复审冻结增量 `scripts/build_release.py`、`tests/test_v1_tooling.py`、`tests/test_textual.py`，并更新本报告。未改业务代码、测试或提交；未重跑业务全量。

已独立读取下载的 `.tmp-v1-ci-df67-evidence` JSON 和两份 job 日志，确认 run `38199392249` 的失败边界：

| 平台 | 已下载真实 CI 证据 | 限制 |
| --- | --- | --- |
| Ubuntu 24.04 / Python 3.12.3 | clean df67aed，unit 316 OK/15 skip（43.626s），real-core 59 OK/0 skip（81.399s）；后续 builder 在 staging runtime import 报 runtime-untrusted | 构建未通过，完整产物安装/privileged 未取得成功报告，不得批准 Release |
| Ubuntu 22.04 / Python 3.10.12 | clean df67aed，unit 316，1 error/15 skip（37.352s）；`test_policy_selector_defaults_to_auto_and_keeps_explicit_nodes` 读取尚未发布的 app.preview，TypeError: NoneType | unit 失败，不能继承为新提交的全绿证据 |

F 独立通过私有 Linux 副本执行：

```text
scripts/v1_ci.py --unit --pattern test_v1_tooling.py --pattern test_textual.py --report /tmp/mihomoctl-v1-f-builder-textual-targeted.json
```

结果为 **32 tests，OK，0 skipped，35.084s**，其中 tooling 17、Textual 15。报告明确基线 df67aed、source_dirty=true、Ubuntu 22.04/Python 3.10.4；这是 F 的定向工作区验证，不是新提交真实 CI。

### 构建权限修复

- `scripts/build_release.py:24-31,66` 用 ContextDecorator 在 main 全程设置 umask 077，并在 finally 恢复；子构建进程继承该 mask。
- `:92,106` 仅规范复制或 git archive 解出的临时 staging 文件为 0600/0700，不修改原 source tree。打包产物成员仍按既有 0644/0755 规则输出；清单、扫描、wheel exact runtime、receipt 的正式/开发区别未放宽。`mihomoctl` 生产模块没有本轮 diff。
- 新 `tests/test_v1_tooling.py:141` 真实 Git fixture 设置 tar.umask=0002，先证实归档含 group/other writable mode，再在 caller umask=002 下分别完整执行 git-commit/worktree 构建。两个模式均通过清单、secret scan、wheel payload、receipt/commit/publishable 检查，源文件 SHA256 和 mode 保持原样。
- F 额外独立检查 context 的正常返回、OSError、KeyboardInterrupt、装饰 main 的 `--help` SystemExit：caller mask 均恢复为 002；子进程创建目录为 0700、文件为 0600。没有通过削弱生产 runtime trust 解决 CI 失败。

### Textual 等待修复

`tests/test_textual.py:198,208,216` 的三处等待从“worker 已记录调用”改为“app.preview 已在 UI 发布”。保留第一次完整 calls 列表、第二/三次次数与参数断言，新增 preview policy 和 selector 可操作性检查；切换 policy/kind 后仍断言旧 preview 已失效。修复同步的是测试观察边界，没有改生产 UI、跳过测试或删除原行为断言。全部 15 项 Pilot 测试在 F 独立运行中通过。

上述三文件 `git diff --check` 通过。**本次未发现新增确定阻断，允许提交并推送这三文件及审查报告到发布分支，运行下一轮 CI。** 正式 Release 仍 BLOCKED / PENDING：必须获得包含这些修复的同一最终 clean 提交对应的两 Ubuntu 完整 CI、真实 systemd/两 UID/TUN、完整产物安装/回滚及正式 release gate 成功证据；df67aed 的部分通过不能替代。

## d2e42b5 CI 后五文件定向复审（2026-10-12 12:11 +08:00）

基线 HEAD 为 `d2e42b56b0412efcc0e734214365785423c2b090`。本次只审冻结增量 `mihomoctl/installation.py`、`tests/test_v1_installation.py`、`mihomoctl/scope.py`、`tests/test_v1_domain.py`、`tests/test_v1_acceptance.py`，唯一工作区写入为本报告，未提交。

已独立读取下载的 `.tmp-v1-ci-d2e4-evidence` 和两个 job 日志，确认 run `38200351634`：

| 平台 | 已有同提交真实证据 | 尚未通过 |
| --- | --- | --- |
| Ubuntu 22.04 | unit 317 OK/15 skip；real-core 59 OK/0 skip；三格式 artifact-install 3 OK/0 skip，publishable_acceptance=true | privileged 6 tests，3 failures，0 skip：test20 环境继承、test40 TUN config-invalid、test60 系统安装 rc=2 |
| Ubuntu 24.04 | unit 317 OK/15 skip；real-core 59 OK/0 skip；三格式 artifact-install 3 OK/0 skip，publishable_acceptance=true | privileged setUp 的 useradd 超时 60s；0 tests、1 error，不能称两 UID/systemd/TUN 验收成功 |

两份 privileged JSON 虽带 real_uids/systemd/tun=true 环境标记，但 success=false；这些标记不能覆盖失败计数或零测试。所有通过结果只属于 d2e42b5，不能自动覆盖本次增量。

F 使用私有 Linux 副本独立执行一次：

```text
scripts/v1_ci.py --unit --pattern test_v1_installation.py --pattern test_v1_domain.py --report /tmp/mihomoctl-v1-f-permission-fixture-targeted.json
```

结果 **106 tests，OK，1 skipped，13.443s**（installation 66、domain 40）。唯一 skip 为真实 disposable privileged system installation，用下述临时文件系统检查不能替代。未重跑完整业务 unit 或 real-core。

### 安装目录权限

`installation.py:506-524` 新 `_mkdir_owned_parents` 先检查祖先、既有目录 trust，然后逐层 mkdir 缺失组件，调用方分别指定 0755 或私有 0700。wheel 解包、源码包复制、launcher 目录与 recovery 目录使用该 helper；不 chmod/repair 既有目录，production trust 规则未放宽。

定向回归验证 caller umask=002 的源码/wheel 安装、生成 CLI、安装 verify、卸载/恢复均可用，生成代码与 recovery 无 group/other writable 目录。F 另以 UID 0 在 root 私有临时目录中独立调用真实 helper：缺失两级代码目录均为 0755；既有 0775 目录被拒绝、mode 保持 0775、未创建 child；symlink ancestry 被拒绝。仅测试临时文件，不代表真实全局系统安装已通过。

### TUN receipt 路径

`scope.py:105-110` 将 receipt 放在 `state_root/tun/authorization.json`。只改变 receipt 位置，不放宽文件/祖先或原子 helper 的 private 检查。

F 以 UID 0 创建 root 私有临时 scope，实际 state root=0750，使用真实 Transaction 发布新 receipt，再调用无 tx 的 `synchronize_receipt`；仅 kernel ownership 使用替身，所有 filesystem/Transaction/atomic 检查为真实。结果 state 保持 0750、tun 子目录 0700、receipt 0600/root-owned，identity 更新成功；旧 state 根目录下直接 write_atomic 仍拒绝。domain 同时验证将 receipt parent 改为 0750 后 reconciliation 拒绝。未调用真实 systemctl、TUN 或改动网络。

### 验收 fixture 与诊断

- useradd 使用 no-create-home/no-log-init/user-group，在既有 disposable-root-systemd 限定下创建两账户；HOME 和初始 runtime 由 fixture 显式创建为 0700，并 chown 对应 UID/GID。超时延至 180s，没有跳过账户、重用 root 或放宽两 UID 条件。F 未在本机创建账户。
- command 失败仅输出 executable、rc 和提取的稳定 bootstrap code，不拼接 stdout/stderr。F 独立注入已识别与未知格式错误，虚构敏感 stdout/stderr 均不回显。
- test20 新增实际 loaded DropInPaths/EnvironmentFiles、环境文件八个固定 proxy key inventory、UnsetEnvironment 固定 key 检查；缺失变量诊断只列固定名字，最终仍要求 `inherited == expected_environment` 布尔为真。没有将环境变量非空、文件存在或 mock 结果替代实际值一致性。
- `git diff --check` 对这五个文件通过。

**本次未发现新增确定代码阻断，允许提交并推送所审五文件和本报告，运行下一轮真实 CI。** 这表示权限修复和 fixture/诊断可以进入真实验收，不表示三项 privileged 失败已解决：特别是 test20 的真实环境继承根因尚未确认，只增加了诊断，必须保留失败门槛。正式 Release 继续 BLOCKED，直到最终同提交两 Ubuntu 的完整 privileged（真实 UID/systemd/TUN/system install）、产物、其余 CI 及正式 release gate 全绿。

## 36bc CI 后六文件定向复审（2026-10-12 12:30 +08:00）

基线 HEAD 为 `36bc14ac8c8520b8a186d49bf58b329757b28559`。本次仅审冻结的 adapter/domain 以及 installation/bootstrap/installation-test/acceptance-test 六文件，写入本报告，未修改业务代码或测试、未提交、未重跑业务全量。

### 已下载真实平台证据

独立读取 `.tmp-v1-ci-36bc-evidence` JSON 与 `job22-b/job24` 日志。两 Ubuntu 均为 clean 36bc：unit **320 OK/15 skip**、real-core **59 OK/0 skip**、完整三格式 artifact-install **3 OK/0 skip** 且 publishable_acceptance=true；privileged 均 **6 tests，2 failures，0 skip**。

两个平台的实际 test10 两 UID/process、test30 system service/crash、test40 隔离 TUN enable/managed restart/SIGKILL 自动恢复/status/disable/路由恢复、test45 foreign device 拒绝均为 **PASS**。这更新此前“未执行/待运行”的历史记录，不能再将这些具体 36bc 用例写作未执行。但完整 privileged success 仍为 false：

- test20 已加载自有 drop-in，但 EnvironmentFiles 为空，尚未进入实际继承成功验收。
- test60 系统安装失败并回滚，稳定错误为 installation-failed-rolled-back；当前证据尚不能确定具体激活阶段根因。

这些部分 PASS 属于 36bc，不能跨提交拼成下一冻结提交的正式发布批准。

### F 独立定向执行

私有 Linux 副本执行一次 `scripts/v1_ci.py --unit --pattern test_v1_domain.py --pattern test_v1_installation.py --report /tmp/mihomoctl-v1-f-environment-diagnostics-targeted.json`：**108 tests，OK，1 skipped，13.905s**（domain 41、installation 67）。唯一 skip 是 disposable privileged system install，真实 systemd-analyze/parser 用例已执行通过，没有 skip。

### EnvironmentFile 真实解析与 literal path

`mihomoctl/integration/systemd_adapter.py:32-43` 拒绝非绝对路径/控制字符，不再用双引号包住 EnvironmentFile 整条路径；独立处理 percent specifier 和 libc glob 中的 backslash、`*?[]` 字符。没有改动 env 值或降低文件 trust。

F 独立实际运行 WSL 的 `systemd-analyze verify` 作旧/新对照（只解析临时 unit，不启动/改动服务）：旧 renderer **rc=0、loaded=false、warning=true**；新 renderer **rc=0、loaded=true、warning=false**。这证实不能只凭 verify 返回 0 断言 directive 已加载，根因确在旧引号格式。

domain 新用例对普通、空格、百分号、backslash、glob 字符五类真实文件路径检查 debug 中的实际 EnvironmentFile 记录、没有对应解析 warning，再以 libc.glob 验证唯一匹配实际目标文件；四类控制字符输入被拒绝。全部在 F 的定向运行中通过。**离线 renderer/parser 缺陷已验证修复；真实 user manager 的实际环境继承仍需下一 CI test20 通过。**

### 安装激活阶段与安全因果诊断

`installation.py:1281-1290` 将 launcher、permissions、post-activation verify 分为三个固定错误 code，保留同一恢复路径。`:1532-1556` 的 failure_codes 只接受显式 allowlist，OSError 映射 io-error，其他 code/type 映射 unclassified-error，并防止 cause 环；不输出异常 detail/path。bootstrap 增加安全 chain 行，fixture 只摘该字段，未修改成功门或将失败当 PASS。

F 在独立临时安装 fixture 对三个阶段分别注入一次真实 OSError，均得到 `installation-failed-rolled-back → 对应固定阶段码 → io-error`；实际旧 generation 恢复、pending 清除。另对 bootstrap main 注入含虚构敏感 code/detail 的未知 cause，返回 2，chain 只输出 unclassified-error，敏感内容不回显。此验证只证明恢复与诊断行为，**不代表 CI test60 的根因已修复或真实系统安装已通过**。

`installation.py:1174-1176` 在安装目标写入前验证 launcher 祖先 trust；新增回归确认 unsafe launcher parent 在 staging 安装前拒绝、install_root 未创建、既有树不变。无 repair/chmod 既有 unsafe 目录，无 trust 豁免。六文件 `git diff --check` 通过。

**本次未发现新增确定代码阻断，允许提交并推送所审六文件及本报告，运行下一轮真实 CI。正式 Release 保持 BLOCKED。** 下一轮必须使 test20 实际继承与 test60 系统安装验收全绿；若仍失败，利用固定安全因果码继续定位，不得放宽断言、跳过或沿用其他提交的部分 PASS。最终仍须两 Ubuntu 同一 clean 提交完整 CI/产物/privileged/release gate 一致通过。

## 5afffd7 独立契约复核与修复（2026-10-12 13:05 +08:00）

### 复核范围

对冻结后的分支做**只读**交叉复核，逐项比对「文档声明 / 发布清单 / 测试声明」
与「代码实际行为」：CLI 命令与 flag、退出码契约、`mihomoctl/v1` envelope 字段、
`release-manifest.json` 与磁盘的一一对应、TUN 与权限边界声明、
安装/更新路径中是否存在 shell 启动文件写入、以及文档是否声称了未通过的门禁。

### BLOCKER：`mihomoctl rules` 有文档、无实现

- 声明：`README.md:104`、`README.en.md:112`、`completions/mihomoctl.bash:6,59`
  以及 `docs/{en,zh-CN}/rules.md` 整页共同承诺 `mihomoctl rules status|check`。
- 实际：`mihomoctl/cli.py` 的 `dispatch()` 没有 `rules` 分支；
  `BRIDGE_COMMANDS` / `GUIDANCE_COMMANDS` 也不含它。任何调用都落到
  `cli.py` 的 `unknown-command`，退出码 `2`。
  `scripts/rules.py` 随 `runtime_files` 打包并有 `tests/test_rules.py`，
  但没有任何 CLI 入口能到达它。

处置：按「保留 Controller、订阅、策略和 TUI 能力」的产品决策**接线**而非删文档。
新增 `mihomoctl/legacy.py:run_rules()` 与 `cli.py` 的 `rules` 分支：只读、
不合成代理环境、不请求变更；由 V1 manager 显式提供内核 HomeDir 与生效配置路径，
`--home-dir` / `--config` 原样覆盖且绝不由工具猜测；检查器自身的 `0`/`1`/`2`
原样保留，`--json` 下以 `mihomoctl/v1` 信封重述，检查器载荷位于 `data.rules`。

实证（WSL Ubuntu 22.04，真实未 mock）：`rules status` 对三个 `0600` 规则文件
退出 `0` 并输出 PASS；`--json` 输出 `command=rules-status`、嵌套 rules/v1 载荷；
将 `rules` 目录放宽到 `0755` 后退出 `1`、`overall=FAIL`、
`rules-directory-mode-must-be-700`，fail-closed 保持。

### MAJOR：`service uninstall --dry-run` 谎报已完成

`cli.py` 在 `--dry-run` 下跳过整个事务与全部前置检查，却返回与真实卸载
**完全相同**的 `PASS` / `{"unit": ...}` / `removed mihomo.service`。
预览因此无法预测真实操作会失败——一个比没有预览更危险的契约。

处置：前置检查（受管运行时在运行、TUN 已启用）在两种模式下都执行；
预览返回独立的 `service-uninstall-preview` 与 `data.dry_run: true`，
不删除单元、不改写 manager，与 `migrate --dry-run` → `migrate-preview` 的既有约定一致。

### MINOR

`direct`、`config validate` / `config check`、`rollback`、`init --port`、
`migrate --remove-loader/--no-import/--core` 此前已实现但五份入口文档均未收录，
而 `rollback` 实际要求 `BACKUP` 位置参数。已在 README（中英）与
`docs/{en,zh-CN}/v1.md` 新增「保留的控制面」章节并补齐签名；
章节编号顺延，`README.md` / `README.en.md` 的锚点同步更新。
`docs/release-review.md` 曾固定在更早的提交上，本节即为最新结论。

### 复核确认无问题

- 退出码：`errors.py` 与 `envelope.exit_code()` 的 0/1/2 三档与文档完全一致。
- `exec` 透传：使用 `os.execve` 替换进程，子进程结果不重映射。
- 发布清单：183 个 `files` 全部存在于磁盘，所有 tracked 文件均已登记，
  无「磁盘有可执行 Python 但不在 `runtime_files`」的漏打包；
  wheel 仅含 `mihomoctl` 包与 dist-info，`scripts/paseo.py`、`tests/test_paseo.py`
  与私有笔记刻意不发布；归档的 paseo 文档页已带 ARCHIVED 标注。
- 无 shell hook：`install.sh`、`uninstall.sh`、`installation.py`、
  `bootstrap.py`、`scripts/{offline_install,update,migrate}.py`
  中无任何写入启动文件的路径。

### 本轮回归

WSL Ubuntu 22.04 私有副本：定向 46 项全通过；完整单元回归 331 项 0 失败。
真实 systemd、多 UID、隔离 TUN 与系统安装门禁由 CI 在本轮提交上重跑，
结论以前一提交 `5afffd7` 的实测为基线，正式发布仍以**打标签那一提交**的
完整 CI 与 `scripts/verify_release.py` 为准。

## dee8d0a 发布门禁结论（2026-10-12 13:40 +08:00）

### CI 结果

提交 `dee8d0a86e9ad65fecc77402286d3fc7305a71f3`，CI run `38206912788`，
Ubuntu 22.04 (Python 3.10) 与 Ubuntu 24.04 (Python 3.12) **两个平台全部通过**，
两平台数据完全一致：

| 套件 | 结果 | 跳过 |
| --- | --- | --- |
| unit / controller / TUI | 331 通过，0 失败，0 错误 | 15（全部为环境门控） |
| real-core（强制） | 59 通过，0 失败，0 错误 | **0** |
| artifact-install（源码包 / ZIP / wheel 离线安装、更新、自含回滚、卸载） | 3 通过 | **0** |
| privileged（真实双 UID、systemd、隔离 TUN） | 6 通过 | **0** |

`privileged` 的 `real_uids`、`systemd`、`tun` 三个平台证据标志均为 `true`；
`artifact-install` 的 `publishable_acceptance` 为 `true`；四份报告的
`source_dirty` 均为 `false`，`commit` 均为上述同一提交。

15 项单元跳过全部是环境门控，且每一项都在下面的专用套件里真实执行：
6 项 `PrivilegedAcceptance` 由 `privileged` 套件覆盖、1 项系统安装由 `test_60`
覆盖、7 项需真实内核由 `real-core` 覆盖，另有 1 项可选外部脚本夹具不属于
任何强制门禁。

### 发布门禁

```
python scripts/verify_release.py \
  --artifacts release-candidate-ubuntu-24.04 \
  --evidence . --commit dee8d0a86e9ad65fecc77402286d3fc7305a71f3
{"assets": ["mihomoctl-1.0.0-py3-none-any.whl", "mihomoctl-1.0.0.tar.gz",
 "mihomoctl-1.0.0.zip"], "commit": "dee8d0a...", "ubuntu": ["22.04", "24.04"],
 "verified": true, "version": "1.0.0"}
```

门禁确认：收据来自 git commit 而非工作树、`publishable` 为 true、版本为 1.0.0；
三个资产的 SHA256 与实际文件逐字节一致；`SHA256SUMS` 内容与收据清单精确匹配；
CI 在两平台上实际安装过的资产摘要与待发布资产完全相同；两平台被测内核的
`core_sha256` 是同一个摘要。缺失任一 Ubuntu 报告、任一强制套件出现跳过、
证据来自其他提交或工作树非干净，都会使门禁返回非零。

### 结论

上一节记录的 BLOCKER（`mihomoctl rules` 有文档无实现）与 MAJOR
（`service uninstall --dry-run` 谎报完成）均已修复并通过真实未 mock 验证，
回归已并入上述 CI 数字。

**代码层面不存在已知阻断项。** 本节之后仅追加 CHANGELOG 与本文件的验收结论，
不再改动实现、测试或发布清单；因此最终发布提交的代码树与本节实测的
`dee8d0a` 完全一致，差异仅为文档表述。

正式发布仍以**打标签那一提交**自身的 CI 与 `scripts/verify_release.py` 为准：
该门禁绑定 commit，拒绝工作树构建、其他提交的证据或任一强制场景跳过。
若标签提交的 CI 未通过，则不发布。
