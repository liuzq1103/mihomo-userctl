# 共享 Node/Codex，独立用户身份与代理

[English](../en/shared-runtime.md) · [交付约定](deployment-contract.md) · [本地安装](offline-install.md)

推荐已由管理员统一维护软件的多用户服务器采用本模式：**共享程序，按 Linux 用户隔离
身份数据和网络配置**。没有公共运行时的个人机器仍可明确选择个人安装模式。在线/本地
只是软件来源，和共享/个人运行时是两个独立选择。

| 层次 | 维护者及边界 |
| --- | --- |
| Node/npm/Codex 公共程序 | 管理员维护固定版本及回滚方案；普通用户只有读取/执行权限 |
| Codex 用户数据与认证 | 各用户自己的 HOME、状态目录、凭据存储及会话，不共享登录身份 |
| Mihomo 与控制层 | 各用户自己的核心、配置、凭据、systemd 用户服务及独立回环端口 |

`/usr/bin/node`、`/usr/bin/npm`、`/usr/bin/codex` 是常见示例，不是必须路径。
也可使用管理员维护的其他目录；记录管理员确认的命令入口、真实目标和版本。由管理员
拥有程序不代表普通用户运行时成为 root；仍须核对实际进程 UID。不能用 sudo 启动 Codex。

## 管理员准备与普通用户安装

管理员单独负责公共运行时安装/升级，使用固定版本，核对来源、摘要、Node 兼容性和
安装方式，保留回滚材料，协调正在使用的会话。本项目的普通用户 Prompt 不执行 apt、
系统 npm 安装、目录 chown/chmod 或公共程序升级；不追随未固定的 latest。
公共程序及其符号链接目标和父目录不得允许普通用户改写，npm 全局目录同样如此。
禁止通过放宽权限或改变全局 npm prefix 来绕过安装权限错误。

普通用户选择共享模式后，只安装缺失的个人 Mihomo 和 mihomo-userctl；Node/Codex 缺失、
版本不满足或权限不可信时，停止依赖该运行时的步骤，报告管理员待办，不偷偷安装个人替代。
OpenCode 如另行选择，独立确认来源与安装范围，不因本模式自动安装。
共享目录中的离线包是分发材料，不是所有人的共同可写运行目录。共享模式默认只需要
Mihomo 包和本项目源码；Node/Codex 包供明确选择个人模式的用户另行准备。

## 路径与 NVM 检查

只读核对命令类型、PATH 顺序、符号链接目标、版本及 npm prefix/root；别回传可能含密钥的
alias/function 定义或完整环境。检查不能仅止于 Codex 入口路径：若启动器使用
`#!/usr/bin/env node`，它会从运行时 PATH 选择 Node，即使 Codex 入口在系统目录。
先查看选定版本的实际启动器，再确定是否有 Node 依赖；独立原生 Codex 包不据此推定依赖 Node。

新登录普通 Shell 和代理子进程都必须解析到已选公共程序，可在完成 PATH 审计后检查：

```bash
type -P node npm codex
node --version
npm --version
codex --version
with_proxy bash --noprofile --norc -c 'command -v node; node --version; command -v npm; npm --version; command -v codex; codex --version'
```

代理子进程检查要求自己的 Mihomo 已就绪。版本输出只证明启动，不等于身份或模型验收。
对于 npm 启动器，进一步核对进程实际 Node 可执行路径及 Codex 包身份；不输出完整参数或密钥。
仅运行 `/usr/bin/codex` 不能保证 `env node` 使用公共 Node。

发现 NVM、个人 standalone/npm Codex 或 PATH 冲突时，先列出当前用户范围内的精确路径和
影响，保留已有安装。只有用户明确选择迁移后，才备份启动配置、记录旧默认值并逐项调整。
若现有 NVM 提供这些命令，可选择 `nvm alias default system`、`nvm use system`、`hash -r`，
但它们会改变当前用户的默认环境，不能自动执行。重新登录复核，并保留恢复旧默认值的方法。
不要删除整个 `.nvm` 或 `.codex`；卸载某份程序还需核对对应安装器、npm prefix 及实际目录，
不得照搬其他服务器笔记中的删除命令。项目级 Node 切换仍可保留，但不能据此宣称共享模式已满足。

## 用户身份与验收

Codex 状态目录默认是 `~/.codex`；`CODEX_HOME` 可覆盖它。核对当前用户的实际 HOME 和
有效状态路径及权限，不改写它们来复用他人身份。登录凭据也可能存于用户的系统凭据存储，
不能以没有 `auth.json` 判断未登录。依据[官方认证说明](https://learn.chatgpt.com/docs/auth)及
[环境变量说明](https://learn.chatgpt.com/docs/config-file/environment-variables)核对已选版本。
禁止共享凭据文件、密钥、会话目录或把状态目录链接到公共目录；只检查自己，保留既有状态。
用户通过自己的认证完成登录，需要代理时从 `with_proxy codex` 进入；不把令牌或登录码发到聊天。

最终报告增加公共命令/真实目标/版本、普通与代理 Shell 的解析结果、npm prefix/root、
Node 实际解释器（适用时）、当前 UID、私有状态路径、迁移前后默认值及回滚方式。
仍按[验收规范](acceptance.md)分别证明 Listener、代理出站和模型请求；程序共享不等于
账号共享，也不单凭程序路径或不同端口声称完整隔离。管理员/root 不在普通用户隔离威胁边界内。

## Remote hook 与长期 app-server

本项目 `src/shell.bash` 加载时先执行 `proxy_off`；远程启动器提供非空
`CODEX_REMOTE_PAYLOAD` 时才调用 `proxy_on`，就绪失败则退出。它是本地验证的兼容 hook，
不是公开稳定的 Codex API，不能假定所有 Remote、code-mode 或 VS Code 启动路径都有它。
实际 Shell 是否加载托管 loader 必须验证；禁止在启动文件或全局环境中持久设置该变量。

区分普通 Shell 默认不注入、终端 `with_proxy`/`mihomoctl exec` 显式注入、经验证 Remote
路径通过 hook 注入。Mihomo 规则在流量进入后决定出口，不透明截获普通进程。
VS Code Extension Host 仍遵循[独立集成指南](vscode-remote.md)。

某些版本/启动方式可出现以下链路，必须实测，不能推广为所有用户的默认行为：

```text
CLI（可能无代理变量）→ 当前用户 Unix socket → 长期 app-server
  → 当前用户 Mihomo Listener → 规则 → 实际出站
```

CLI `0/8` 不证明模型请求直连；CLI `8/8` 也不证明旧服务已代理。`mihomoctl direct`
同样只控制新子进程环境，不能把复用的旧服务变成直连。公共程序升级/PATH 修正不会替换
已运行服务的版本或环境。记录实际出站进程，而不只记录新 CLI。

按[排障流程](troubleshooting.md)关联 CLI、桥接进程（若有）和 app-server 的 UID/PID、
运行身份、启动时间、环境分类、Unix socket、Listener 连接、同一请求时段/目标与脱敏路由证据。
当前 diagnose 不自动证明 Unix 对端或完整因果链。socket 路径随版本/状态目录变化；
PPID=1、`8/8` 或节点日志单独都不能证明 hook 来源或 CLI 关联。空闲时无连接不等于失败，
证据不足记 UNVERIFIED。只输出脱敏分类，不回传完整参数、环境或日志。
重连/重启需先协调当前用户的会话，不自动 kill 或删除 socket/私有状态。新用户仍需自己的
授权启动与登录验收，不能因另一用户 plain codex 可用就认定无需代理接入。
