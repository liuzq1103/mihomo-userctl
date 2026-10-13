# mihomo-userctl 后续路线与 Coding Agent Prompts

> 状态：规划文档，不代表功能已经实现。
>
> 审计基线：2026-09-02，当前工作树中的安装器版本为 `0.1.6`。实施任何阶段前，
> 都必须重新审计最新代码、文档和测试，不能把本文描述当作当前实现事实。

## 1. 文档目的

本文集中记录当前设计讨论中发现的问题、推荐的长期架构、实施优先级、验收标准，
以及可以交给具备终端和文件工具的 Coding Agent 使用的分阶段 Prompt。

本文只属于 `mihomo-userctl` 项目。它不属于 FlClash PC 规则生成项目，也不要求
修改 FlClash 的规则、Profile、Merge、Listener 或运行时配置。

项目继续坚持以下边界：

- 服务器普通 Shell 默认直连；
- 代理按命令、按应用或按明确兼容钩子启用；
- 不使用 sudo，不修改其他用户；
- 只操作当前用户的 `systemctl --user` 服务；
- Mihomo 服务保持 `disabled`，不配置 linger、cron 或自动启动；
- 不让 `mihomo-userctl` 接管订阅、节点内容、完整 Mihomo 配置或内核更新；
- 不默认开启 TUN、系统代理、路由修改、Dashboard 或 Controller；
- 不在命令行、日志、Git、报告或聊天中显示订阅 URL、Listener 凭据和节点密钥；
- 同一共享服务器上的不同用户必须使用不同端口；
- 项目不能读取、停止或清理其他用户的配置、服务、进程和端口。

## 2. 当前已经覆盖的能力

当前控制层主要覆盖：

- `mihomoctl start/stop/restart/status/ready/doctor/logs/version`；
- `proxy_on/proxy_off/proxy_status/with_proxy`；
- `.bashrc` 中的短 managed loader；
- 普通 Shell 默认清除八个代理变量；
- `CODEX_REMOTE_PAYLOAD` 的本地实测兼容钩子；
- VS Code Remote `http.proxy` 的人工配置和排错文档；
- 安装时原子替换、事务备份、失败回滚；
- 卸载控制器代码和 `.bashrc` managed loader，同时保留 Mihomo 核心配置。

需要明确：`mihomo-userctl` 当前只决定程序是否进入 Mihomo。Mihomo 内部的节点
选择、域名规则、策略组、fallback 和订阅策略仍由用户自己的 Mihomo 配置负责。
公开项目不得包含维护者或任何用户的真实数据集、科研站点、节点名称和专属规则。

## 3. 已发现的问题

### 3.1 代理入口不能只按“终端”和“VS Code”理解

真正决定程序能否联网的是它的**启动边界**和**代理配置来源**。除终端和 VS Code
扩展外，还存在：

| 类型 | 示例 | 主要风险 |
| --- | --- | --- |
| 交互式 Shell | SSH、VS Code 集成终端 | 用户可能忘记当前 Shell 已执行 `proxy_on` |
| 非交互命令 | SSH RemoteCommand、部署脚本 | 可能不读取 `.bashrc` |
| 长期驻留进程 | tmux、screen、Codex App Server | 一直保留启动时的旧环境 |
| IDE 扩展宿主 | VS Code、Cursor、Windsurf | 不执行 Shell 函数，各产品行为不同 |
| 远程 IDE | JetBrains Gateway、code-server | 可能使用自己的代理配置 |
| Notebook | JupyterLab、Kernel、RStudio Server | Kernel 与 Server 继承链不同 |
| 用户服务 | `systemd --user` 程序 | 默认不读取 `.bashrc` |
| 调度任务 | Slurm、PBS、cron | 作业环境可能经过过滤或复制 |
| 子进程生态 | MCP Server、语言服务器 | 是否继承以及是否遵循代理变量并不一致 |
| 容器 | Docker、Podman、Apptainer | 容器内 `127.0.0.1` 不是宿主回环地址 |
| 应用自有配置 | Git、npm、pip、浏览器 | 应用配置可能覆盖环境变量 |

因此项目不应为每个软件默认写入全局配置。长期设计应提供通用的命令启动边界，
再为少数经过验证的应用提供可选适配器和诊断说明。

### 3.2 环境变量只在进程创建时继承

修改 `.bashrc`、VS Code 设置或凭据后，已经运行的 tmux、Extension Host、Codex
App Server、MCP Server、Jupyter Kernel 和后台服务不会自动获得新环境。

项目需要能回答：

- 某个 PID 是否包含代理变量；
- 它是否连接当前用户的 Mihomo Listener；
- 它是否仍在直接连接外网；
- 哪个父进程负责启动它；
- 用户应该重启哪个属于自己的客户端或进程。

诊断功能只能读取当前用户可见的信息，不得按进程名称批量杀进程。

### 3.3 当前更新方式安全，但缺少完整生命周期模型

