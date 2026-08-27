# mihomo-userctl

`mihomo-userctl` 是面向 Linux 共享服务器的 Mihomo 用户级控制器和 Bash
集成层。它不替代 Mihomo，也不接管订阅或节点；它解决的是“怎样安全、清晰地
启动服务，以及怎样只让明确选择的 Shell 或命令使用代理”。

> 本项目是独立、非官方项目，与 MetaCubeX、Mihomo 和 Mihoro 均无隶属关系。

[English](README.md) · [文档语言导航](docs/README.md)

## 解决什么问题

多人共享服务器中的某一个普通用户，可能只希望让自己的 Codex Remote、
VS Code Remote、Git 或少量命令使用个人代理；同时不能让自己的大型下载悄悄
进入代理，不能影响其他账户，也不应依赖管理员权限。全局导出代理变量或透明
代理对这个场景都过于宽泛。

`mihomo-userctl` 把“用户服务是否运行”和“当前 Shell 是否使用代理”明确拆开，
并把可测试、可审计的实现放在 `.bashrc` 之外。

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

## 项目边界

本仓库只包含服务器端用户级控制器和 Shell 集成。PC 端 Clash/FlClash Merge、
规则脚本和 server-policy 生成器属于另一个独立项目，不应放入本仓库，也不能
把两个项目的安装或维护步骤混在一起。

## 适用范围

最典型的场景是：多人共享 Linux 服务器中的某一个普通用户，希望只让自己的
Codex Remote、VS Code Remote、Git 或少量指定命令使用个人代理订阅，同时不改
其他用户环境，并让自己运行的 `axel`、S3 和大型科研数据继续服务器直连。

单用户服务器如果也希望“默认直连、按需代理”，同样适用。以下需求不适合：

- 给整台服务器部署透明代理或单位统一网关；
- 仅靠本工具实现 Linux UID 之间的严格端口隔离；严格隔离还需管理员防火墙；
- 没有 Bash 或可用 systemd 用户管理器的环境；
- 管理 PC 端 Clash/FlClash Merge、TUN、系统代理或路由；
- 要求无人值守自动启动、自动升级 Mihomo 或自动管理订阅生命周期。

本工具的操作范围只有安装者自己的 Home 文件和 `systemctl --user` 服务。其他
账户、归属不明的监听和无关 SSH 会话都不在范围内。

## 如何实现

1. Mihomo 以当前 Linux 用户身份运行，只创建一个带认证的
   `127.0.0.1:<每用户端口>` Mixed Listener。
2. `mihomoctl` 把配置当数据校验，只控制指定用户服务；检查监听、执行认证
   readiness，并只读取该用户 unit 的 journal。
3. `shell.bash` 加载时先清空大小写八个代理变量。`proxy_on` 只有在权限、端点、
   服务、监听和认证都通过后才导出变量；`with_proxy` 在子 Shell 中完成同样
   操作，不污染父 Shell。
4. `.bashrc` 只保留短 managed loader，在 source 前检查模块所有者和权限。
   普通 Shell 加载失败时保持直连；明确配置的 Codex 兼容路径则 fail closed。
5. 程序进入 Mihomo 后，由用户自己的规则决定 `DIRECT` 或代理节点；控制器不
   改写规则、订阅或节点。

更完整的数据流和信任边界见[架构文档](docs/zh-CN/architecture.md)。

## 适用条件

- Linux、Bash 5 或更高版本；
- 可用的 `systemd --user`；
- 已存在的 `mihomo.service`；
- Mihomo 只在 `127.0.0.1` 创建带认证的 Mixed Listener；
- 系统具备 `curl`、`ss`、`journalctl`、`stat`、`awk`、`grep`。

v0.1 不下载或更新 Mihomo、不接管订阅、不安装面板、不启用 TUN。尚未安装
Mihomo 的用户应从[安装 Mihomo 开始的完整教程](docs/zh-CN/setup.md)阅读。

本项目也不生成 PC 端 Clash/FlClash Merge、路由规则或服务器策略 YAML。规则
生成器应保留在独立仓库；`mihomo-userctl` 只负责服务器用户现有服务与 Shell。

## 安装

### 最省脑：复制 Prompt 交给 Codex

全新服务器建议先把受支持的 Codex 客户端切换到 Plan 模式，再把
[完整安装 Prompt](docs/zh-CN/codex-install-prompt.md)复制到新任务。Prompt 要求
Codex 用交互弹窗收集非敏感自定义项，先审计系统、架构、端口和权限，遇到归属
不明或需要管理员权限的步骤立即停止；订阅 URL、密码和令牌等敏感信息不得进入弹窗或聊天。

Prompt 是编排入口，不是安装程序本身。这样既容易使用，也避免把不可审计的
`curl | bash` 当成“一键安装”。

### 可审计的命令行安装

项目没有默认端口。配置 Mihomo 前，先取得一个当时未监听的候选端口并人工
确认：

```bash
PROXY_PORT=$(./install.sh --suggest-port)
printf '候选端口=%s\n' "$PROXY_PORT"
ss -lnt "sport = :$PROXY_PORT"
```

建议器从 `20000–29999` 中、以当前 UID 推导的位置为起点寻找空闲候选值，但
不会预留端口。同一台服务器的用户共享回环网络命名空间，因此必须使用不同
端口，并在绑定前再次检查、与同机用户协调。认证只能减少误用，不能让两个
进程同时绑定相同地址和端口。

将同一个端口写入 Mihomo 和 `client.env` 后，再显式安装：

```bash
./install.sh --dry-run --port "$PROXY_PORT"
./install.sh --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
```

安装器会：

1. 检查依赖和 systemd 用户管理器；
2. 原子安装程序文件；
3. 创建权限 `600` 的非敏感配置；
4. 保留已有 `client.env`；
5. 在权限 `700` 的事务备份中记录所有受管文件；
6. 追加或精确更新本项目自己的 managed loader；
7. 执行不泄露敏感信息的 `mihomoctl doctor`；
8. `doctor` 失败时自动恢复原有活动文件；
9. 不启动、不 enable 服务。

## 日常使用

连接服务器后：

```bash
proxy_status
# shell=direct service=up endpoint=127.0.0.1:<已选择端口>
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
# shell=proxied service=up endpoint=127.0.0.1:<已选择端口>

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

完整说明见[安全模型](docs/zh-CN/security.md)。

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

- [从安装 Mihomo 开始配置完整环境](docs/zh-CN/setup.md)
- [可直接复制的 Codex 安装 Prompt](docs/zh-CN/codex-install-prompt.md)
- [架构与数据流](docs/zh-CN/architecture.md)
- [安全模型](docs/zh-CN/security.md)
- [停电、端口、凭据等排错](docs/zh-CN/troubleshooting.md)
- [借鉴 Mihoro 的范围](docs/zh-CN/mihoro-inspiration.md)

## 许可证

MIT
