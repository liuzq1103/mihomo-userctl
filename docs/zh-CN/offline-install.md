# 离线安装

联网的 Linux/WSL 机器若已有 1.2.0，可用 `mihomoctl release fetch --output-dir DIR --target ubuntu22.04-x86_64-py310` 取得套件，另支持 `ubuntu24.04-x86_64-py312`。不要求下载机器和目标机器的环境一致。整体传输取得的目录，保留原套件、摘要、门禁证据和相对路径记录；自动校验是传输与一致性检查，不能代替独立签名认证。

在目标机器的私有目录执行（以 1.2.0 为例，KIT 为传入输出目录的绝对路径）：

```bash
umask 077
mkdir "$HOME/mihomoctl-offline-source"
tar -xzf "$KIT/kit/release/mihomoctl-1.2.0.tar.gz" -C "$HOME/mihomoctl-offline-source"
cd "$HOME/mihomoctl-offline-source/mihomoctl-1.2.0"
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$KIT/kit/wheelhouse" --dry-run
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$KIT/kit/wheelhouse"
```

原有低版本请直接运行核验后的新版安装器；不要求旧 CLI 支持 release 或 --latest。目标机器不联网、不执行下载，也不需要下载机器的原绝对路径。

选择匹配目标的完整套件：Ubuntu 22.04 x86_64 Python 3.10，或 Ubuntu 24.04 x86_64 Python 3.12。解包前按独立获取的发行摘要核验外部 .sha256，再核验套件内部 SHA256SUMS。套件含源码、wheel、依赖 wheelhouse 和安装入口。解压到本人拥有的私有目录，不允许符号链接或组/其他用户可写的代码路径。

阅读套件 README.txt，在解压目录执行其 install.sh。安装器检查目标兼容性，并以 --no-index 从 wheelhouse 安装。无需预先展开的公共部署目录。默认仍为用户安装，不启动运行时或服务。保留报告的自包含备份，详见 [INSTALL.md](../../INSTALL.md) 和 [升级回滚](update.md)。离线核心需单独提供已经核验的可执行文件，再显式初始化。
