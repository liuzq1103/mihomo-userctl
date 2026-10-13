# mihomo-userctl 代码审计报告（V1 基线）

- 审计基线：**当前 dirty 工作树的 0.9.3**（`install.sh:4` `VERSION=0.9.3`；`src/common.bash:9` `MIHOMO_USERCTL_VERSION="0.9.3"`；两者一致性由 `scripts/install_support.py:297-301` 强制）。工作树含 31 个已跟踪文件修改与 17 个未跟踪路径（`git status`，2026-10-11），全部保留并纳入分析。
- 审计日期：2026-10-11。方法：只读逐文件精读（src / scripts / tests / docs / CI / completions / examples / 根目录安装脚本）+ 模式扫描（`shell=True`、`eval(`、`os.system` 全仓零命中）+ 文档与 help 文案交叉核对。
- 严重度：高（流程/安全门当前即失效或被打红）、中（V1 必须处理的正确性/耦合缺陷）、低（明确改进项）、信息（实现与声明一致，记录为契约）。
- 结论色带：本报告不使用外部链接，事实一律以 `文件:行号` 引用，避免破坏 `tests/docs-test.sh:80-93` 的相对链接检查与 `tests/secret-scan.sh:4` 的模式扫描。

## 1. 执行摘要

安全工程整体质量高：不可变世代安装、`current` 原子切换、flock、pending-install 阻断、自含 restore.py 回滚、fail-closed 端口门、秘密最小暴露（凭据不进 argv、报告脱敏）均成体系且相互印证。

按已批准的 V1 决策，本报告撤销审计过程中形成的三条初步建议（见第 2 节），最终待办集中在：

1. 彻底移除自动 Shell hook（A1/A2/A4），fail-closed 健康门语义改由通用 `exec`/profile/integration 承载。
2. 安装器与用户配置/数据面解耦（D1/D2）。
3. `controller setup` 端口冲突校验补全（B1）。
4. 作用域模型：默认 user，root 的系统级变更必须显式 `--system`（C1）。
5. 发布物 allowlist 化 + 对发布清单/包做 secret scan（F2），不动用户未跟踪文件。
6. 旧专属 Paseo 生命周期退役，迁移仅提供通用接入，绝不自动停第三方应用（D6）。

## 2. 已批准的 V1 决策与被撤销的初步建议

| 初步建议（已撤销） | V1 决策（批准） |
| --- | --- |
| 保留 `.bashrc` loader 注入机制，仅改良 `CODEX_REMOTE_PAYLOAD` hook 的失败提示（原 A1/A2） | **彻底移除自动 Shell hook**：安装器不再写任何启动文件；`CODEX_REMOTE_PAYLOAD` 分支删除。保留的是 fail-closed 健康门语义（SAFE_TO_LAUNCH / BLOCKED / UNVERIFIED，不达标绝不放行），通过通用 `mihomoctl exec`、文档化 profile 片段（用户自行添加）、通用 integration/unit 生成（只写文件、永不 enable/start）承载 |
| root 一刀切拒绝（原 C1：`EUID==0` 即 die） | **默认 user 作用域；root 管理员为显式 system scope**：root 身份默认仍走 user 路径或拒绝系统级写入；任何系统级变更（system unit、全局路径、跨用户资源）必须显式 `--system` 才允许，且同样适用锁/备份/回滚/预检门 |
| 移走/删除根目录两份未跟踪学习笔记以恢复 secret-scan（原 F2） | **不删除、不移动用户文件**：发布只纳入显式审核的 allowlist 文件；`secret-scan` 增加发布模式，扫描发布清单/打包产物而非整个脏工作树 |
| uninstall 主动清理受管 `paseo.service` 并 daemon-reload（原 D6） | **旧专属 Paseo 生命周期不再支持**：`paseo start/restart/run/install-unit`、stop/替换流程退役；迁移只提供通用接入；**绝不自动停第三方应用**（移除一切对第三方 daemon 的 stop/ExecStop/替换逻辑）；uninstall 对历史遗留单元仅检测并提示，不代操作 |

以下第 3–8 节的事实与证据在撤销修订后仍然有效（事实不因建议修订而变化）。

## 3. Shell startup 自动修改 / hook 注入（V1：全部移除）

### A1 [中] 安装器自动改写 ~/.bashrc 并把 loader 置于交互性 guard 之前