当前安装器可在已有安装上重复运行，并且会：

- 保留 `client.env`；
- 拒绝显式传入与现有配置冲突的端口；
- 原子替换控制器、模块和补全；
- 刷新 `.bashrc` managed loader；
- 创建事务备份；
- 最终 `doctor` 失败时回滚活动文件；
- 不启动或 enable Mihomo。

仍缺少：

- 明确记录“安装版本”和“文件所有权”的安装收据；
- 升级、重复安装和降级的区分；
- 配置格式变化时的版本化迁移；
- 对本地修改过的受管文件给出漂移提示；
- 备份保留和人工清理策略；
- 更新后提醒现有 Shell 仍加载旧函数；
- 从经过验证的新版本检出到安装验收的完整入口。

在旧仓库目录直接重新运行 `install.sh` 只会重新安装旧代码，不等于升级。

### 3.4 当前卸载是“卸载控制层”，不是“删除 Mihomo 环境”

当前卸载器会删除项目代码和 `.bashrc` managed loader，但会保留：

- Mihomo 二进制和用户服务；
- `config.yaml`、`client.env`、`mihomo-shell.conf`；
- 订阅、provider 和缓存；
- 安装事务备份和 `.bashrc` 卸载备份；
- 用户手工配置的 VS Code `http.proxy`；
- 其他应用中可能存在的代理引用。

这种保守行为可以防止误删用户数据，但存在几个必须显式说明的问题：

1. 卸载脚本是子进程，无法清除调用它的父 Shell；如果卸载前运行过
   `proxy_on`，当前 Shell 仍可能保留八个代理变量。
2. 删除 managed loader 后，新 Shell 不再由本项目主动清理从父进程继承的代理
   变量。
3. VS Code `http.proxy` 可能继续指向 Listener；如果以后停止 Mihomo，远程扩展
   会超时。
4. 新的 Codex Remote 会话不再获得本项目的兼容代理钩子，服务器不能直连时会
   失去联网能力。
5. 老的 tmux、Codex、MCP、Jupyter 或 Extension Host 可能继续持有旧环境，形成
   新旧状态混合。

卸载器不能删除或恢复它从未记录、无法证明归本项目所有的外部设置。

### 3.5 用户缺少标准化的自定义规则维护入口

每个用户都可能需要自己的直连、代理或拒绝规则，但这些规则既不能进入公共项目，
也不应长期无结构地堆在含凭据的 `config.yaml` 中。当前文档只有通用配置示例，
尚未形成一套稳定、可验证、可备份的用户规则工作流。

长期设计需要同时满足：

- 规则文件位于 Mihomo HomeDir 内，由当前用户所有，默认权限 `600`；
- 直连、代理和拒绝规则分别存放，避免修改一类规则时影响其他策略；
- 主配置只通过 `type: file`、`behavior: classical` 的 rule-provider 引用；
- 用户规则优先于宽泛规则，最终 fallback 仍由用户明确决定；
- 修改后先运行 Mihomo 配置测试，成功后才允许重启用户服务；
- 备份、检查和错误输出不得泄露私有域名、内部 IP、凭据或订阅信息；
- 公共仓库只提供占位模板和机制，永远不收集、同步或提交真实用户规则。

第一阶段应优先提供文档和只读检查，不立即让控制器改写 `config.yaml`。只有安装
收据、文件所有权和恢复模型成熟后，才考虑可选的初始化、备份和恢复命令。

### 3.6 手动切换节点与当前安全模型冲突

用户可能使用 `url-test` 等自动策略组；此时控制的是“是否进入 Mihomo”，不是
“固定使用哪个节点”。运行时列出节点、测速、固定节点、更新 provider、查看
连接和规则命中通常需要 Mihomo Controller API。

Controller 会扩大攻击面，因此必须是后期、可选、默认关闭的能力。不能为了节点
面板破坏现有的 loopback-only、无 Dashboard、无 Controller 默认模型。

## 4. 目标架构

```text
调用者
├─ 交互 Shell ───────── proxy_on / with_proxy / direct
├─ 非交互命令 ───────── mihomoctl exec / mihomoctl direct
├─ IDE / Notebook ───── 可选适配器 + 专项 doctor
├─ systemd / 调度器 ─── 文档化的显式启动边界
└─ 容器 ─────────────── 单独的网络与凭据安全方案
          │
          ▼
  经过白名单解析的本地配置和凭据
          │
          ▼
127.0.0.1:<每用户唯一端口> ── Mihomo ── 用户自有规则和节点

用户自有策略
├─ rules/custom-direct.yaml
├─ rules/custom-proxy.yaml
└─ rules/custom-reject.yaml
          │
          └─ config.yaml 中的本地 rule-provider 只负责引用
```

项目分为三层：

1. **稳定核心**：生命周期、Shell 隔离、安全配置解析、readiness、脱敏诊断。
2. **可选适配器**：VS Code、进程检查、systemd/Notebook/调度器指南；必须幂等、
   可审计、可回滚。
