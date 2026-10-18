# 本地与严格离线安装

本地包不一定要求目标断网。完整新装包括控制器、核心与初始化；默认不启动。发行源码包和 offline 控制层套件都**不含 Mihomo 核心**。严格离线前请准备架构匹配、已经核验的核心；只有本地控制层包且允许联网时，可在安装后按 [初始化教程](setup.md) 显式下载固定核心。交给 Agent 可复制 [本地安装 prompt](agent-local-install-prompt.md)。

## 先检查材料和目标

完整依赖套件支持 Ubuntu 22.04 x86_64 / Python 3.10 和 Ubuntu 24.04 x86_64 / Python 3.12，不跨目标强装。先检查已有 manager；保留其核心和配置，不重复初始化。严格离线缺核心或依赖时，在写入安装前列出缺项。

NAS 例如 `/mnt/nas/public/software` 只作来源。设置 `umask 077`，把所需包、摘要、证据与整个 wheelhouse 复制到 HOME 下本人拥有的私有目录，再核验使用；不要执行共享可写目录中的安装器或修改 NAS 权限。代码及父目录必须满足安装器信任要求。外层摘要应与独立可信发行记录比较；同目录摘要、receipt 和 gate 是一致性证据，不是独立签名。解包前检查归档条目，拒绝绝对路径、路径穿越、符号/硬链接和特殊文件，使用全新私有目标目录。以下命令均以材料已核验为前提。

## 路径一：release fetch 的完整输出目录

联网 Linux/WSL 上已有 1.2.0 时可执行：

```bash
mihomoctl release fetch --output-dir "$HOME/releases/mihomoctl-kit" --target ubuntu22.04-x86_64-py310
```

另支持 `ubuntu24.04-x86_64-py312`。下载机器无需与目标一致。整体传输输出目录，保留原套件、摘要、门禁证据和 acquisition.json 相对路径；不要只复制源码包。

目标机器上，KIT 是已复制到私有位置的完整输出目录。fetch 已展开内层 kit，无需再展开原外层套件：

```bash
# offline-fetch-layout
umask 077
KIT=/absolute/private/mihomoctl-kit
kit_root="$KIT/kit"
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

## 路径二：直接取得 offline tarball

只有 `mihomoctl-1.2.0-offline-TARGET.tar.gz` 和其 `.sha256` 时，需要先展开外层。下面以 Ubuntu 22.04 目标为例，替换 PACKAGES 为私有副本所在目录：

```bash
# offline-archive-layout
umask 077
PACKAGES=/absolute/private/packages
bundle=mihomoctl-1.2.0-offline-ubuntu22.04-x86_64-py310
(cd "$PACKAGES" && sha256sum --check --strict "$bundle.tar.gz.sha256") &&
kit_parent=$(mktemp -d "$HOME/mihomoctl-kit.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$PACKAGES/$bundle.tar.gz" -C "$kit_parent" &&
kit_root="$kit_parent/$bundle" &&
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

如果任一步失败，停止，不能继续安装。上述摘要比较不替代解包前对独立可信摘要及归档条目的审阅。

## 从已核验的 kit 安装控制器

两种路径现在都得到真实的 `kit_root`。先阅读该目录的 README.txt，并复核 build-receipt.json、bundle-manifest.json 和随附门禁证据；然后展开其中的源码包。选择与目标匹配的 Python，示例为 `/usr/bin/python3`：

```bash
# offline-controller-install
umask 077
source_parent=$(mktemp -d "$HOME/mihomoctl-source.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$kit_root/release/mihomoctl-1.2.0.tar.gz" -C "$source_parent" &&
cd "$source_parent/mihomoctl-1.2.0" &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse" --dry-run &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse"
```

安装器用 `--no-index` 读取本地 wheelhouse，不下载依赖、不启动服务。使用核验后的新版安装器升级旧版，不依赖旧 CLI 的 release 或 --latest。只有普通源码包时，没有完整依赖，需另行提供可信 wheelhouse 或已满足依赖的 Python 环境。

## 完成核心与初始化

安装后仅在当前终端设置 PATH；严格离线时同时禁止无关后台更新查询：

```bash
export PATH="$HOME/.local/bin:$PATH"
export MIHOMOCTL_NO_UPDATE_CHECK=1
mihomoctl version
/usr/bin/python3 "$source_parent/mihomoctl-1.2.0/scripts/bootstrap.py" verify --user
```

verify 使用上面安装时选定的解释器。没有 manager 时，使用预先准备的可信核心，按 [初始化教程](setup.md) 只 init 一次，并执行 config validate；已有 manager 则保留，不重新安装核心。默认保持停止；分别记录控制器、核心、初始化结果，运行态和远端代理仍为 UNVERIFIED。保留安装器报告的自包含备份及工作目录，见 [升级回滚](update.md)。恢复控制器代码不会删除新初始化的数据。
