# 从共享目录安装（课题组部署）

[English](../en/offline-install.md) · [本地安装 Prompt](agent-local-install-prompt.md) · [公开在线安装](setup.md)

适用于维护者提前下载、普通用户从 Ubuntu 共享目录安装的场景。公开仓库仍以官方在线
来源为默认入口；此流程是可选部署方式，不写死服务器路径，也不向 Git 提交安装包。
下文的 `PUBLIC` 必须替换为实际共享目录。共享的是程序包，不是账号、订阅或配置。

管理员已提供公共 Node/npm/Codex 时采用[共享运行时模式](shared-runtime.md)：普通用户
默认只取 Mihomo 包和本项目源码，不重复下载/安装 Node 或 Codex。下表仍保留个人模式的
可选包；公共依赖缺失应交管理员处理，不能自动切换个人安装。

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
| mihomo-userctl 源码 | [v0.3.3 ZIP（架构通用）](https://github.com/liuzq1103/mihomo-userctl/archive/refs/tags/v0.3.3.zip) | 同左 |

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
记录归档 SHA256 和来源，再解压为下面的 `source/`。自算摘要只用于传输一致性。
v0.3.3 包含离线入口、清单及双语文档，直接从同一份审核后的源码复制即可。
Ubuntu 22.04 x86_64 服务器使用表中 x86_64 一列；不要根据下载电脑的 Windows 架构
选择 Windows 包。安装前仍需检查目标服务器的基础依赖和实际运行兼容性。

## 维护者准备共享目录

建议结构（包保留原文件名）：

```text
PUBLIC/mihomo-offline/
  offline_install.py       # 本项目 scripts/offline_install.py
  offline-packages.json    # 本项目 examples/offline-packages.json
  docs/                   # 本次审阅的双语文档
  source/                 # 已核对的完整 mihomo-userctl 源码
  SOURCE.txt              # 标签、完整 commit、归档 SHA256、审阅记录
  packages/               # 当前架构的上述四个包，按需选择
```

由维护者维护目录及其父目录权限，普通使用者只读，不能让任意用户修改包、清单或脚本。
不要使用 `chmod -R 777`。安装器不会修改共享目录。每次更新发布新的版本目录，不要
覆盖仍被其他人使用的材料。保留许可证与上游来源，不向共享目录放任何密钥。

在目标 Ubuntu 账号中检查已选包；仅装 Mihomo 就只写 `--packages mihomo`：

```bash
PUBLIC='/replace/with/shared/public'
BUNDLE="$PUBLIC/mihomo-offline"
python3 "$BUNDLE/offline_install.py" check \
  --bundle-dir "$BUNDLE/packages" --manifest "$BUNDLE/offline-packages.json" \
  --packages mihomo
```

`check` 只读校验文件与摘要，不执行程序、不解压、不声称兼容性已验证。缺包、摘要不符、
架构未覆盖均以退出码 2 停止。无需联网获取官方摘要，使用事先审核的清单。

## 各用户本地安装

需要已具备 Python 3.8+（含 gzip、tarfile、lzma 标准库）。完整代理环境还需原
[安装指南](setup.md)中的 Bash、systemd 用户管理器、curl、ss 等基础工具；本入口不运行
apt，不会安装系统依赖。基础工具缺失时由管理员另行准备匹配 Ubuntu 版本的离线包。

```bash
python3 "$BUNDLE/offline_install.py" install \
  --bundle-dir "$BUNDLE/packages" --manifest "$BUNDLE/offline-packages.json" \
  --packages mihomo
export PATH="$HOME/.local/bin:$PATH"
```

程序先复制到私有目录再校验、限制大小并安全解压；全部成功后创建 `~/.local/bin` 链接。
实际文件位于 `~/.local/share/mihomo-userctl-offline/install-*/`，生成 `receipt.json` 记录
版本、摘要及每个链接目标。不会执行包内脚本、运行 npm、启动 Mihomo 或修改 Shell 配置。
失败时回收本次临时文件和已创建链接。已有同名命令（含失效链接）则停止并保留原样；
因此重复安装不会覆盖既有环境。其他 PATH 位置可能还有同名程序，需检查 `type -a`。

随后将 `source/` 复制到当前用户私有工作目录，按原安装指南配置个人 Mihomo、服务及
凭据；跳过其中的 GitHub 下载/克隆步骤，使用已验证的本地材料。在源码目录运行原
`install.sh --suggest-port`，确认专属端口后执行 `bash install.sh --port "$PORT"`。
`PORT` 必须是已确认的实际端口。原安装器承担控制层备份、事务和回滚，不另造一套。
普通用户不得在共享源码中运行会写文件的检查或安装操作。

安装后逐项运行并记录退出码：`mihomo -v`、`node --version`、`npm --version`、
`codex --version`、`opencode --version`；检查实际选择的软件，包括复用的公共运行时。
个人模式需额外工具时才显式扩展 `--packages`；不要在共享模式追加 node/codex。还需运行源码的测试
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