3. **可选 Controller 扩展**：节点、provider、连接、流量和规则解释；默认不安装、
   不启用。

## 5. 分阶段实施计划

### P0：先冻结契约和建立回归基线

目标：在增加功能前保护现有“默认直连”和“用户隔离”行为。

任务：

- 写明当前文件所有权边界和非目标；
- 为现有安装、重复安装、失败回滚、卸载和 Codex 钩子补齐测试矩阵；
- 为八个代理变量建立统一断言；
- 记录当前命令输出和退出码契约；
- 增加测试，确保 FlClash 项目从不被安装器、卸载器或测试写入；
- 增加测试，确保任何命令都不使用 sudo、system service、linger 或 cron；
- 建立敏感信息扫描，覆盖测试失败输出、备份 manifest 和诊断输出；
- 明确 Bash、Linux、systemd user manager、`curl`、`ss` 等最低依赖。

验收：

- 当前完整测试继续通过；
- 失败场景不会改变 Mihomo 服务 enabled 状态；
- 普通新 Shell 默认八个代理变量全部不存在；
- 所有测试使用临时 HOME，不触碰真实用户配置。

### P1：通用启动边界和诊断

目标：不再把能力限制在终端函数或某一个 IDE。

新增建议：

```text
mihomoctl exec command [args...]
mihomoctl direct command [args...]
mihomoctl test-url URL
mihomoctl inspect-process PID
mihomoctl inspect-name NAME
mihomoctl status --json
mihomoctl ready --json
mihomoctl doctor --json
```

行为要求：

- `exec` 在子进程中安全加载凭据并导出八个代理变量，不污染父 Shell；
- `direct` 在子进程中明确清除八个代理变量，适合 `axel`、S3 和大文件；
- 两者使用 `--` 消除命令参数歧义，不使用 `eval`；
- 无命令、配置错误或权限错误返回 `2`；readiness 失败返回 `1`；
- `inspect-process` 只允许检查当前用户有权读取的 PID；
- 只报告变量数量、endpoint、父子关系和连接类别，不打印变量值；
- 不杀进程，不自动重启 IDE、Codex、MCP、tmux 或 Notebook；
- JSON 输出具有稳定 schema，stdout 只放数据，诊断文字写 stderr；
- `test-url` 必须分别标识 direct、代理入口、认证和目标请求结果；
- URL 输出和错误信息必须脱敏，防止凭据出现在 curl 错误中。

验收：

- 父 Shell 在 `exec` 和 `direct` 前后字节级保持相同代理环境；
- `mihomoctl direct axel ...` 不连接 Listener；
- `mihomoctl exec` 经认证 Listener 成功；
- 当前用户旧 Codex App Server 的 `0/8` 环境能被准确识别；
- JSON 可由标准 JSON 解析器读取且不包含凭据。

### P1：用户自定义规则维护契约与只读检查

目标：让每位用户安全维护自己的 Mihomo 规则，同时保持公共项目与私有策略彻底
分离。该阶段优先级与通用诊断相同，但初版只提供文档、模板和只读验证，不自动
修改含凭据的主配置。

推荐布局：

```text
<Mihomo HomeDir>/rules/custom-direct.yaml
<Mihomo HomeDir>/rules/custom-proxy.yaml
<Mihomo HomeDir>/rules/custom-reject.yaml
```

主配置使用本地 rule-provider：

```yaml
rule-providers:
  custom-direct:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-direct.yaml
```

任务按风险分两步实施：

**P1a：文档与只读能力**

- 新增中英文自定义规则维护指南，说明匹配顺序、三类文件、配置测试和回滚；
- 提供只含占位域名的示例文件，示例不得包含维护者或用户真实策略；
- 新增 `mihomoctl rules check`，检查目录、所有者、权限、YAML 基本结构、provider
  引用和规则目标组是否存在；
- 新增 `mihomoctl rules status [--json]`，只输出文件存在性、规则数量、摘要和最近
  修改时间，不输出具体域名、IP 或规则内容；
- 调用用户已有 Mihomo 二进制做完整配置测试，但只读、不重启服务；
- 规则文件不存在时清楚报告，不擅自创建或改写 `config.yaml`。

**P2：可选写入能力**

- 安装收据和所有权模型完成后，再考虑 `mihomoctl rules init --dry-run`、`init`、
  `backup`、`list-backups` 和 `restore --dry-run`；
- `init` 只创建缺失的用户规则文件并输出需要人工审核的主配置片段，不自动注入
  `config.yaml`；
- 已存在文件默认拒绝覆盖；恢复前必须显示脱敏摘要并验证备份归属；
- 修改规则后只运行配置测试，是否重启 Mihomo 必须由用户单独明确执行；
- 不提供把规则自动上传公共 Git、远程服务或其他用户目录的功能。

验收：

