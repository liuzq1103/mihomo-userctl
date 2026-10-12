# 文档导航 / Documentation

- [简体中文](zh-CN/README.md) · [中文首页](../README.md)
- [English](en/README.md) · [English overview](../README.en.md)

文档按语言维护；CI 检查必需 V1 文档是否齐全、入口文档是否覆盖 V1 关键词，
以及所有本地相对链接是否有效。
Documentation topics are maintained in both languages; CI checks that the required
V1 documents exist, that the entry documents carry the V1 markers, and that every
local relative link resolves.

## V1 基线 / V1 baseline

- **命令与配置契约 / Command and configuration contract**:
  [中文](zh-CN/v1.md) · [English](en/v1.md)
- 架构与实现契约 / Architecture and implementation contract: [architecture-v1.md](architecture-v1.md)
- 决策 / Decisions: [ADR 0002 — V1 通用运行时](adr/0002-v1-generic-runtime.md) ·
  [ADR 0001 — 基础决策](adr/0001-vnext-foundation.md)
- 设计参考与边界推导 / Design reference: [design-reference.md](design-reference.md)
- 代码审计 / Code audit: [code-audit.md](code-audit.md)
- 安装 / Installation: [INSTALL.md](../INSTALL.md)

## 使用 / Using

- 安装与首次启动 / Install and first start: [中文](zh-CN/setup.md) · [English](en/setup.md)
- 首次使用 / First use: [中文](zh-CN/first-run.md) · [English](en/first-run.md)
- 快速安装 / Bootstrap: [中文](zh-CN/quick-install.md) · [English](en/quick-install.md)
- 离线安装 / Offline install: [中文](zh-CN/offline-install.md) · [English](en/offline-install.md)
- 节点与面板 / Control plane: [中文](zh-CN/control-plane.md) · [English](en/control-plane.md)
- 控制台 / Console: [中文](zh-CN/console.md) · [English](en/console.md)
- 私有规则 / Private rules: [中文](zh-CN/rules.md) · [English](en/rules.md)

## 运维与验证 / Operations and verification

- 安全模型 / Security model: [中文](zh-CN/security.md) · [English](en/security.md)
- 验收与证据 / Acceptance and evidence: [中文](zh-CN/acceptance.md) · [English](en/acceptance.md)
- 更新与回滚 / Updates and rollback: [中文](zh-CN/update.md) · [English](en/update.md)
- 故障排查 / Troubleshooting: [中文](zh-CN/troubleshooting.md) · [English](en/troubleshooting.md)
- 多用户共享运行时 / Shared runtime: [中文](zh-CN/shared-runtime.md) · [English](en/shared-runtime.md)

## Coding Agent 提示 / Coding agent prompts

- 安装 / Install: [中文](zh-CN/agent-install-prompt.md) · [English](en/agent-install-prompt.md)
- 本地安装 / Local install: [中文](zh-CN/agent-local-install-prompt.md) · [English](en/agent-local-install-prompt.md)
- 更新 / Update: [中文](zh-CN/agent-update-prompt.md) · [English](en/agent-update-prompt.md)

## 已归档 / Archived

以下页面保留历史记录，**其中的命令面已在 v1.0.0 退役**，不要照其操作。
These pages are kept for the record; **their command surface was retired in
v1.0.0** and must not be followed.

- [Paseo 后台注入 / Paseo background injection](zh-CN/paseo.md) · [English](en/paseo.md)
- [Paseo 生产实施 / Paseo production](zh-CN/paseo-production.md) · [English](en/paseo-production.md)

替代方式是通用接入：`mihomoctl integration`。
The replacement is generic integration: `mihomoctl integration`.

## 历史路线 / Historical roadmap

[architecture-vnext.md](architecture-vnext.md) 与 [future-roadmap](zh-CN/future-roadmap-and-agent-prompts.md)
记录 V1 之前的设计讨论，**不代表当前实现**。以
[architecture-v1.md](architecture-v1.md) 为准。
These record pre-V1 design discussion and **do not describe the current
implementation**. [architecture-v1.md](architecture-v1.md) is authoritative.

本项目面向 Linux 用户级服务；仓库不分发、不安装 PC Clash/FlClash 规则。
This project manages Linux user services and ships no PC Clash/FlClash rules.