- 证据：`install.sh:109-116`（受管目标含 bashrc）、`install.sh:137-140`（单标记块约束）、`install.sh:256-330`（loader 放置/刷新/迁移全流程）、`install.sh:266-283`（`case $- in ... return ... esac` guard 的 awk 启发式）、`install.sh:289-301`（把 guard 之后的存量受管块迁到 guard 前）、`install.sh:314-321`（guard 前插入）、`install.sh:322-326`（无 guard 时追加）、`install.sh:328`（`bash -n` 校验）、`examples/bashrc-loader.bash:1-17`、`src/shell.bash:3-21`（属主/权限校验后 source）。
- 事实分析：每个 source `.bashrc` 的 bash（含非交互，为 Codex Remote 设计）都会执行 `unset` 8 个代理变量（`examples/bashrc-loader.bash:2`）并 source 受管模块；缓解措施完备（标记块、备份、回滚、卸载移除 `uninstall.sh:42-63`），但自定义 guard 形态（如 `[[ $- != *i* ]] && return`）不匹配启发式时 hook 在非交互 shell **静默不生效**，无任何检测项。
- V1（已批准）：整套机制移除。安装器不再触碰启动文件；`proxy_on/proxy_off/with_proxy` 保留为显式函数（`src/shell.bash:30-63`），供用户自行 source 或放入自己的 profile 片段。**迁移必需**：为存量安装提供基于标记块的 loader 摘除命令（复用 `uninstall.sh:52-60` 已验证的 awk 剥离逻辑），V1 更新流程中显式执行并报告结果。

### A2 [中] `proxy_on || exit 1` 终止被 source 的整个 shell

- 证据：`src/shell.bash:84-86`（`CODEX_REMOTE_PAYLOAD` 存在且代理不可用即 `exit 1`）；对照 loader 自身失败路径用 `return 1 2>/dev/null || exit 1`（`examples/bashrc-loader.bash:14`）；行为被 `tests/test.sh:476-487` 固化为预期；`tests/docs-test.sh:242-246` 更把 `proxy_on || exit 1` 源码原文列为文档契约。
- 事实分析：fail-closed 方向正确（防"无代理的远程会话"），但 rc 文件杀死整个登录会话，stderr 仅一行错误（`src/common.bash:273`），无恢复指引。
- V1（已批准）：随 hook 一并删除。fail-closed 语义迁移到显式入口：`mihomoctl exec`（`src/mihomoctl:295-300`）已在子进程内实现同等的"预检不过绝不执行"；codex/preflight 的三态门（`scripts/diagnostics.py:434-522`，`execve` 于 `:559`）保留。删除时必须同步反转 `tests/docs-test.sh:242-246` 与改写 `tests/test.sh:476-487`、`tests/test.sh:377`、`tests/test.sh:400`（compat-probe 用例）。

### A3 [低] 无条件清除用户继承的代理变量

- 证据：`examples/bashrc-loader.bash:2`、`src/shell.bash:82`（source 即 `proxy_off`）；文档化于 `docs/en/security.md:35-45`。
- V1：随 loader 移除，"每个新 shell 被静默清变量"的行为消失；显式 `proxy_on/proxy_off/with_proxy/mihomoctl direct`（`src/mihomoctl:382-387`）语义不变。

### A4 [信息] 同 UID 进程设置环境变量即可触发自动注入

- 证据：`src/shell.bash:84`；威胁模型声明同 UID 不设防（`docs/en/security.md:54-56`）。随 hook 移除，该面自然消失；通用 integration 采用同样的"只写不启动"边界（参考 `scripts/paseo.py:542-569` 的写文件 + daemon-reload、永不 enable/start 模式）。

## 4. 端口与 listeners

### B1 [中] `controller setup` 端口冲突校验不完整（与 initialize 不一致）

- 证据：`scripts/controller_dashboard.py:127` 仅对照 `mixed-port/port/socks-port`；而 `scripts/controller_dashboard.py:48-54`（initialize）额外覆盖 `redir-port/tproxy-port/listeners[*].port`。
- 后果：setup 选出的 `external-controller` 端口可与 redir/tproxy/自定义 listener 同端口，`mihomo -t` 未必报错，运行时才冲突。
- V1：抽出公共 occupied-port 集合函数供 setup/initialize 共用；新增回归用例（两端口径一致）。

### B2 [低] 端口探测 TOCTOU（自认非预留）