- 所有测试使用临时 HomeDir 和虚构域名；
- `rules check/status` 不修改任何文件或服务状态；
- 输出、JSON、错误和备份 manifest 不包含规则原文或敏感信息；
- 非当前用户所有、权限过宽、符号链接、重复 provider、非法 YAML 和未知策略组
  均明确失败；
- 用户规则位于宽泛规则之前，配置最后 fallback 缺失时给出警告；
- 公共文档和测试 fixture 对维护者专属标识的扫描为零。

### P1：安全更新模型

目标：让已安装用户能确定地升级、失败回滚，并知道哪些状态不会自动刷新。

任务：

- 新增权限 `600`、严格解析、无敏感信息的安装收据；
- 收据记录项目版本、安装时间、受管路径、受管文件摘要、配置 schema 版本和
  `.bashrc` marker，不记录凭据内容；
- `install.sh --dry-run` 显示 fresh install / reinstall / upgrade / downgrade；
- 默认拒绝降级，只有显式 `--allow-downgrade` 才允许；
- 检测受管代码是否被本地修改并在覆盖前警告；
- 配置迁移必须按 schema 版本逐级执行，先备份、后验证、再原子替换；
- 失败时恢复代码、loader、非敏感配置和收据；
- 保留 `client.env`、Mihomo 核心、服务、订阅和缓存；
- 更新不启动、不停止、不重启、不 enable Mihomo；
- 安装完成后明确提示“现有 Shell 仍加载旧函数，请重新登录或 `exec bash`”；
- 文档给出从可信仓库取得目标 tag、检查差异、dry-run、安装、doctor 的完整步骤；
- 不实现静默联网自动更新。

验收：

- 从每个受支持旧版本升级的测试通过；
- 重复安装幂等；
- 降级默认被拒绝；
- 模拟每个写入阶段失败时均能恢复；
- 更新期间运行中的 Mihomo 和下载不被中断；
- 凭据文件内容和摘要在更新前后保持不变。

### P1：可解释、无障碍的卸载

目标：既不留下隐蔽的失效代理引用，也不误删其他软件配置。

建议把动作名称明确分开：

```text
./uninstall.sh --dry-run
./uninstall.sh
./uninstall.sh --scan-references
./uninstall.sh --purge-userctl-data --dry-run
./uninstall.sh --purge-userctl-data
```

默认 `uninstall.sh` 仍表示“移除控制器和 Shell 集成、保留 Mihomo 环境”。不要使用
语义模糊的 `--purge` 来暗示会删除 Mihomo 核心。

任务：

- 卸载前检查当前进程环境；如果调用脚本的 Shell 看起来处于 proxied 状态，明确
  提示必须先在父 Shell 执行 `proxy_off`；
- 由于子进程不能修改父 Shell，卸载完成后打印一条安全的 `unset` 指令，不声称
  已清理当前 Shell；
- 基于安装收据删除项目拥有的代码和 loader；
- 引用扫描只检查当前用户明确允许的已知路径，不遍历或读取其他用户 HOME；
- 检测 VS Code Machine `http.proxy`、已知 managed adapter、当前用户进程环境、
  用户级 unit 和端口监听；
- 扫描结果只报告“存在引用”和路径，不打印认证 URL；
- 对项目曾通过适配器写入的外部设置，只有存在安装前备份、marker/receipt 和
  哈希验证时才能自动恢复；
- 对用户手工配置的 VS Code、Git、npm、pip、Jupyter 等设置只警告，不删除；
- 默认不停止 Mihomo 服务；如未来增加停止选项，必须单独显式授权；
- `--purge-userctl-data` 只能删除收据证明归控制层所有的非核心数据，继续保留
  Mihomo 二进制、service、`config.yaml`、订阅和 provider；
- 备份默认保留，提供独立、显式、带 dry-run 的备份清理命令；
- 最终报告列出删除、保留、无法安全判断和需要人工处理的项目。

验收：

- `.bashrc` marker 外的字节保持不变；
- 卸载不会修改其他软件已有配置；
- 手工 VS Code 代理存在时只提示，不擅自删除；
- 卸载后新 Shell 不再定义项目函数；
- 当前 Shell 仍有旧变量时不会错误报告为“已清理”；
- Mihomo 核心和正在运行的服务默认不受影响；
- 第二次卸载幂等。

### P2：应用适配框架

目标：为不同启动机制提供统一规范，而不是把所有软件都写进核心。

优先适配：

1. VS Code Remote；
2. 当前用户进程与 Codex/MCP 继承链诊断；
3. `systemd --user` 使用指南；
4. tmux/screen 旧环境排查；
5. Jupyter/RStudio；
6. Slurm/PBS；
7. JetBrains Gateway、Cursor、Windsurf、code-server；
8. 容器网络专题。

接口建议：

