# 交给 Coding Agent 的更新 Prompt

[English](../en/agent-update-prompt.md) · [更新指南](update.md) · [验收](acceptance.md) · [架构](architecture.md)

替换目标标签后，把下列 Prompt 交给能访问已安装 Linux 账号终端与文件的 Agent。
不要在 Prompt 中粘贴凭据。

```text
只把当前账号已有的 mihomo-userctl 更新到精确的正式版本 <vX.Y.Z>。
直接完成更新并报告证据。

写入前阅读仓库约束、docs/zh-CN/update.md、acceptance.md、architecture.md、
security.md 和当前安装元数据。以这些内容为规范，不得复制或另建安装、更新、
验证和回滚逻辑。

审计当前安装版本与不可变来源、原 HOME/XDG 和启动文件路径、受管文件完整性、
备份状态、服务 active/enabled 状态及无关工作。敏感值只留在本机，不得引用。
保留配置、凭据、端口、服务名、Mihomo 核心与数据、启动文件非托管内容，以及
全部无关文件与进程。禁止 sudo、改变服务状态、升级 Mihomo 或重连/结束客户端。

实际运行并记录真实退出码：
  mihomoctl update --check
  mihomoctl update --version <vX.Y.Z> --dry-run
  mihomoctl update --version <vX.Y.Z>

只有安装元数据确实属于文档所述旧式布局时才使用 scripts/migrate.py。不得改用
main/latest、接受移动标签、静默降级、逐个复制模块或伪造来源。恢复时复用现有
事务和本次精确的私有备份。

不启动原本停止的服务，按文档运行完整测试与验收。每个已选项目使用 PASS、FAIL、
UNVERIFIED 或 DEFERRED，包括版本/来源、运行模块完整性、设置保持、active/enabled、
Listener/认证、目标路由、新 Shell 和长期客户端。Listener readiness 不是节点选择。
新 Shell 与客户端重连在用户执行并验证前保持 DEFERRED。

最后报告精确命令与退出码、请求/安装版本、commit 与归档身份、实际摘要、变更与
保留范围、备份、准确回滚命令、剩余失败和用户动作。跳过或未运行的项目不得写通过。
```