- 证据：`scripts/controller_dashboard.py:28-33`（bind 后释放再写配置）；`scripts/controller_runtime.py:84-89`（probe bind，注释自认"not a reservation"）；`install.sh:66-79`（suggest-port 只查当前监听）。
- 分析：竞态存在但失败可观测（`port-collision` / `listener-service-ownership-unverified`，`scripts/controller_runtime.py:77-82`）。V1：文档保持如实声明，失败信息给出重试指引即可。

### B3 [低] acceptance 与 ready 的 IPv6 口径不一致

- 证据：`scripts/acceptance.py:85-96` 要求 ss 输出所有行恰为 `127.0.0.1:port`（`[::1]:port` 第二行即 FAIL）vs `src/common.bash:233-237` 只匹配 v4 行。
- 后果：同一双栈服务可能出现 acceptance FAIL 而 `mihomoctl ready` PASS。V1：统一策略（允许或明确拒绝 `::1`）并写入文档。

### B4 [信息] 多用户端口唯一性 = 约定 + 运行时门禁（保留）

- suggest-port 按 UID 播种（`install.sh:66-77`）；`gate()` 以 /proc 的 UID/族/地址 + cgroup-fd 归属校验后才放行 start（`scripts/controller_runtime.py:48-92`），属用户态上限，保留。

### B5 [信息] controller API 的属主校验（保留）

- `scripts/controller_api.py:54-71`：发送 bearer 前先查 `/proc/net/tcp` 监听 UID；endpoint 强制 `127.0.0.1:端口` + 32–256 位 URL-safe secret（`scripts/controller_config.py:77-86`）。

## 5. root / 多用户权限

### C1 [低→V1 重定义] 无作用域区分的 root 处理

- 事实证据：`install.sh:58-89`、`uninstall.sh`、`bootstrap.py:96-140` 均无 EUID 检查；root 场景仅被 `systemctl --user show-environment`（`install.sh:89`）间接拦截；sudo 指向他人 HOME 会被 `scripts/install_support.py:68-74` 的属主链校验拒绝。
- V1（已批准，取代"一刀切拒绝"）：**默认 user 作用域**；引入显式 `--system`：
  - root 无 `--system`：只允许操作自身 user 路径（等价普通用户约束），任何系统级写入直接拒绝；
  - root `--system`：显式管理员路径，纳入同一套锁/备份/回滚/预检门，动作前打印将变更的系统资源清单。
  - 测试断言：root 无 `--system` → 系统写拒绝；root `--system` → 审计输出完整。

### C2 [信息] safe_path 的 root+sticky 祖先豁免（保留）

- `scripts/install_support.py:63-67`：允许 root 属主 + sticky 目录作为私有 staging HOME 的祖先，注释论证正确（不可替换他人子文件）。保留。

### C3 [信息] 同 UID 边界实现与声明一致（保留）

- `scripts/diagnostics.py:163-167`、`scripts/paseo.py:206-213` 全部 `os.getuid()` 校验；`docs/en/security.md:30-33` 明示 loopback 属主机、严格 UID 隔离超出范围。保留。

### C4 [低] 根目录两份未跟踪学习笔记含真实环境信息

- 事实：两份未跟踪 md 含与真实服务器匹配的路径，命中 `tests/secret-scan.sh:4` 的 `/home/…` 类模式（本报告不复述具体值）。
- V1（已批准）：**不删除、不移动**。处置改为发布侧收口：见 F2。

## 6. 安装 / 更新 / 回滚耦合

### D1 [中] 安装器在事务结束后自动修改用户 config.yaml，且不在回滚 manifest 内

- 证据：`install.sh:343-355`（`transaction_active=0`、trap 已解除后于 `:348` 调用 `controller initialize`）→ `scripts/controller_dashboard.py:36-77` 写入 `external-controller`/随机 secret/`store-selected`/CORS（`:67-70`）；备份 manifest 仅 6 个受管文件（`install.sh:165`、`install.sh:109-116`）；回滚白名单不含 config.yaml（`scripts/install_support.py:404-409`）。
- 后果：安装失败回滚后 config.yaml 残留 controller 改动（仅 `.before-controller-*` 独立备份，需人工恢复）；"装控制层"隐式携带"改核心配置"。
- V1：二选一并落实——(a) initialize 移入事务并纳入 manifest（记录 before/after 哈希，回滚一并还原）；(b) 默认不自动 initialize，安装后提示显式执行。至少：安装输出打印 config.yaml 的具体变更与独立回滚命令。

### D2 [中] 全新安装把数据面就绪当发布门