```text
mihomoctl app list
mihomoctl app vscode status
mihomoctl app vscode doctor
mihomoctl app vscode install --dry-run
mihomoctl app vscode install
mihomoctl app vscode uninstall --dry-run
mihomoctl app vscode uninstall
```

适配器契约：

- 默认只读；修改必须显式调用 install/uninstall；
- 安装前备份原始值，记录精确所有权和哈希；
- 不覆盖配置文件中的其他键；
- 不把凭据复制到不必要的位置；
- 如果目标应用能够使用受权限保护的引用文件，优先引用而不是复制；
- 安装和卸载均幂等；
- 配置生效需要重启时只提示用户正常重连，不批量杀进程；
- 每个适配器文档都要说明影响范围、进程继承、验证和回滚；
- 未经实测的产品只能标记为实验性，不能承诺兼容。

容器适配必须单独评审。不能把宿主的 loopback Listener 暴露到 LAN，也不能默认
使用 host network；必须先定义容器到宿主的安全可达方式和凭据边界。

### P3：可选 Controller 扩展

目标：在不改变默认安全模型的前提下提供节点和流量管理。

可选命令：

```text
mihomoctl nodes [--group GROUP]
mihomoctl current GROUP
mihomoctl latency [--group GROUP]
mihomoctl select GROUP NODE
mihomoctl select GROUP --auto
mihomoctl provider status
mihomoctl provider update NAME
mihomoctl provider healthcheck NAME
mihomoctl connections [--process NAME] [--large]
mihomoctl traffic
mihomoctl trace DOMAIN
```

安全要求：

- Controller 功能编译/安装后仍默认关闭；
- 首次启用必须显示威胁模型并取得明确批准；
- 只允许 loopback TCP Controller 加随机高强度 API 密钥，或权限严格限制的 Unix
  Socket；两种方案必须分别测试；
- 不能监听 `0.0.0.0`，不能启用宽松 CORS，不能安装 Dashboard；
- Unix Socket API 不能假设 Mihomo `secret` 会生效，必须依赖目录和 Socket 权限；
- API 密钥不得进入命令参数、日志、Git 或报告；
- 所有名称通过 JSON 编码，不手工拼接请求体；
- `select --auto` 必须清除 URLTest/Fallback 的固定选择，而不是随便选择一个节点；
- 节点列表默认不显示节点协议凭据；
- 连接输出默认聚合和脱敏，关闭连接属于破坏性操作，v1 不提供；
- Controller 不得改变 service disabled、默认直连或 per-user port 模型。

验收：

- 未启用 Controller 时所有现有命令行为不变；
- 未认证 TCP API 请求被拒绝；
- Socket/目录权限不允许同机其他普通用户访问；
- 节点切换、恢复自动选择、provider 更新和延迟测试均有模拟 API 测试；
- API 不可用时返回清晰错误，不重启 Mihomo作为替代手段。

### P4：高级维护

后续可考虑：

- `mihomoctl audit`：检查 loopback、认证、TUN、Controller、service disabled、权限、
  旧端口引用和多用户端口冲突；
- `mihomoctl config test/summary/diff`：只输出脱敏摘要；
- `mihomoctl backups list/prune`：显式、可预览地管理备份；
- `mihomoctl update-check`：只检查版本，不静默下载和安装；
- `mihomoctl credentials rotate`：事务式同步 Listener 和 `client.env`，失败回滚；
- 安全恢复命令：恢复前显示脱敏差异，恢复后重新执行 doctor 和 readiness。

凭据轮换风险较高，应放在安装收据、版本迁移、备份恢复和敏感信息扫描全部成熟
之后。

## 6. 推荐发布顺序

| 里程碑 | 内容 | 发布条件 |
| --- | --- | --- |
| `0.2.x` | P0、`exec/direct`、JSON 状态、进程诊断、规则只读检查 | 不改变现有默认行为 |
| `0.3.x` | 安装收据、版本迁移、升级、卸载及可选规则初始化/备份 | 跨版本和故障注入测试完整 |
| `0.4.x` | 应用适配框架、VS Code doctor | 每个适配器可回滚 |
| `0.5.x` | 可选 Controller、节点/provider/连接 | 安全评审通过且默认关闭 |
| `0.6.x` | audit、备份、恢复、更新检查 | 敏感信息和恢复测试通过 |
| `1.0.0` | 稳定 CLI、配置 schema 和兼容承诺 | 至少一个完整小版本周期验证 |

每个里程碑都应独立发布，不建议一次性实施全文。先解决启动边界和卸载障碍，再
考虑节点面板等便利功能。

## 7. 通用实施约束

以下约束适用于本文所有 Prompt：

1. Agent 必须具有读取文件、执行终端命令、修改文件和等待用户回复的能力；否则
   只给人工步骤，不声称完成。
