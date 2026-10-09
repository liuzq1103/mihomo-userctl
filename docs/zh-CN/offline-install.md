# 从共享目录安装（课题组部署）

本页以 v0.7.0 正式发布包为例；部署时固定版本并核对来源。

[English](../en/offline-install.md) · [本地安装 Prompt](agent-local-install-prompt.md) · [公开在线安装](setup.md)

适用于维护者提前下载、普通用户从 Ubuntu 共享目录安装的场景。公开仓库仍以官方在线
来源为默认入口；此流程是可选部署方式，不写死服务器路径，也不向 Git 提交安装包。
下文的 `PUBLIC` 必须替换为实际共享目录。共享的是程序包，不是账号、订阅或配置。

默认安装个人 Mihomo 和控制层，优先复用已有适用软件；Codex、Node、OpenCode 按需选择。
公共目录只是存包位置，不是公共 mihomoctl 或运行目录。仅明确选择管理员公共 Node/npm/Codex
时才采用[共享运行时模式](shared-runtime.md)，不能由存包位置推断该模式。

## 下载清单

先在服务器运行 `uname -m`、`ldd --version`，再在联网电脑下载。`x86_64` 选 x64，
`aarch64` 选 arm64；不需要把两种架构全部下载。以下为 2026-09-24 核对的固定版本，
不是自动追踪最新版。安装器按运行机器架构选择，不会下载缺失的软件。