- 证据：`install.sh:332-336` 用非 offline doctor 收尾；doctor 在 service=up 时执行真实 curl 探测（`src/mihomoctl:253-261`）；订阅/节点未就绪即安装失败并回滚（`tests/test.sh:429-446` 验证回滚本身）。setup.md 的顺序（第 6 步 start、第 8 步 install）使典型新装必然带活服务。更新路径已用 `--preserve-service-state` → `--offline` 规避同一问题（`install.sh:333`、`install.sh:45`），说明耦合已被认知。
- V1：全新安装同样允许（或默认）`--offline` doctor，把"代码可安装"与"代理已可用"解耦；验收交给 acceptance 阶段；同步 setup.md §8 表述与 `tests/test.sh:429` 用例前提。

### D3 [中] 更新验证的目标测试清单漏 test_health.py

- 证据：`scripts/update.py:159-170`（required 静态清单）与 `:194-202`（按版本动态追加）均无 `tests/test_health.py`；而 `controller_health.py` 自 0.9.3 起已是安装运行时组件（`scripts/install_support.py:33` 的 "health"、`:38` 的 paseo.py）；CI 却跑全量 `test_*.py`（`.github/workflows/test.yml:28`）。
- 后果：自我更新验证与 CI 覆盖不一致，health 模块发布后从未在更新路径被测。
- V1：按版本矩阵补齐；建立"新增 scripts 模块必须同步 required 测试与 RUNTIME 清单（`scripts/install_support.py:23-43`）"守则；同时复核 `:205` 的 180s/命令预算。

### D4 [低] 世代与备份无 GC

- 证据：每次更新新建完整世代（`scripts/install_support.py:302-369`）；仅 uninstall 清理（`:509-519`）；`docs/en/update.md` 自认无自动垃圾回收。
- V1：finish 后保守清理——仅删除 `result.json=PASS`、非 `previous`、非最近 N（如 3）个的旧世代；保留对应 backup 供审计；配"GC 后仍可回滚到 previous"测试。

### D5 [低] 可选 Textual 锁变更阻断更新

- 证据：`scripts/install_support.py:341-347`（旧 textual-env 存在且新锁 digest 不同即失败）。fail-safe 方向正确；V1 可降级为"无 TUI 继续 + 明确重装命令提示"。

### D6 [低→V1 重定义] 旧专属 Paseo 生命周期与 uninstall 残留

- 事实证据：`scripts/paseo.py:432-445`（stop 第三方 daemon）、`:448-473`（wait_ready）、`:499`（unit `ExecStop=`）、`:572-600`（前台接管）、`:705-749`（start/restart/run 生命周期，`:732-738` 含"先停旧实例再启动"）；`src/mihomoctl:302-330`（paseo 子命令分发）、`src/mihomoctl:268-281`（doctor 内嵌 daemon 报告）；`uninstall.sh:33` 的 targets 不含 `~/.config/systemd/user/paseo.service`（`scripts/paseo.py:476-477`）。
- V1（已批准）：上述生命周期全部退役；**绝不自动停第三方应用**（删除 stop/ExecStop/替换语义，环境漂移仅报告 BLOCKED 与维护窗口指引）；迁移仅提供通用 integration（生成凭证无关 unit：只写文件 + daemon-reload、永不 enable/start，模式等同 `scripts/paseo.py:542-569`，但参数通用化）；uninstall 对历史遗留单元仅检测 MARKER（`scripts/paseo.py:33`）并提示，不代删、不代办 daemon-reload。

### D7 [信息] 健全且必须保留的更新机制

- 拒绝降级（`scripts/update.py:387-388`）、tag 移动检测（`:401-402`）、pending-install 阻断（`scripts/install_support.py:303-304`、`install.sh:104`）、锁 + 世代指针双复查（`scripts/update.py:389-391`）、restore.py 随备份自含（`scripts/install_support.py:366-367`）、官方重定向白名单（`scripts/update.py:49-56`）、归档安全解压（`:114-149`）。

### D8 [低] bootstrap 自动采纳 suggest-port 未经确认

- 证据：`bootstrap.py:126-134` 自动取建议端口直装，与 setup.md"Confirm it with the user"（§3）有张力。V1：`--dry-run` 不选端口，或交互确认。

## 7. Setup（文档/help）与实现差异