2. 固定采用“只读审计和计划 → 等待明确批准 → 实施 → 测试 → 报告”的流程。
3. 不使用 sudo，不登录其他用户，不读取其他用户 HOME，不结束未知进程。
4. 不修改 FlClash PC 规则项目。
5. 不启动、停止、重启或 enable 真实 Mihomo，除非该阶段和用户批准明确要求。
6. 所有自动测试使用临时 HOME、伪造依赖和非真实凭据。
7. 不在聊天中索取或展示订阅 URL、密码、令牌、完整 `client.env` 或节点内容。
8. 修改前检查 Git 状态，保留用户已有未提交修改，不 reset、不覆盖无关文件。
9. 使用原子写入、权限校验、备份和失败回滚；不使用宽泛正则修改启动文件。
10. 最终报告列出改动文件、测试、风险、备份、回滚和未完成事项，但不包含敏感
    信息。

## 8. 分阶段 Coding Agent Prompts

下面的 Prompt 是未来任务入口。每次只复制一个阶段，不要一次要求 Agent 完成
所有阶段。

### Prompt A：P0 契约与测试基线

```text
你正在维护独立 Bash 项目 mihomo-userctl。请先阅读 README、双语 docs、
install.sh、uninstall.sh、src、completions、tests 和 CI。不要修改 FlClash 项目。

目标：冻结当前行为契约并补齐回归测试，不新增用户功能。

必须先只读审计：
1. 当前版本、Git 状态、测试入口和依赖；
2. 所有安装路径、权限、managed marker、备份和回滚路径；
3. proxy_on/off/status/with_proxy 的环境变量、退出码和父子 Shell 隔离；
4. systemctl --user 的 active/enabled 行为；
5. 安装、重复安装、更新、失败回滚和卸载的现有覆盖；
6. 敏感信息可能出现在 stdout、stderr、测试 fixture、manifest 或 Git 的位置。

输出完整实施计划、预期修改文件、测试矩阵和回滚方式，等待我明确批准后再修改。

实施边界：无 sudo、无其他用户、无真实凭据、无真实服务变更；所有测试使用临时
HOME 和伪造命令。确保普通新 Shell 默认清除八个代理变量，service 仍 disabled，
安装器和卸载器不接触 Mihomo 核心、订阅和 FlClash。运行 Bash 语法、ShellCheck、
完整测试、文档链接、敏感信息扫描和 git diff --check。最终给出证据化报告。
```

### Prompt B：P1 通用启动边界和进程诊断

```text
请为 mihomo-userctl 设计并实现通用命令启动边界和脱敏诊断。先只读审计当前
CLI、common.bash、shell.bash、配置解析、测试和文档；输出计划并等待我明确批准。

目标命令：
- mihomoctl exec -- command [args...]
- mihomoctl direct -- command [args...]
- mihomoctl test-url URL
- mihomoctl inspect-process PID
- mihomoctl inspect-name NAME
- status、ready、doctor 的 --json 输出

要求：exec 只给子进程导出经过校验的八个代理变量；direct 只在子进程中清除它们；
都不得污染父 Shell，不得使用 eval。进程诊断只能读取当前用户有权访问的进程，
只输出代理变量数量、父子关系、endpoint 和连接类别，绝不输出变量值或凭据；不杀
进程。JSON stdout 必须是稳定有效数据，文字诊断写 stderr。test-url 清楚区分服务器
直连、Listener、认证和目标请求结果。保持 service disabled、默认直连、无 sudo、
无 Controller、无 FlClash 修改。

为成功、参数错误、权限错误、readiness 失败、恶意参数、带空格参数、父子 Shell
隔离、旧 Codex/MCP 进程和敏感信息泄漏建立自动测试。同步更新中英文 README、
architecture、security、troubleshooting 和 completion。运行完整质量检查并报告。
```

### Prompt C：P1 用户自定义规则维护契约与只读检查

```text
请为 mihomo-userctl 设计并实现用户自定义 Mihomo 规则的标准维护方式。先只读审计
当前 setup、architecture、security、Mihomo HomeDir、config.yaml 示例、控制器和
测试；输出文件所有权、隐私边界、失败停止条件和实施计划，等待我明确批准。

本阶段只实现中英文维护指南、虚构示例和只读命令：mihomoctl rules check，以及
mihomoctl rules status [--json]。推荐把 custom-direct.yaml、custom-proxy.yaml 和
custom-reject.yaml 放在 Mihomo HomeDir 的 rules 目录，由 config.yaml 通过本地
type:file、behavior:classical、format:yaml 的 rule-provider 引用。用户规则应位于
宽泛规则之前；最终 fallback 由用户明确配置。

check/status 只能检查当前用户文件的存在性、所有者、权限、符号链接、YAML 基本
结构、provider 引用、策略组存在性和完整 Mihomo 配置测试。默认输出不得显示规则
原文、真实域名、内部 IP、订阅、节点或凭据；JSON 只给数量、摘要、时间和状态。
不得创建或修改规则文件，不得改写 config.yaml，不得启动、停止或重启 Mihomo。

公共示例只能使用保留的示例域名/IP，不得包含维护者或测试用户的真实数据集、科研
站点、策略组或节点名称。新增防回归扫描。所有自动测试使用临时 HomeDir、伪造
Mihomo 和虚构规则，覆盖权限过宽、非当前用户、符号链接、非法 YAML、重复 provider、
未知策略组和敏感输出。保持默认直连、service disabled、无 sudo、无其他用户和
无 FlClash 修改。运行完整质量检查并给出脱敏报告。
```