| 软件 | x86_64 下载 | aarch64 下载 |
| --- | --- | --- |
| Mihomo 1.19.31 | [amd64 compatible .gz](https://github.com/MetaCubeX/mihomo/releases/download/v1.19.31/mihomo-linux-amd64-compatible-v1.19.31.gz) | [arm64 .gz](https://github.com/MetaCubeX/mihomo/releases/download/v1.19.31/mihomo-linux-arm64-v1.19.31.gz) |
| Codex CLI 0.156.1 | [x86_64 musl .tar.gz](https://github.com/openai/codex/releases/download/rust-v0.156.1/codex-x86_64-unknown-linux-musl.tar.gz) | [aarch64 musl .tar.gz](https://github.com/openai/codex/releases/download/rust-v0.156.1/codex-aarch64-unknown-linux-musl.tar.gz) |
| OpenCode 1.18.32 | [x64 baseline .tar.gz](https://github.com/anomalyco/opencode/releases/download/v1.18.32/opencode-linux-x64-baseline.tar.gz) | [arm64 .tar.gz](https://github.com/anomalyco/opencode/releases/download/v1.18.32/opencode-linux-arm64.tar.gz) |
| Node.js 24.21.0 LTS（含 npm/npx） | [x64 .tar.xz](https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-x64.tar.xz) | [arm64 .tar.xz](https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-arm64.tar.xz) |
| mihomo-userctl 源码 | [v0.7.0 ZIP（架构通用）](https://github.com/liuzq1103/mihomo-userctl/archive/refs/tags/v0.7.0.zip) | 同左 |

Mihomo 和本项目构成代理控制环境；Codex、OpenCode、Node 均为可选工具。选用独立
Codex/OpenCode 程序包，无需通过 npm 安装它们。Node 为其他 JS 工具准备，不是
`mihomo-userctl` 的依赖。不要下载 Windows/macOS 包、OpenCode Desktop 包或只有
安装脚本的文件。Node 包中的 npm/npx 不意味着任意 npm 项目依赖也已经离线备齐。

固定摘要位于 [软件包清单](../../examples/offline-packages.json)。Mihomo、Codex、OpenCode
摘要来自对应官方 GitHub Release API 的资产 `digest`，Node 来自该版本官方
[SHASUMS256.txt](https://nodejs.org/dist/v24.21.0/SHASUMS256.txt)。清单保留下载和摘要来源 URL。
这是通过 HTTPS 获取的发布元数据，不等于独立签名验证。使用者必须信任维护者提供的
清单；软件包和清单同时被篡改时，单纯 SHA256 无法证明来源。

源码 ZIP 没有在这份二进制清单中：维护者应在联网电脑核对标签对应 commit、审阅源码，
提供可核对的版本/commit 与来源记录；记录归档 SHA256。记录可随交付说明提供，
不要求单独的 `SOURCE.txt`。自算摘要只用于传输一致性，无法确认来源时应停止并报告。
v0.7.0 包含离线入口、清单及双语文档，直接从同一份审核后的源码复制即可。
Ubuntu 22.04 x86_64 服务器使用表中 x86_64 一列；不要根据下载电脑的 Windows 架构
选择 Windows 包。安装前仍需检查目标服务器的基础依赖和实际运行兼容性。

## 公共目录存包，个人目录解压

目录可以直接平铺项目源码 ZIP 和所选依赖包，保留依赖包原文件名。例如：

```text
/mnt/nas/public/software/
  mihomo-userctl-0.7.0.zip
  mihomo-linux-amd64-compatible-v1.19.31.gz
  ...其他已选择且匹配目标架构的依赖包
```

不要求预先解压，不要求 `source/`、`packages/`、外置安装脚本或文档副本。
审查目录及父目录权限和材料来源；不更改公共文件或权限，不在公共目录执行安装/测试。
多个源码 ZIP 无法唯一确定时先确认版本，不自动选择最新文件。依赖版本须匹配该源码内清单。

在当前用户下创建权限 700 的新工作目录，将确定的源码 ZIP 复制进去，比较复制前后的
SHA256 并保存来源记录。解压前逐项检查：拒绝绝对路径、`..`、反斜线/盘符路径、符号链接、
重复成员及文件/目录冲突；最多 100000 项、总解压大小最多 2 GiB，解压时同样限制实际写入量。
仅解压到新建的空私有目录，不覆盖已有文件；确认归档只有一个项目根目录。
这些检查应使用目标机已具备的归档工具或 Python 标准库完成，不运行未审阅的包内代码。
阅读解压后的同版本文档和仓库约束，核对 release-manifest.json、install.sh 和 src/common.bash
版本一致且符合选定版本，再运行项目脚本。ZIP 文件名不能单独证明发布身份。

## 各用户本地安装

需要 Python 3.8+（含 gzip、tarfile、lzma）及[安装指南](setup.md)中的 Bash、systemd 用户
管理器、curl、ss 等基础工具。缺失基础工具时报告管理员准备，不运行 apt 或自动联网补包。
以下命令从已审核的个人源码目录执行；`PUBLIC` 替换为实际存包目录。

```bash
PUBLIC='/mnt/nas/public/software'  # 示例；替换为实际安装包目录
python3 scripts/offline_install.py check \
  --bundle-dir "$PUBLIC" --manifest examples/offline-packages.json \
  --packages mihomo
python3 scripts/offline_install.py install \
  --bundle-dir "$PUBLIC" --manifest examples/offline-packages.json \
  --packages mihomo
export PATH="$HOME/.local/bin:$PATH"
```

默认只安装缺失的 Mihomo；已存在且适用则跳过该安装，其他已选缺失软件按需加入
`--packages`（例如 `mihomo codex`）。`check` 只读检查文件及摘要，不解压或执行程序，
不证明运行兼容性。缺包、摘要不符或架构未覆盖时退出码为 2；不联网补包。

程序先复制到私有目录再校验、限制大小并安全解压；全部成功后创建 `~/.local/bin` 链接。
实际文件位于 `~/.local/share/mihomo-userctl-offline/install-*/`，生成 `receipt.json` 记录
版本、摘要及每个链接目标。不会执行包内脚本、运行 npm、启动 Mihomo 或修改 Shell 配置。
失败时回收本次临时文件和已创建链接。已有同名命令（含失效链接）则停止并保留原样；
因此重复安装不会覆盖既有环境。其他 PATH 位置可能还有同名程序，需检查 `type -a`。

随后在上述个人源码目录按原安装指南配置个人 Mihomo、服务及
凭据；跳过其中的 GitHub 下载/克隆步骤，使用已验证的本地材料。在源码目录运行原
`install.sh --suggest-port`，确认专属端口后执行 `bash install.sh --port "$PORT"`。
`PORT` 必须是已确认的实际端口。原安装器承担控制层备份、事务和回滚，不另造一套。
普通用户不得在共享源码中运行会写文件的检查或安装操作。

安装后逐项运行并记录退出码：`mihomo -v`、`node --version`、`npm --version`、
`codex --version`、`opencode --version`；检查实际选择的软件，包括复用的公共运行时。
仅检查实际选择或复用的软件，不把未选工具缺失当作失败。还需运行源码的测试
和原验收脚本。glibc、CPU 指令集和动态库兼容性必须以目标机器实际结果为准；版本命令
成功也不等于模型调用或代理节点已经验收。新包尚未在目标服务器运行时应标为 UNVERIFIED。

## 更新、撤销和联网边界

离线工具不实现原位升级，不停止已运行进程。换版本前先审查 receipt 和同名命令，
备份当前链接/文件并协调运行中进程，再解除需要替换的个人链接后安装新包。
撤销本次工具安装时，只删除仍指向该 receipt 所记录目标的链接；确认不再需要后删除
对应的单个 `install-*` 目录。不要删除整个 `~/.local/bin` 或其他用户目录。
控制层使用原安装器记录的独立备份/回滚命令。

`mihomoctl update`（包括 `--check`）仍是 GitHub 在线更新功能，本地安装 Prompt 不运行它。
离线刷新控制层应审查新的源码快照，沿用 `install.sh` 的重新安装与回滚流程，并单独核对
来源记录。Node/Codex/OpenCode 不归 `mihomoctl update` 管理。

安装入口本身不发起网络访问，也不执行下载的程序。程序运行后的登录、模型 API、订阅、
规则/provider 更新仍可能联网；离线安装不承诺离线使用。OpenCode 的插件、LSP 或自动更新
也可能触发下载：课题组环境应按其[官方配置文档](https://opencode.ai/docs/config/#autoupdate)
在个人配置中合并 `"autoupdate": false`，按需预备插件与缓存，不能覆盖已有个人配置。
Mihomo 配置如引用远程规则或 Geo 数据，维护者需要另行备齐与所选配置匹配的数据；
私人订阅只在个人目录中导入。验收时把本地检查与需用户授权联网的端到端检查分开报告，
按[安装参数与交付约定](deployment-contract.md)处理软件复用、启动授权和 Codex 分层证据。
<!-- Core compatibility: package integrity and runtime capabilities are independent. -->

文中的核心版本是已验证示例，不是精确版本限制。可复用已有 Mihomo，或用自定义离线清单指定其他版本的文件、架构和可信 SHA256。哈希校验仍必需；运行兼容性以配置校验和实际 API 能力为准。
