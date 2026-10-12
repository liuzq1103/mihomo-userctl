# mihomoctl V1.0.0 独立发布审查

审查员：用户指定的 F 独立 Codex 审查员。初审落盘日期：2026-10-12（Asia/Shanghai）。

**最新结论（2026-10-12 11:16 +08:00）：代码审查允许推送增量修复后的发布分支运行下一轮实际 CI；F1–F12、duplicate 诊断及 public integration/锁外旧 manager 增量问题已在所审工作区关闭。正式 Release 仍为 BLOCKED / 真实 CI pending，不构成正式发布批准。以下保留初审、复现和修复记录，最新复审结论见文末。**

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
