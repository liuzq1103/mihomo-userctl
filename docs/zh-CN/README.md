# 简体中文文档

> **v1.0.1：** 自动 Shell hook 已移除，安装器不写任何启动文件；应用专属 daemon
> 生命周期已退役。命令面以 [V1 命令与配置契约](v1.md) 为准。

全新服务器建议按顺序阅读：

1. [安装 · Installation](../../INSTALL.md)
2. [安装指南与完整环境](setup.md)
3. [首次使用](first-run.md)
4. [V1 命令与配置契约](v1.md)
5. [V1 架构与实现契约](../architecture-v1.md)
6. [安全模型](security.md)

## V1 基线

- [V1 命令与配置契约](v1.md)
- [V1 架构与实现契约](../architecture-v1.md)
- [ADR 0002：V1 通用运行时与退役第三方生命周期](../adr/0002-v1-generic-runtime.md)
- [设计参考与边界推导](../design-reference.md)
- [代码审计](../code-audit.md)
- [安全策略](../../SECURITY.md)

## 使用

- [安装指南](setup.md) · [快速安装](quick-install.md) · [离线安装](offline-install.md)
- [首次使用](first-run.md)
- [节点管理 / Nodes and dashboards](control-plane.md)
- [控制台](console.md) · [控制台验收](console-acceptance.md)
- [TUI 覆写与手动组](tui-overrides.md)
- [私有自定义规则契约与只读检查](rules.md)
- [VS Code Remote](vscode-remote.md)
- [多用户共享运行时](shared-runtime.md)

## 运维与验证

- [安装参数与交付约定](deployment-contract.md)
- [安装验收与证据要求](acceptance.md)
- [更新与回滚](update.md)
- [故障排查](troubleshooting.md)
- [安全模型](security.md)

## Coding Agent 提示

- [安装 Prompt](agent-install-prompt.md)
- [本地安装 Prompt](agent-local-install-prompt.md)
- [更新 Prompt](agent-update-prompt.md)

## 已归档

以下页面保留历史记录，**其中的命令面已在 v1.0.0 退役**：

- [Paseo 后台注入与 systemd](paseo.md)
- [Paseo 生产实施报告](paseo-production.md)

替代方式是通用接入 `mihomoctl integration`；详见
[V1 旧命令退役映射](v1.md#12-旧命令退役)。

## 历史路线（不代表当前实现）

[architecture-vnext.md](../architecture-vnext.md) ·
[未来路线与 Agent 提示](future-roadmap-and-agent-prompts.md) ·
[ADR 0001](../adr/0001-vnext-foundation.md)
