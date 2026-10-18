# 本地安装包：交给 Agent 的完整安装 prompt

[English](../en/agent-local-install-prompt.md) · [安装与初始化](setup.md) · [离线包布局](offline-install.md)

适用于 OpenCode、Codex 等能执行 Linux 命令的 Agent。默认完成控制器、核心与初始化，不启动；`install.sh` 自身仍只安装控制器。下面整段可直接复制，按需修改来源目录。“本地包”允许随后显式下载核心；要求全程断网时，在 prompt 中明确“严格离线”。

```text
请实际安装并验收 mihomoctl，安装包默认在 /mnt/nas/public/software。
默认完成：控制器与依赖、可信 Mihomo 核心、初始化、配置验证。默认不启动运行时。

1. 先只读检查当前用户、HOME/XDG 路径、Linux 发行版、架构、Python 3.10+、Bash、已有 mihomoctl、manager 和可信核心；不要打印凭据。使用当前普通用户的 --user 作用域；若当前为 root 且未指定目标普通用户，先询问安装用户。
   开始前列出包版本、格式、目标环境与网络条件。读取包内 INSTALL.md、setup.md 和 offline-install.md。不要将本地来源等同于严格离线。

2. 检查来源目录中的源码包、完整 offline 套件、摘要、receipt/gate 和依赖。使用 umask 077，在 HOME 下创建本人拥有的 700 私有工作目录，将所需整套材料（包括 wheelhouse）复制进去，后续不引用共享可写的 NAS 代码或依赖。不修改、删除或递归 chmod NAS。
   解包前核验外层摘要，检查归档路径、类型和链接，拒绝路径穿越与可疑条目；解包后核验内部 SHA256SUMS、发行一致性及目标兼容性。相邻摘要不是独立发布者认证。校验失败即停，不绕过信任或版本门禁。
   区分 release fetch 的完整输出目录和直接下载的 offline tarball，按 offline-install.md 展开到真实路径。源码及其父目录须符合安装器所有权和权限要求。

3. 在修改安装前确认核心路径：已有 manager 时保留并审阅，不重复 init、不主动 core install；缺失或损坏的配置核心先报告修复阻塞，不擅自激活替代核心，因为 core install 可能重启已有运行时。
   没有 manager 时优先复用已核验、架构匹配且权限安全的现有核心。没有可信核心且允许联网时，x86_64 默认显式执行 mihomoctl core install --version v1.19.32，使用包内维护的对应摘要，无需询问版本；这是固定测试版本，不是“最新版本”。其他架构没有对应内置摘要时，提前请求可信本地核心或经核验的对应资产 SHA256，不跨架构强装。
   严格离线且缺核心/依赖时，在安装前列出缺项，不能以仅安装控制器宣称完整成功。初始下载使用可用直连或已有可信代理；不能依赖尚未启动的自身 mihomoctl exec。

4. 按匹配套件 README 和安装器帮助，先 --dry-run，再用相同参数去掉 --dry-run 安装。显式使用 --user、正确的 --python 和本地 --wheelhouse；只有源码包时可复用可信且满足依赖的 Python 环境，缺依赖就报告，不擅自修改系统 Python 或使用 sudo。
   旧版直接使用核验后的新版安装器升级，保留配置、凭据、订阅、缓存和核心，记录备份路径。不要调用旧 updater 或添加版本垫片。不改 Shell 启动文件，只临时设置 PATH。安装期间设置 MIHOMOCTL_NO_UPDATE_CHECK=1，避免无关后台查询。

5. 控制器安装通过后，执行第 3 步选定的核心准备操作。没有 manager 时只初始化一次：mihomoctl init --core /可信核心绝对路径；若明确提供配置，则在同一次 init 中传 --config。随后执行 mihomoctl config validate。core install 保存路径以命令结果为准，默认 XDG 路径为 ${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo。
   不自动 start/restart、导入订阅、操作第三方服务、启用 systemd 或 TUN。不要把默认 MATCH,DIRECT 说成远端代理已经可用。

6. 从源码目录之外运行已安装启动器的 version、--help，并用安装时选定的 Python 通过绝对路径执行 /发行源码绝对路径/scripts/bootstrap.py verify --user。分别报告控制器安装、核心版本、初始化/配置验证的 PASS/FAIL/UNVERIFIED；默认未启动，运行态健康和真实远端代理记为 UNVERIFIED，不因此判定安装失败。
   给出版本、安装用户、启动器/Python/核心路径、核验结果、备份路径及可执行的回滚命令。保留自包含备份；不要把卸载控制器当作清除初始化数据的回滚。说明新建数据及其位置，不删除既有数据。
   最后给出临时 PATH、后续显式 start、订阅/规则和真实客户端验证入口。只为缺失输入或超出授权范围的操作询问，不在结束时才让用户选择已有默认的核心版本。输出脱敏。
```

验收标准与代理安装器的环境继承见 [首次运行](first-run.md)。严格离线准备见 [离线安装](offline-install.md)，升级备份恢复见 [升级与回滚](update.md)。
