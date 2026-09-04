# 交给 Coding Agent 的安装 Prompt

[English](../en/agent-install-prompt.md) · [安装](setup.md) · [架构](architecture.md) · [安全](security.md) · [验收](acceptance.md)

把下列 Prompt 交给能访问目标 Linux 账号终端和文件的 Agent。占位符只填写非敏感
选择；凭据和订阅 URL 留在目标机器本地。

```text
请从经过审查的精确已发布标签，为这个普通 Linux 账号安装 mihomo-userctl。
直接完成工作并返回证据，不要只给方案。

任何写入前，完整阅读仓库约束以及这些规范文档：docs/zh-CN/setup.md、
architecture.md、security.md、acceptance.md、troubleshooting.md；选择 VS Code
Remote 集成时还要阅读 vscode-remote.md。遵循这些文档，不要把其中实现细节复制
成另一套临时流程。

先做能力检查和只读审计，记录当前账号、Linux/libc/架构、当前代理变量分类、
systemctl --user 可用性、服务名与 active/enabled 状态、Listener、ssh/sshd 进程、
正在运行的下载、已有 Mihomo 核心/配置/provider/规则、Shell 启动文件和 Git 工作区。
保留无关及未提交工作。只收集非敏感选择：项目固定 Release、Mihomo 官方固定
Release 与官方摘要、用户选择端口、订阅接入方式、启动文件、disabled 策略、可选
VS Code Remote http.proxy，以及保留/合并方案。写入前对具体变更和回滚取得明确批准。

敏感信息不得进入聊天、命令参数、日志、diff、Git 或最终报告；只能按安全文档在
本机读取。禁止 sudo、system service、linger、cron、TUN、透明/系统代理，以及
其他用户的文件或进程；不得结束客户端或下载。Mihomo 绝不自动启动；除非用户
明确选择其他策略，文档约定的用户服务保持 disabled。

只使用已审核检出和文档化的确定性安装器。在运行 ./install.sh --suggest-port 前，
先取得固定已发布标签。核对官方 Release 来源、资产、摘要、libc 兼容性、配置、带
认证回环 Listener、默认直连 Shell 边界和用户选择的窄 MATCH,DIRECT fallback。
仅在适用时使用文档化的 CODEX_REMOTE_PAYLOAD 兼容路径。不得另建安装器，也不得
用字符串求值替代安全参数数组。

按文档实际运行完整测试套件和 scripts/acceptance.sh，需要时使用 --expect-status。
保留真实退出码；使用管道时记录 PIPESTATUS，不能只取最后一项。只记录 SHA256
证据，不打印私有内容。每个已选检查必须标为 PASS、FAIL、UNVERIFIED 或 DEFERRED。
Listener readiness 不等于代理节点证据。

失败时在授权范围内停止并使用文档化回滚，不得临时发明破坏性恢复。最后给出
脱敏 diff 和最终验收报告，包括变更、版本与来源、实际测试命令/退出码、active/enabled
保持、备份及回滚命令、剩余 UNVERIFIED/DEFERRED，以及重开终端或重连长期客户端
等用户动作。未运行的检查不得报告为通过。
```
