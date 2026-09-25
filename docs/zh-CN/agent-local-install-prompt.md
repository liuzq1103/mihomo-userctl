# 从共享目录安装的 Coding Agent Prompt

[English](../en/agent-local-install-prompt.md) · [下载清单与本地流程](offline-install.md) · [公开在线版 Prompt](agent-install-prompt.md)

适用于课题组提前备包的 Ubuntu 账号。先填共享目录和软件选择；这些都不是凭据。
通用参数、授权与报告要求见[安装参数与交付约定](deployment-contract.md)。

```text
请为当前普通 Ubuntu 用户从已有共享目录安装环境，直接完成授权范围内的工作并返回证据。
共享部署目录：<PUBLIC/mihomo-offline 的实际绝对路径>
运行时模式：<管理员公共 Node/npm/Codex / 明确选择个人安装；公共入口及版本>
选择软件：<共享模式默认仅 mihomo；个人模式才按需选择 node/codex；opencode 单独选择>
控制层：<是否安装 mihomo-userctl>
专属端口：<已确认端口，或先只读建议再向我确认>
已知环境与软件复用：<已有软件路径版本；默认复用满足要求的软件>
交付目标：<控制层安装 / 包含 Codex 端到端验收>
启动策略：<只安装并保留现状 / 安装并启动验收>
联网验收：<明确选择的订阅刷新、公开探测、最小模型请求；不代表允许联网安装>

这是本地安装，不是 GitHub 在线安装。先读取共享材料中的 offline-install.md、setup.md、
security.md、acceptance.md、architecture.md、troubleshooting.md、deployment-contract.md 和仓库约束。
文档、脚本和测试使用同一固定版本，不能扩大用户授权或混用 main。
setup.md 中获取 Mihomo/Git 源码的联网步骤由本地流程替代，不得照抄执行。
不访问 GitHub/npm/apt，不自动补下载，不运行 mihomoctl update 或其 --check。

先只读检查账号、Linux 架构/libc/CPU、基础依赖、systemctl --user、已有程序及 PATH、
代理环境分类、端口和服务状态。检查共享目录是否可信、普通用户是否有篡改权限，
审阅固定软件包清单、SOURCE.txt 和源码。缺包、摘要不符或依赖不满足就报告具体缺项并停止，
不得降级为联网安装。不要把安装器的 check 成功说成运行兼容性已经验证。
先报告简短审计与变更/回滚范围；复用适用的系统 Node/npm/Codex，不另装同名程序改变 PATH。
共享模式读取 shared-runtime.md：公共依赖缺失交管理员，不以个人包补齐；只装个人 Mihomo/控制层。
核对新登录与代理子进程的 Node/npm/Codex 路径、npm 启动器解释器和私有 CODEX_HOME。
保留认证、会话、NVM 和既有个人安装；默认值迁移/卸载需明确选择，不照搬笔记清理命令。
按 shared-runtime.md 分别检查 Remote hook、新 CLI 与长期 app-server 的 Unix socket/出站关联；
不以 0/8 或 8/8 单独判断模型请求路径，不持久设置 CODEX_REMOTE_PAYLOAD，不自动重启旧服务。
遵循 deployment-contract.md 的脱敏审计，只报告必要分类和状态，不回传环境、完整参数或原始日志。

使用文档化 offline_install.py check/install，仅安装我选择的软件；不运行 npm install、
npx 下载或包内安装脚本。遇到已有同名程序先保留，说明冲突及备份/迁移方案，不直接删除。
把已审核源码复制到当前用户私有目录，用原 install.sh 安装控制层。写入授权已明确时
继续执行；涉及未授权替换现有程序或尚未选择的个人配置时，先给出具体变更和回滚方案。
不使用 sudo，不修改共享目录、其他用户、系统服务、TUN 或系统代理；安装器不自行启动服务。
明确选择“安装并启动验收”时，配置测试与端口复核成功后可显式启动，保持 disabled；
只安装时保留已有运行状态，不为测试停服。已有授权无需重复确认。
每用户独立端口、服务与认证信息，默认服务保持 disabled；已有状态按原规范审查保留。

订阅和凭据只在个人受限权限文件中处理，不放入聊天、日志、Git、共享包或最终报告。
缺凭据时给出规范的本地文件和编辑方法，等用户填写后继续，不要求在聊天中粘贴。
OpenCode 如需关闭自动更新，只合并个人配置的 autoupdate=false，保留其他设置。
不自动安装插件、LSP、MCP 或扩展。运行期需要的远程资源应单独列为待准备项目。

按文档执行本地版本检查、源码回归测试及验收，保留真实退出码。未允许联网时不进行
模型登录、订阅刷新、代理节点外网探测等网络验收，标记 UNVERIFIED；仅用户明确延后才
记 DEFERRED。未选功能写“未选择”。按 deployment-contract.md 分别记录 Codex 程序、
新进程、Listener/代理出站和已授权最小模型请求证据，登录由用户完成。
未实测兼容性为 UNVERIFIED。Listener readiness 不等于节点连通证据。
最终列出版本/架构/SHA256/本地来源、个人安装路径与 receipt、控制层备份及回滚命令、
服务状态、实际测试结果和剩余步骤，使用通用约定的固定报告字段和有限隔离结论。
不要声称所有安装包具有独立官方签名验证。
最后必须按 deployment-contract.md 提醒订阅填写：实际绝对配置路径、provider 的准确 url 键、
本地编辑方法、填写后检查与授权验收；不把缺订阅说成完整可用。已有订阅说明保留，
file provider 给实际导入位置，不强迫输入 URL，也不索取聊天中的链接。
```
