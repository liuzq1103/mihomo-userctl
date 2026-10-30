# 1.4.3 release notes / 发布说明

All ten Textual pages now have direct navigation buttons. Narrow terminals use a compact two-row layout; subscription strategy labels fit without wrapping. The mode selector contains only real modes and synchronizes with the core without issuing a change request.

十个 Textual 页面均可通过按钮直达，窄终端使用紧凑的两行导航；订阅策略标签不再换行。模式下拉仅提供实际模式，界面刷新不会触发切换请求。

Home shows the active connection count and the five newest connections, including domain or destination IP, port, protocol, chain, rule and traffic. The connection page shows all rows. A shared single-flight snapshot refreshes every two seconds; errors retain the last good data with an explicit stale/error label, and data older than six seconds is stale. These destination fields are for the local Textual display only; default CLI and log output remains redacted. Avoid sharing screenshots containing private destinations.

首页显示活跃连接总数及最新五条连接的目标、端口、协议、链路、规则和流量，连接页查看全部。两页共用每两秒刷新的单任务快照；失败保留旧数据并显示错误，超过六秒未更新标记为旧数据。目标信息仅供本地 Textual 展示，默认 CLI 与日志仍脱敏；含私有目标的截图应仅在本地审阅。

Batch latency checks reuse one directory per operation and run at most eight probes. Results appear as they complete. Cancellation stops unsent probes and retains finished results; active requests finish under their existing timeouts. Each target keeps the ownership/authentication checks, and provider/name identities remain distinct. The five-second probe and eight-second HTTP timeouts are unchanged. This is latency testing, not download throughput testing; improvement depends on the network and controller.

批量延迟测速在单次操作内复用目录，最多八路并发，完成一项即显示一项。取消后不再提交探测，保留完成结果，进行中的请求按原超时收尾。逐目标属主和认证检查、provider 来源身份及错误分类继续保留。探测五秒、HTTP 八秒的超时不变；实际提速取决于网络与控制器，不增加下载带宽测试。

Fallback connection IDs no longer change with byte counters or routing fields. Indistinguishable duplicates without core IDs are marked as identity unverified in the local display; their row keys do not prove physical connection identity after reordering. Invalid connection collections are errors, not zero connections. Result/progress observer exceptions are counted separately and cannot abort probes. The directory reuse approach follows the operation-scoped reuse in [Magpie](https://github.com/yetone/magpie/blob/main/internal/gui/api.go); review checks also follow its [behavior-focused standards](https://github.com/yetone/magpie/blob/main/docs/code-standards.md). No Magpie runtime or gateway is added.

缺少核心连接 ID 时，备用 ID 不再随流量或路由字段变化；无法区分的重复条目标记“身份未确认”，其行键不证明重排后的物理连接身份。非法连接列表明确报错，不再显示成零连接。结果及进度回调异常单独计数，不中断探测。目录复用借鉴上述 Magpie 的操作内复用方式，并采用按行为验证的审核方法；未引入其运行时或网关。

The complete bundle retains the pinned Python, Textual and Mihomo versions, Ubuntu 22.04/24.04 x86_64 targets, current-only retention and existing release gates. Publication requires valid GLM and MiniMax independent/cross reviews, exact candidate-SHA approval, successful two-platform CI and review of the actual draft asset hashes. Timeouts, quota errors and malformed model replies are not approval.

完整包保留固定解释器、Textual、Mihomo、两个 Ubuntu 目标及既有发布门禁。正式发布要求 GLM 与 MiniMax 有效独立及交叉审核、完整候选 SHA 批准、双平台 CI 和实际草稿资产摘要核验；超时、额度错误或异常模型回复均不算批准。