- E1 [低] `mihomoctl help` 称 `controller setup` "Back up and validate ... no restart"（`src/mihomoctl:61-62`），实现会**改写 config.yaml**（`scripts/controller_dashboard.py:139-166`，返回 restart-required）。文案应为"Back up, validate, and write controller/UI settings (restart separately)"。
- E2 [低] `install.sh:346` 提示"Run mihomoctl tui to initialize the controller if needed"，而 `:348` 刚执行过 initialize——输出未反映实际初始化结果。
- E4 [低] `tests/docs-test.sh:242-246` 把 hook 源码原文、`:56-69` 把 paseo 文档字样固化为契约。V1 修改对应行为时必须同步（护栏兼耦合点）；hook 移除后该断言改为反向。
- E3 [信息] 核对一致的项：stop 只等服务端口释放绝不 kill（`src/mihomoctl:139-148`、`src/common.bash:329-337`）；install-unit 从不 enable/start（`scripts/paseo.py:542-569`）；配置按数据解析不 eval（`src/common.bash:101-150`）；凭证 URL 强制 `127.0.0.1:$MIHOMO_PORT`（`src/common.bash:199-213`）；配置/凭证 600+属主强校验（`src/common.bash:53-69`、`scripts/controller_config.py:15-21`）；override 脚本只能改 `proxy-groups/rules/rule-providers`（`scripts/controller_policy.py:104-106`）且明示 Node vm 非沙箱（`:20`）；日志凭据脱敏（`scripts/controller_service.py:442-451`）。

## 8. 测试 / CI

- F2 [高·流程] 当前工作树与门禁的关系（V1 已批准处置）：
  - `tests/secret-scan.sh:7-8` 扫描整个工作树，根目录两份未跟踪学习笔记命中 `:4` 模式 → 本地/CI 必 FAIL。处置：**不动笔记**；secret-scan 增加**发布模式**——以显式 allowlist（发布清单）为输入，扫描将要打包的文件集合/产物；默认（仓库模式）仅扫描已跟踪+显式列入清单的文件。发布打包步骤须校验"产物文件集合 == 清单"（机制雏形已存在：安装只复制 RUNTIME 清单文件 `scripts/install_support.py:309-311`；更新校验 required 文件存在 `scripts/update.py:159-170`；升级为打包期强校验即可）。
  - `tests/docs-test.sh:28-54` 要求 `docs/{en,zh-CN}/paseo.md`、`paseo-production.md`、`failover.md` 存在——当前以未跟踪文件满足；提交已跟踪改动时必须与这些新文档**同一原子提交**，否则干净检出即红。
- F1 [低] CI shellcheck 清单缺 `examples/bashrc-loader.bash`（`.github/workflows/test.yml:24`；bash -n 的 find 已覆盖它但无 shellcheck）。hook 移除后该文件删除，此条随闭环消解；在此之前补入清单。
- F3 [信息] 现有覆盖面（迁移时不得倒退）：`tests/test.sh:348-357`（安装/幂等）、`:359-400`（Ubuntu guard 与 legacy 迁移，hook 移除后需改写为"无 loader"断言）、`:402-403`（卸载保留数据）、`:405-446`（失败回滚）、`:448-465`（全新安装失败清理）、`:468-487`（fail-closed，语义迁移到 exec 入口）、`:490-496`（符号链接拒绝）；`tests/test_update.py`（43KB 更新回归）；CI 双 Python 跑 textual（`test.yml:37-59`）。
- F4 [低] `scripts/update.py:205` 每命令 180s 超时对慢机偏紧，随 D3 一并复核。

## 9. V1 保留能力清单（修订后）

1. 直连默认 + 8 个代理变量精确管理（`proxy_on/proxy_off/with_proxy/mihomoctl exec/direct`，`src/shell.bash:30-63`、`src/mihomoctl:295-300,382-387`）。
2. **fail-closed 健康门语义**：SAFE_TO_LAUNCH/BLOCKED/UNVERIFIED 三态与"预检不过绝不执行"，经通用 exec/profile/integration 显式承载（`scripts/diagnostics.py:434-522`、`src/mihomoctl:295-300`）。
3. 配置/凭证按数据解析 + 属主/600 模式强校验（`src/common.bash:101-150,53-69`）。
4. 端口 fail-closed 门（`scripts/controller_runtime.py:72-133`：UID/族/地址/归属 + after 复验 + config 端口一致性）。
5. 不可变世代 + `current` 原子切换 + flock + pending-install 阻断 + 自含 restore.py（`scripts/install_support.py:139-163,247-257,404-472`）。
6. 更新信任链（HTTPS tag→commit、安全解压、目标测试、不变量复查、拒绝降级/tag 移动）。
7. 卸载保留用户数据（`uninstall.sh:35-40` dry-run 声明与实现一致）。
8. 秘密最小暴露（凭据不进 argv：`src/mihomoctl:377-379`；集中序列化 `scripts/reporting.py:11-23`；日志脱敏 `scripts/controller_service.py:442-451`）。
9. 非破坏性停止（只 `systemctl --user stop` + 等端口释放，`src/mihomoctl:139-148`）。
10. **作用域模型**：默认 user；系统级变更必须显式 `--system`（新增契约）。
11. **发布物 allowlist**：只有显式审核过的文件进入发布，secret scan 作用于清单/产物（新增契约）。