### Prompt D：P1 安全升级模型

```text
请为 mihomo-userctl 实现可验证、可迁移、可回滚的更新模型。先只读审计当前
install.sh 的事务、备份、端口冲突、doctor 回滚和现有测试；输出详细计划，等待我
明确批准后实施。

必须增加一个权限 600、严格解析且不含敏感信息的安装收据，记录项目版本、配置
schema、受管路径、受管文件摘要和 .bashrc marker。install.sh --dry-run 必须区分
fresh install、reinstall、upgrade、downgrade；默认拒绝 downgrade，显式批准才允许。
检测受管文件漂移，在覆盖前警告。为配置 schema 实现逐版本迁移框架；先备份，
验证后原子替换，失败恢复代码、配置、loader 和收据。

始终保留 client.env、Mihomo 二进制、用户服务、config.yaml、订阅、provider 和
缓存；更新不能启动、停止、重启或 enable Mihomo。更新成功后提示现有 Shell 仍是
旧函数，需要重新登录或 exec bash。不要实现静默自动更新。

使用临时 HOME 测试所有受支持版本升级、重复安装、默认拒绝降级、显式降级、文件
漂移和每个写入阶段的故障注入。验证凭据内容不变、备份权限正确、输出脱敏。更新
中英文安装和排错文档，运行完整测试和敏感信息扫描。
```

### Prompt E：P1 安全卸载和残留检查

```text
请改进 mihomo-userctl 的卸载模型。先只读审计 uninstall.sh、安装路径、备份、
.bashrc loader、VS Code 文档和当前测试；区分项目拥有的文件、用户手工配置以及
Mihomo 核心。输出计划并等待我明确批准。

默认卸载的语义固定为：删除 mihomo-userctl 控制器、模块、补全、安装收据和受管
.bashrc loader，但保留 Mihomo 二进制、用户 service、config.yaml、client.env、
订阅、provider、缓存和用户备份。默认不停止服务。

增加 --dry-run、--scan-references 和名称明确的 --purge-userctl-data。引用扫描只
检查当前用户允许的已知路径，检测 VS Code Machine http.proxy、项目适配器、当前
用户进程环境、用户级 unit 和 Listener；不打印 URL 或凭据。手工配置只能警告，
不能删除。只有安装收据、备份和哈希共同证明由项目写入的外部设置才能自动恢复。

特别处理父 Shell 限制：卸载脚本不能声称清除了父 Shell。若检测到代理环境，提示
用户先 proxy_off；卸载后打印安全的八变量 unset 命令。不得使用 eval，不得杀进程，
不得读取其他用户。增加幂等卸载、手工 VS Code 设置、旧 tmux/Codex 环境、缺失
marker、重复 marker、哈希冲突和失败回滚测试。同步更新中英文文档并完整验收。
```

### Prompt F：P2 应用适配框架和 VS Code Doctor

```text
请为 mihomo-userctl 设计可插拔的应用适配框架，并先只实现经过实机验证的 VS Code
Remote 适配器。先审计现有 docs/*/vscode-remote.md、安装器边界、凭据解析和测试，
输出威胁模型、文件所有权方案、备份/恢复方案和实施计划，等待我明确批准。

建议接口：mihomoctl app list；mihomoctl app vscode status/doctor；以及显式、支持
--dry-run 的 install/uninstall。默认命令只读。安装不能覆盖 settings.json 的其他键，
必须保存安装前值、文件摘要和权限；卸载只有在 receipt 与哈希验证通过时恢复本项目
写入的键，否则停止并给人工建议。所有输出脱敏，不打印 http.proxy 值。

doctor 需要区分 Extension Host 和 Codex app-server，检查它们是否属于当前用户、
是否包含预期变量数量、是否连接配置端口，并提醒环境只在进程创建时继承。只能建议
正常 Reload/Reconnect，不能按名称杀进程。不要假设 Cursor、Windsurf、JetBrains、
Jupyter 或 MCP 与 VS Code 行为相同；为它们只建立适配器规范和实验性文档占位。

保持默认直连、service disabled、无 sudo、无 Controller、无其他用户操作。使用临时
HOME 和 JSON fixture 测试配置保留、并发漂移、回滚、幂等和敏感信息扫描。
```

### Prompt G：P3 可选节点和流量控制

