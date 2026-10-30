# 离线准备与传入安装

在联网机器获取完整的 `mihomoctl-1.4.3-portable-linux-x86_64.tar.gz` 和 `.sha256`，通过可信发布记录核验后传入服务器。完整包内置 Python、Textual、全部依赖及固定核心，无需 wheelhouse、venv 或安装系统 Python。

```bash
umask 077
sha256sum --check --strict mihomoctl-1.4.3-portable-linux-x86_64.tar.gz.sha256
tar -xzf mihomoctl-1.4.3-portable-linux-x86_64.tar.gz
cd mihomoctl-1.4.3-portable-linux-x86_64
./install.sh --user
```

已有联网 mihomoctl 可使用 `mihomoctl release fetch --output-dir DIR --target linux-x86_64` 获取最新公开完整包。下面的版本固定示例需在审核、CI 门禁及正式发布完成后，从 [v1.4.3 发布页](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.4.3) 获取已核验的发行资产，不能用候选构建替代。

每人复制到本人私有目录安装。共享存储只作来源，不执行共享可写代码。安装后可删除原始解压目录。随后运行 `mihomoctl`，按终端向导导入订阅并选择节点。获取远程订阅及提供商资源仍需网络；也可导入准备好的本地 YAML。

先前的 Ubuntu/Python wheelhouse 套件仍是旧环境兼容格式，并不包含独立解释器。只保留当前版本和配置，不保留历史备份。

## 旧式 Python 套件兼容路径

以下步骤仅适用于源码与 wheelhouse 套件，需要事先准备匹配的可信系统 Python 和 Mihomo 核心。新的 SSH 用户优先使用上面的完整包。解压前检查归档路径，并通过独立可信记录核验摘要。

```bash
# offline-fetch-layout
umask 077
KIT=/absolute/private/mihomoctl-kit
kit_root="$KIT/kit"
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

```bash
# offline-archive-layout
umask 077
PACKAGES=/absolute/private/packages
bundle=mihomoctl-1.4.3-offline-ubuntu22.04-x86_64-py310
(cd "$PACKAGES" && sha256sum --check --strict "$bundle.tar.gz.sha256") &&
kit_parent=$(mktemp -d "$HOME/mihomoctl-kit.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$PACKAGES/$bundle.tar.gz" -C "$kit_parent" &&
kit_root="$kit_parent/$bundle" &&
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

```bash
# offline-controller-install
umask 077
source_parent=$(mktemp -d "$HOME/mihomoctl-source.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$kit_root/release/mihomoctl-1.4.3.tar.gz" -C "$source_parent" &&
cd "$source_parent/mihomoctl-1.4.3" &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse" --dry-run &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse"
```
