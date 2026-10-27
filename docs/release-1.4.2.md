# 1.4.2 release notes / 发布说明

Batch latency now shows explicit untested/testing/failed/cancelled states, safe failure reasons and completion counts. Use `latency NODE --global` to select the global identity when a provider has the same name. Existing systemd installations must regenerate their managed unit with `service install` after upgrading; see [troubleshooting](en/troubleshooting.md).

批量测速明确展示未测试、测速中、失败原因及取消状态，并汇总数量；全局同名目标使用 `--global`。既有 systemd 安装升级后需执行 `service install` 更新托管 unit，详见[排障](zh-CN/troubleshooting.md)。身份或终止状态无法确认时保留恢复日志，不宣称已停止或已恢复。

Readable block YAML preserves types, Unicode, long URLs/regular expressions, comments and untouched configuration. Isolated core checks copy trusted geodata/provider resources and reuse process-local results only while their inputs remain unchanged. The 60-second default remains; failures report safe stage/timing evidence. Repeated downloads remain an unverified explanation of the original production timeout.

配置改写使用多行 YAML，保留类型、Unicode、长 URL/正则、注释和未修改内容。核心校验继续隔离执行，复制可信资源；输入变化时旧校验结果失效。默认超时仍为 60 秒，错误提供脱敏阶段和耗时。现场超时是否源于重复下载仍未确认。

Provider nodes are discovered separately from global proxies. CLI latency accepts `--provider`; the TUI carries provider identity through single/batch probes. Duplicate names, disappearing nodes, unsupported endpoints and connectivity failures have distinct outcomes. A latency result proves only the probe request, not ChatGPT or another business workload.

provider 节点纳入发现与链路证据；CLI 测速支持 `--provider`，TUI 单点/批量携带来源。区分同名、刷新消失、接口不支持和连通性失败；探测成功不等于业务端到端成功。

Private-path errors retain specific reasons. TUI failures show saving/activation stage and observed recovery state. The known FlClash metadata marker is discarded without permitting host-setting changes. Explicit `--policy policy` imports server routing fragments while preserving nodes and proxy-providers; see the [English](en/overrides.md) and [中文](zh-CN/overrides.md) tutorials.

权限错误保留具体原因，TUI 展示保存/激活阶段与恢复状态。兼容已知脚本元数据但不放宽运行字段权限；显式策略叠加模式保留节点及 provider。

The complete bundle retains pinned Python 3.12.15, Textual 8.2.8 and Mihomo v1.19.32 for Ubuntu 22.04/24.04 x86_64. Current-only retention and unfinished-transaction recovery remain in effect; no historical backups. Source migration, dual-UID SSH/PTY, isolated systemd/TUN, offline installation and v1.4.0 live-core upgrade gates remain mandatory. Publication must reuse the exact successful two-platform CI assets and verify draft/public downloads. No production server is used for this release's acceptance.

完整包继续内置固定解释器、界面依赖和核心，支持上述两个 Ubuntu 目标。成功后仅保留当前版本，不保留历史备份；未完成事务仍可恢复。正式发布必须通过既有双平台门禁，复用精确 CI 资产并验证草稿与公开下载。本次验收不操作生产服务器。