```text
请为 mihomo-userctl 设计一个默认关闭、明确 opt-in 的 Mihomo Controller 扩展。
先阅读当前安全模型和 Mihomo 官方 API/Controller 文档，验证目标 Mihomo 版本的
实际接口。只做只读审计、威胁模型和完整计划，等待我明确批准后才修改。

目标功能：nodes/current/latency/select、恢复 url-test 自动选择、provider status/
update/healthcheck、connections/traffic 和域名规则解释。不能安装 Dashboard，不能
监听 0.0.0.0，不能开启宽松 CORS，不能改变 TUN、系统路由、默认直连或 service
disabled。TCP Controller 只能绑定 loopback 并使用本地生成的高强度 API 密钥；
Unix Socket 方案必须考虑 API 不校验 secret 的事实，使用严格目录和 Socket 权限。

密钥不得出现在参数、日志、Git、测试输出或报告。请求体必须由安全 JSON 编码生成，
不能拼接节点名。select --auto 要使用官方语义清除 URLTest/Fallback 的 fixed 选择。
API 不可用时只报告，不通过重启模拟。连接功能默认只读、聚合和脱敏，不实现关闭
连接。使用伪造 API 完整测试认证、编码、节点名攻击、不可用、超时和敏感信息泄漏，
并证明未启用扩展的旧安装行为完全不变。
```

### Prompt H：P4 审计、备份和凭据轮换

```text
请为 mihomo-userctl 规划并分步实现 audit、脱敏 config summary、备份管理和凭据
轮换。先只读审计现有配置所有权、Mihomo Listener、client.env、用户 service 和备份
目录；输出风险分级计划并等待我明确批准。不要一次同时实现全部高风险功能。

audit 应检查 loopback-only、Listener 认证、意外 TUN/Controller、service disabled、
文件权限、旧端口引用和当前用户端口冲突，但不打印敏感值。backup list/prune 必须
默认只读，prune 要求 --dry-run 和明确执行，禁止静默清理。

credentials rotate 只能在安装收据、事务恢复和测试成熟后实现：本地生成新凭据，
同步更新当前用户 Mihomo Listener 与 client.env，测试配置，显式重启当前用户服务，
验证认证，失败完整回滚。不得把凭据放进命令参数、聊天、日志、Git 或报告；不得
修改其他用户、系统服务或 FlClash。为每一个中断点做故障注入测试。
```

### Prompt I：阶段发布和文档收尾

```text
请对 mihomo-userctl 当前阶段做发布前审计，不新增范围外功能。先检查 Git diff、
未提交用户修改、版本号、CHANGELOG、中英文 README 和 docs、命令帮助、completion、
测试和 CI。输出发布计划并等待我明确批准。

确保中文和英文文档结构对应但语言自然，不机械直译；明确当前已实现与未来规划，
不得把规划功能写成已发布功能。检查所有链接、示例端口占位、多人服务器端口隔离、
默认直连、service disabled、更新、卸载残留、VS Code/终端/长期进程差异和回滚。

运行 Bash 语法、ShellCheck、完整测试、文档测试、secret scan、git diff --check，并
确认仓库不存在真实订阅 URL、Listener 凭据、节点密钥或 client.env。只有全部通过
才提交；推送、创建 tag 和发布 Release 属于外部操作，必须分别取得明确授权。最终
报告提交摘要、测试证据、兼容性、已知限制和下一阶段，不显示敏感信息。
```

## 9. 每个阶段的完成定义

一个阶段只有同时满足以下条件才算完成：

- 代码、命令帮助、中英文文档和 completion 一致；
- 正常路径、错误路径、权限错误和故障回滚都有自动测试；
- 不泄露凭据、订阅或节点内容；
- 不改变普通 Shell 默认直连；
- 不改变 Mihomo 服务 `disabled`；
- 公共文件不包含维护者或任何用户的真实自定义规则；
- 不修改其他用户和 FlClash；
- 不覆盖用户无关改动；
- `git diff --check`、ShellCheck、完整测试、文档链接和敏感信息扫描通过；
- 有明确的升级、卸载和人工回滚说明；
- 最终报告能区分“已实现”“人工验证”“尚未验证”和“刻意不支持”。

## 10. 当前最推荐的下一步

按投入产出比，建议依次执行：

1. Prompt A：冻结现有契约；
2. Prompt B：实现 `exec`、`direct`、JSON 和进程诊断；
3. Prompt C：建立用户自定义规则的文档契约和只读检查；
4. Prompt D：建立安装收据和版本迁移；
5. Prompt E：解决卸载残留与外部引用；
6. Prompt F：把 VS Code 经验沉淀成可选适配器；
7. 安装收据成熟后，再实现规则初始化、备份与恢复；
8. 稳定运行一个版本周期后，再决定是否执行 Prompt G 开启可选 Controller。

节点切换和流量面板很直观，但没有更新、卸载、所有权和诊断基础时，优先实现它们
会让项目更难安全维护。当前最有价值的改进仍是：**通用启动边界、进程诊断、安装
收据、自定义规则只读检查和可解释卸载**。
