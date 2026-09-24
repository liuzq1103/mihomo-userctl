# 交给 Coding Agent 的安装 Prompt

这是面向公开仓库用户的**官方在线来源版**。已提前下载软件到共享目录的课题组用户请改用
[本地安装 Prompt](agent-local-install-prompt.md)，不要混用两套获取流程。

[English](../en/agent-install-prompt.md) · [安装](setup.md) · [架构](architecture.md) · [安全](security.md) · [验收](acceptance.md)

把下列 Prompt 交给能访问目标 Linux 账号终端和文件的 Agent。占位符只填写非敏感
选择；凭据和订阅 URL 留在目标机器本地。
先填写[安装参数与交付约定](deployment-contract.md)中的非敏感参数，已有选择无需重复确认。

```text
请从经过审查的精确已发布标签，为这个普通 Linux 账号安装 mihomo-userctl。
直接完成工作并返回证据，不要只给方案。
已知环境与软件复用：<系统/架构/已有软件路径版本；默认复用满足要求的软件>
运行时模式：<管理员公共 Node/npm/Codex / 明确选择个人安装；公共入口及版本>
交付目标：<控制层安装 / 包含 Codex 端到端验收>
启动策略：<只安装并保留现状 / 安装并启动验收>
联网验收：<明确选择的订阅刷新、公开探测、最小模型请求；未授权的不执行>

先获取并审阅固定源码，在修改目标环境前完整阅读同一版本的 deployment-contract.md、
仓库约束以及这些规范文档：docs/zh-CN/setup.md、
architecture.md、security.md、acceptance.md、troubleshooting.md；选择 VS Code
Remote 集成时还要阅读 vscode-remote.md。遵循这些文档，不要把其中实现细节复制
成另一套临时流程；文档、脚本、测试不得跨版本混用，文档不能扩大用户授权。

先做能力检查和只读审计，记录当前账号、Linux/libc/架构、当前代理变量分类、
systemctl --user 可用性、服务名与 active/enabled 状态、Listener、ssh/sshd 进程、
正在运行的下载、已有 Mihomo 核心/配置/provider/规则、Shell 启动文件和 Git 工作区。
保留无关及未提交工作。只收集非敏感选择：项目固定 Release、Mihomo 官方固定
Release 与官方摘要、用户选择端口、订阅接入方式、启动文件、disabled 策略、可选
VS Code Remote http.proxy，以及保留/合并方案。给出简短审计及变更/回滚范围；已有
明确批准或安装授权时继续执行，只对未授权替换、冲突或未决选择提出具体问题。
优先复用已安装软件，不替换系统 Node/npm/Codex，不另装同名程序改变 PATH 优先级。
共享模式必须读取 shared-runtime.md：只装个人 Mihomo/控制层，公共依赖缺失交管理员，
不自行补装 Node/Codex；核对正常与代理子进程的 PATH、npm 启动器所用 Node 和私有 CODEX_HOME。
保留个人认证、会话和 NVM；迁移默认值或旧程序需明确选择，禁止照搬其他机器的清理命令。
同时按 shared-runtime.md 核对 Remote hook、CLI/桥接/app-server 和 Unix socket 复用链路；
0/8 或 8/8 不单独证明模型请求路径，不持久设置 CODEX_REMOTE_PAYLOAD，不自动停止旧服务。
审计遵循 deployment-contract.md 的脱敏要求，不回传环境转储、完整进程参数或原始日志。

敏感信息不得进入聊天、命令参数、日志、diff、Git 或最终报告；只能按安全文档在
本机读取。禁止 sudo、system service、linger、cron、TUN、透明/系统代理，以及
其他用户的文件或进程；不得结束客户端或下载。安装器不自行启动或 enable 服务；
明确选择“安装并启动验收”时，配置测试与端口复核成功后可显式启动，保持 disabled。
只安装时保留已有运行状态。缺凭据时提供受限本地文件和编辑方法，等待用户填写，勿索取聊天值。

只使用已审核检出和文档化的确定性安装器。在运行 ./install.sh --suggest-port 前，
先取得固定已发布标签。核对官方 Release 来源、资产、摘要、libc 兼容性、配置、带
认证回环 Listener、默认直连 Shell 边界和用户选择的窄 MATCH,DIRECT fallback。
仅在适用时使用文档化的 CODEX_REMOTE_PAYLOAD 兼容路径。不得另建安装器，也不得
用字符串求值替代安全参数数组。

按文档实际运行完整测试套件和 scripts/acceptance.sh，需要时使用 --expect-status。
保留真实退出码；使用管道时记录 PIPESTATUS，不能只取最后一项。只记录 SHA256
证据，不打印私有内容。每个已选检查必须标为 PASS、FAIL、UNVERIFIED 或 DEFERRED。
Listener readiness 不等于代理节点证据。按 deployment-contract.md 分别验收 Codex 的
实际程序、新进程、Listener/代理出站和已授权最小模型请求；登录由用户完成。
证据不足或未授权检查为 UNVERIFIED；仅用户明确延后才记 DEFERRED，不把未选功能记为通过。

失败时在授权范围内停止并使用文档化回滚，不得临时发明破坏性恢复。最后给出
脱敏 diff 和最终验收报告，包括变更、版本与来源、实际测试命令/退出码、active/enabled
保持、备份及回滚命令、剩余 UNVERIFIED/DEFERRED，以及重开终端或重连长期客户端
等用户动作。使用 deployment-contract.md 的固定报告字段，隔离结论限于实际操作与检查范围。
未运行的检查不得报告为通过。
```
