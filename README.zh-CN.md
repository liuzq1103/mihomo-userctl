# mihomo-userctl

`mihomo-userctl` 是面向 Linux 共享服务器的 Mihomo 用户级控制器和 Bash
集成层。它不替代 Mihomo，也不接管订阅或节点；它解决的是“怎样安全、清晰地
启动服务，以及怎样只让明确选择的 Shell 或命令使用代理”。

> 本项目是独立、非官方项目，与 MetaCubeX、Mihomo 和 Mihoro 均无隶属关系。

[English](README.md)

## 核心原则

```text
普通登录 / 新 Shell / axel / 大文件下载
                    │
                    └── 默认服务器直连

with_proxy command / proxy_on / Codex 专用启动环境
                    │
                    └── 认证的 127.0.0.1:<用户端口> → Mihomo
```

启动 Mihomo 服务不等于开启当前 Shell 代理。代理环境和服务生命周期是两个
明确分离的状态：

- `mihomoctl start` 只启动服务；
- `proxy_on` 只改变当前 Shell；
- `with_proxy` 只改变一个子 Shell；
- `proxy_off` 不停止服务；
- 普通新 Shell 总是先清空代理变量。

## 适用条件

- Linux、Bash 5 或更高版本；
- 可用的 `systemd --user`；
- 已存在的 `mihomo.service`；
- Mihomo 只在 `127.0.0.1` 创建带认证的 Mixed Listener；
- 系统具备 `curl`、`ss`、`journalctl`、`stat`、`awk`、`grep`。

v0.1 不下载或更新 Mihomo、不接管订阅、不安装面板、不启用 TUN。尚未安装
Mihomo 的用户应先阅读[从零配置教程](docs/mihomo-setup.zh-CN.md)。

本项目也不生成 PC 端 Clash/FlClash Merge、路由规则或服务器策略 YAML。规则
生成器应保留在独立仓库；`mihomo-userctl` 只负责服务器用户现有服务与 Shell。

## 安装

```bash
./install.sh --dry-run --port 17890
./install.sh --port 17890 --bashrc "$HOME/.bashrc"
```

首次安装必须明确指定端口。每个服务器用户应选择自己的端口；例如一个用户
可以使用 `17890`，另一个用户使用 `17891`。端口不同只能减少误用，不能替代
Linux UID 防火墙隔离。

安装器会：

1. 检查依赖和 systemd 用户管理器；
2. 原子安装程序文件；
3. 创建权限 `600` 的非秘密配置；
4. 保留已有 `client.env`；
5. 备份 `.bashrc`；
6. 精确替换已识别的旧代理函数块或更新 managed loader；
7. 执行不泄露秘密的 `mihomoctl doctor`；
8. 不启动、不 enable 服务。

## 日常使用

连接服务器后：

```bash
proxy_status
# shell=direct service=up endpoint=127.0.0.1:17890
```

服务没有运行时：

```bash
mihomoctl start
```

该命令成功后当前 Shell 仍然直连。只代理一条命令：

```bash
with_proxy curl https://chatgpt.com
with_proxy git clone https://github.com/example/project.git
```

临时让当前 Shell 的后续命令全部走 Mihomo：

```bash
proxy_on
proxy_status
# shell=proxied service=up endpoint=127.0.0.1:17890

proxy_off
```

大型数据保持普通运行：

```bash
axel -n 10 '下载地址'
```

只要没有先执行 `proxy_on`，普通 `axel` 不会继承本项目代理变量。

## 状态和排错

```bash
mihomoctl status
mihomoctl ready
mihomoctl doctor
mihomoctl logs --lines 100
mihomoctl logs --follow
```

- `status`：快速检查 service、enable 状态和 loopback listener；
- `ready`：额外读取凭据并发起认证 HTTP 请求；
- `doctor`：检查依赖、权限、配置、服务和 readiness，输出始终脱敏；
- `logs`：读取用户服务日志。

退出码：`0` 成功，`1` 运行状态失败，`2` 参数、配置、权限或依赖错误。

## 安全边界

- 配置与凭据按数据解析，绝不 `source`、`eval`；
- `client.env` 和 `mihomo-shell.conf` 必须属于当前用户且为 `600`；
- 代码模块和目录不得被 group/other 写入；
- 只接受配置端口上的 `127.0.0.1` HTTP/SOCKS5H URL；
- 凭据通过子进程环境传递，不出现在命令参数；
- 不使用 sudo、root service、linger、cron、TUN、controller 或系统代理；
- `stop` 只停止指定用户服务，端口不释放时只报告，绝不杀进程；
- 不处理其他用户的配置、进程、服务或端口。

完整说明见[安全模型](docs/security.zh-CN.md)。

## Codex Remote

项目保留一个经过本地验证的兼容钩子：加载 `shell.bash` 时，如果发现
`CODEX_REMOTE_PAYLOAD`，则自动执行 `proxy_on`；服务或认证不可用时明确失败。

该变量不是公开、稳定的 Codex API，因此升级 Codex 后应重新做连接验收。普通
SSH 不设置该变量，仍然默认直连。

## 卸载

```bash
./uninstall.sh --dry-run
./uninstall.sh
```

卸载只移除 `mihomoctl`、项目模块、补全和 `.bashrc` managed loader。它保留：

- Mihomo 二进制；
- `mihomo.service`；
- `config.yaml`；
- `client.env`；
- 订阅/provider 缓存；
- 文档和备份。

## 进一步阅读

- [架构与数据流](docs/architecture.zh-CN.md)
- [从零配置 Mihomo](docs/mihomo-setup.zh-CN.md)
- [从大型 `.bashrc` 迁移](docs/migration.zh-CN.md)
- [安全模型](docs/security.zh-CN.md)
- [停电、端口、凭据等排错](docs/troubleshooting.zh-CN.md)
- [借鉴 Mihoro 的范围](docs/mihoro-inspiration.md)

## 许可证

MIT
