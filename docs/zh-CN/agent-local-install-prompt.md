# 从共享目录安装的 Coding Agent Prompt

[English](../en/agent-local-install-prompt.md) · [下载清单与本地流程](offline-install.md) · [公开在线版 Prompt](agent-install-prompt.md)

适用于课题组提前备包的 Ubuntu 账号。先填共享目录和软件选择；这些都不是凭据。

```text
请为当前普通 Ubuntu 用户从已有共享目录安装环境，直接完成授权范围内的工作并返回证据。
共享部署目录：<PUBLIC/mihomo-offline 的实际绝对路径>
选择软件：<mihomo，以及可选 node、codex、opencode>
控制层：<是否安装 mihomo-userctl>
专属端口：<已确认端口，或先只读建议再向我确认>

这是本地安装，不是 GitHub 在线安装。先读取共享材料中的 offline-install.md、setup.md、
security.md、acceptance.md、architecture.md、troubleshooting.md 和仓库约束。
setup.md 中获取 Mihomo/Git 源码的联网步骤由本地流程替代，不得照抄执行。
不访问 GitHub/npm/apt，不自动补下载，不运行 mihomoctl update 或其 --check。

先只读检查账号、Linux 架构/libc/CPU、基础依赖、systemctl --user、已有程序及 PATH、
代理环境分类、端口和服务状态。检查共享目录是否可信、普通用户是否有篡改权限，
审阅固定软件包清单、SOURCE.txt 和源码。缺包、摘要不符或依赖不满足就报告具体缺项并停止，
不得降级为联网安装。不要把安装器的 check 成功说成运行兼容性已经验证。

使用文档化 offline_install.py check/install，仅安装我选择的软件；不运行 npm install、
npx 下载或包内安装脚本。遇到已有同名程序先保留，说明冲突及备份/迁移方案，不直接删除。
把已审核源码复制到当前用户私有目录，用原 install.sh 安装控制层。写入授权已明确时
继续执行；涉及未授权替换现有程序或尚未选择的个人配置时，先给出具体变更和回滚方案。
不使用 sudo，不修改共享目录、其他用户、系统服务、TUN 或系统代理；Mihomo 不自动启动。
每用户独立端口、服务与认证信息，默认服务保持 disabled；已有状态按原规范审查保留。

订阅和凭据只在个人受限权限文件中处理，不放入聊天、日志、Git、共享包或最终报告。
OpenCode 如需关闭自动更新，只合并个人配置的 autoupdate=false，保留其他设置。
不自动安装插件、LSP、MCP 或扩展。运行期需要的远程资源应单独列为待准备项目。

按文档执行本地版本检查、源码回归测试及验收，保留真实退出码。未允许联网时不进行
模型登录、订阅刷新、代理节点外网探测等网络验收，标记 DEFERRED；未实测兼容性为
UNVERIFIED。Listener readiness 不等于节点连通证据。
最终列出版本/架构/SHA256/本地来源、个人安装路径与 receipt、控制层备份及回滚命令、
服务状态、实际测试结果和剩余步骤。不要声称所有安装包具有独立官方签名验证。
```
