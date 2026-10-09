# 固定链接安装

[中文首页](../../README.md) · [English](../en/quick-install.md)

```bash
curl -fsSL https://raw.githubusercontent.com/liuzq1103/mihomo-userctl/main/bootstrap.py -o mihomo-userctl-bootstrap.py && python3 mihomo-userctl-bootstrap.py
```

脚本先完整下载到当前目录，再运行。仅安装已发布版本，不把开发快照当作正式发布版。
不依赖 Coding Agent，默认使用最新稳定 GitHub Release；指定版本和预览方式：

```bash
python3 mihomo-userctl-bootstrap.py --version vX.Y.Z --dry-run
python3 mihomo-userctl-bootstrap.py --version vX.Y.Z --port YOUR_PROXY_PORT
```

`vX.Y.Z` 替换成实际已发布标签，`YOUR_PROXY_PORT` 替换成空闲数字端口。
首次安装省略端口时调用发布包内的 `install.sh --suggest-port`，再显式传给安装器。
已有安装保留原端口与安装路径约定。预览仍会下载发布包，但不安装控制层。

它只安装 **mihomo-userctl 控制层**：不会替你准备订阅、Mihomo 核心、配置和用户服务；
已有私有配置和核心时会自动补齐本机控制器；缺少时提示之后在 TUI 初始化。
不会自动启动或重启服务、修改全局代理或提权。首次完整部署继续看[安装指南](setup.md)，
已有本地软件包看[离线安装](offline-install.md)，已有实例看[节点与面板](control-plane.md)。
依赖和授权要求不因快捷入口改变。已安装用户升级优先使用[原有更新命令](update.md)。

安全边界：bootstrap 链接使用 main，信任 GitHub HTTPS 与本仓库维护者；执行前可检查下载的脚本。
它只接受正式稳定 Release，将 tag 解析到不可变 commit，再下载该 commit 的源码包。
拒绝越界 ZIP、符号链接、异常体积和版本不匹配，记录源码 SHA256 与发布来源。
该 SHA256 是下载内容记录，**不是独立签名验证**；不会声称供应链已完全证明可信。
网络请求可以使用调用者已有代理，但不会打印代理值或把服务端错误正文回显到终端。
不要在命令行、聊天或 URL 中传订阅与密钥。