## 10. 最小安全迁移顺序（修订后）

1. **hook 移除**（A1/A2/A4）：删除 loader 注入与 `CODEX_REMOTE_PAYLOAD` 分支；提供存量 loader 摘除命令（复用 `uninstall.sh:52-60` 标记块剥离）；反转 `tests/docs-test.sh:242-246`、改写 `tests/test.sh:359-400,476-487`；安装器自此不写启动文件。
2. **发布 allowlist + secret-scan 发布模式**（F2）：打包产物 == 清单强校验；不触碰任何用户未跟踪文件。
3. 低风险批次：B1（统一 occupied-port 集合）、E1/E2（文案）、D3（required 补 test_health.py）、F4。
4. D2：全新安装默认/允许 `--offline` doctor，验收移交 acceptance。
5. D1：initialize 归位决策（事务内纳管 vs 显式步骤）+ 回滚测试。
6. C1：`--system` 作用域门与审计输出。
7. Paseo 生命周期退役 + 通用 integration；uninstall 对遗留单元仅报告（D6）。
8. D4：世代 GC（保守策略 + 回滚兼容测试）；D5、D8 随批次收尾。

每步独立可回滚，先过 `tests/test.sh` + `tests/test_update.py` + 对应新增用例。

## 11. 测试清单（修订后）

- 摘除命令：对含存量标记块的 `.bashrc` 执行后，标记块消失、其余内容字节不变（对照 `tests/test.sh:378-383` 的恢复断言）。
- hook 不存在断言：安装后 `.bashrc` 无标记块；全仓无 `CODEX_REMOTE_PAYLOAD` 引用（取代 `tests/docs-test.sh:242-246`）。
- 通用 exec fail-closed：预检失败时子进程绝不执行、父环境不变（承接 `tests/test.sh:469-474` 的 with_proxy 语义）。
- 通用 integration：只写 unit + daemon-reload，断言无 enable/start/stop 副作用。
- root 作用域：无 `--system` 拒绝系统写；`--system` 输出完整变更清单。
- 发布模式 secret-scan：构造含违规样例的假清单 → FAIL；真实清单 → PASS；工作树模式不再因未跟踪笔记 FAIL。
- D1 决策后：安装回滚后 config.yaml 状态断言 + `.before-controller-*` 存在性。
- D2 后：全新安装 + service=active + CURL_FAIL=1 → 安装成功不回滚（`tests/test.sh:429` 前提反转）。
- B1：setup() 端口与 redir-port/tproxy-port/listeners 冲突报错。
- 卸载后：遗留受管单元被检测并提示（不代删）；`daemon-reload` 未被代办。
- D3：update validate 对 ≥0.9.3 目标必跑 `tests/test_health.py`。
- D4：GC 后仍可回滚到 previous 世代。
- 干净检出（无未跟踪文件）`tests/docs-test.sh` PASS（新文档与改动同一提交后）。

## 12. 审计边界与工作树状态

- 全程只读；未修改任何业务代码、未执行安装/服务/网络变更；本报告为唯一落盘产物（`docs/code-audit.md`）。
- 工作树状态（2026-10-11）：31 个已跟踪文件修改 + 17 个未跟踪路径，全部保留。未跟踪中与运行时行为相关的：`scripts/controller_health.py`、`scripts/paseo.py`、`tests/test_health.py`、`tests/test_paseo.py`、`examples/paseo-proxy.json`（均已审计）；其余为文档、学习笔记与样例。
- 与 CI 门禁的相容性：本文件不含 markdown 链接、不含 `tests/secret-scan.sh:4` 命中模式、不含 `tests/docs-test.sh:95-107` 封禁字样；行尾无空白。
