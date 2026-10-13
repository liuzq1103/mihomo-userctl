# V1 完整离线安装

[English](../en/offline-install.md) · [安装契约](../../INSTALL.md) · [本地安装 Prompt](agent-local-install-prompt.md)

适用于 1.0.2 及之后采用相同交付格式的发布；不要混用旧源码、旧参数和新文档。
完整离线套件仅含 mihomoctl 控制层、源码、项目 wheel 和 Python 依赖。
**Mihomo、OpenCode、Codex、Node 需要用户自行准备或安装**，不在套件内。

## 核对目标与来源

| 目标标识 | 系统 | 解释器 | 架构 |
| --- | --- | --- | --- |
| ubuntu22.04-x86_64-py310 | Ubuntu 22.04 | CPython 3.10 | x86_64 |
| ubuntu24.04-x86_64-py312 | Ubuntu 24.04 | CPython 3.12 | x86_64 |

先只读运行 `uname -m`、`cat /etc/os-release`、`/usr/bin/python3 --version`。
即使 `which python` 指向 Anaconda，安装器仍优先使用 `/usr/bin/python3`。
例如系统解释器 3.10.12、PyYAML 5.4.1 不满足 `PyYAML>=6.0.1`，即使导入成功也不能通过
依赖预检。使用匹配的 wheelhouse 即可：依赖解压到 mihomoctl 自己的安装世代，
不升级系统或 Anaconda 内的 PyYAML。

维护者交付 `mihomoctl-VERSION-offline-TARGET.tar.gz` 和相邻 `.tar.gz.sha256`。
**预期摘要、精确版本和完整 commit 必须来自你信任、且不能与共享包一同被篡改的渠道**，
例如另行核对的维护者发布记录。普通源码归档的 `SHA256SUMS` 是发布附件，不要求归档包含
自身摘要；完整离线套件则另有内部 `SHA256SUMS`。

共享目录只存包。0777、当前账号可写或可写挂载不能独立证明来源；复制前后摘要一致、包内
receipt 和包旁的校验文件也不能提供独立来源证明。缺可信外部摘要时记录 `UNVERIFIED`
并停止，不现场自算后宣布验证通过，不修改公共目录内容或权限。

## 先校验，再解压

以下只用系统工具；将路径和摘要替换成已确认的材料：

```bash
ARCHIVE='/absolute/shared/mihomoctl-1.0.2-offline-ubuntu22.04-x86_64-py310.tar.gz'
EXPECTED_SHA256='<从独立可信渠道取得的64位摘要>'
WORK=$(mktemp -d "$HOME/mihomoctl-offline.XXXXXX")
chmod 700 "$WORK"
cp -- "$ARCHIVE" "$WORK/"
ARCHIVE="$WORK/$(basename "$ARCHIVE")"
printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum --check --strict
DEST="$WORK/unpacked"
```

任何失败即停止。运行[英文页中的 Python 标准库受限解压代码](../en/offline-install.md#verify-then-safely-extract)，
参数为上面的 `ARCHIVE` 和 `DEST`；该代码不执行收到的项目脚本，拒绝链接、特殊文件、绝对路径、
`..`、重复成员和多个根目录，限制 20000 项、512 MiB 及实际写入量。输出目录必须尚不存在。

确认唯一套件根目录，再执行：

```bash
KIT="$WORK/unpacked/mihomoctl-1.0.2-offline-ubuntu22.04-x86_64-py310"
cd "$KIT"
sha256sum --check --strict SHA256SUMS
cd release
sha256sum --check --strict SHA256SUMS
ARCHIVE="$KIT/release/mihomoctl-1.0.2.tar.gz"
DEST="$WORK/source"
```

阅读套件根目录 `bundle-manifest.json` 和 `release/build-receipt.json`，将版本、commit、目标
与可信记录核对。以上述新参数再次运行标准库受限解压代码，解压源码。
审阅同版本 INSTALL、源码和仓库约束；交付包不得含 `.pyc`、`.pyo`、`__pycache__` 或未审核文件。
静态核对 manifest、pyproject、Python `__version__`、install.sh `VERSION=`、
src/common.bash `MIHOMO_USERCTL_VERSION` 五处一致，再运行项目脚本。

## 安装控制层

```bash
cd "$WORK/source/mihomoctl-1.0.2"
bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse" --dry-run
bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse"
"$HOME/.local/bin/mihomoctl" version
/usr/bin/python3 -I scripts/bootstrap.py verify
```

dry-run 与安装共用版本、依赖及 wheel 兼容性预检。缺包、摘要不符、目标不符或依赖版本
不满足均停止，不运行 apt/npm/pip 联网补齐。仅当所选解释器的依赖版本和导入检查都满足
声明时可省略 wheelhouse。不使用 sudo；系统安装另按 INSTALL 的显式 `--system` 流程。

安装器不改 `.bashrc`，不注册 `proxy_on`、`proxy_status`、`with_proxy` 或 hook，不启动/停止
服务，不接管或替换已有 Mihomo 核心。默认用户作用域、process 后端，控制层位于
`~/.local/share/mihomoctl/install`。端口由后续显式 `mihomoctl init --port PORT` 和命名
listener profile 决定。0.x 迁移先检查 `mihomoctl migrate --dry-run`，明确选择后再 `--apply`。
代理通过显式 `mihomoctl exec` / `env` / `integration` 使用。
未授权时不为验收启动服务、刷新订阅或进行模型请求；缺外网验收记 `UNVERIFIED`。
按[交付约定](deployment-contract.md)报告真实版本、来源、路径、备份/回滚命令及测试结果，
不回传凭据或订阅链接。

## 维护者备包

只在匹配目标的联网构建环境准备依赖，离线安装目标机不运行下载步骤：

```bash
python3 scripts/build_release.py --output dist
python3 -m pip download --only-binary=:all: --require-hashes \
  -r requirements-lock.txt -d /absolute/path/to/wheelhouse
python3 scripts/build_offline_bundle.py --artifacts dist \
  --wheelhouse /absolute/path/to/wheelhouse \
  --target ubuntu22.04-x86_64-py310 --output dist
```

Ubuntu 24.04 使用对应目标。构建器只消费本地材料，核对锁定摘要并拒绝覆盖已有套件。
发布校验 `scripts/verify_release.py --offline-artifacts DIR` 读取两个目标的套件和外部摘要；
省略该参数时从普通发布产物目录读取。完整发布还须通过两平台实际断网安装、更新、回滚及
既有发布门禁；开发 `--worktree` 套件不可发布，测试未运行不得标为 PASS。
