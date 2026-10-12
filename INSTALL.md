# 安装 · Installation

- 适用版本：v1.0.1
- 完整命令与配置契约：[docs/zh-CN/v1.md](docs/zh-CN/v1.md) ·
  [docs/en/v1.md](docs/en/v1.md)
- 冻结的实现契约：[docs/architecture-v1.md](docs/architecture-v1.md)

## 依赖

| 项 | 要求 |
| --- | --- |
| 系统 | Linux，Ubuntu 22.04 / 24.04 为正式验收目标 |
| Python | 3.10+ |
| 运行后端（用户作用域，默认） | `process`，不需要 systemd |
| 运行后端（用户作用域，systemd） | 可用的 `systemd --user` |
| 运行后端（系统作用域） | 可用的 `systemd`，且需要 UID 0 |
| 诊断工具 | `curl`、`ss`、`journalctl`、`sha256sum` |

**默认安装不需要 root，不需要 systemd，不写任何 Shell 启动文件。**

## 三个必须先知道的边界

1. **安装器不写 `.bashrc` / `.zshrc` / `profile`**，不注册别名或函数，
   不注入 hook。首次使用与登录态无关。
2. **环境变量在进程创建时继承**，不是持续策略；本工具不会替你重启任何第三方进程。
3. **本工具不管理第三方应用生命周期。** systemd drop-in、env-file、
   容器与 CI 配置只导出或只写入，绝不 `enable` / `start` / `stop` / `restart`
   别人的单元。

## 1. 安装控制层

使用已核对 `SHA256SUMS` 的完整 V1 Release 源码包，解压后进入源码目录。
依赖可预先在与目标系统、Python 版本和架构匹配的联网环境准备，再整体转移：

```bash
# 准备依赖；只有此步骤需要联网，离线目标机可直接复用已准备的 wheelhouse
python3 -m pip download --only-binary=:all: --require-hashes \
  -r requirements-lock.txt -d /absolute/path/to/wheelhouse

# 从完整、干净且已审核的 Release 源码目录安装，不需要 root
bash install.sh --wheelhouse /absolute/path/to/wheelhouse --dry-run
bash install.sh --wheelhouse /absolute/path/to/wheelhouse
"$HOME/.local/bin/mihomoctl" version
python3 -I scripts/bootstrap.py verify
```

安装器把控制层写入不可变世代，再原子切换入口。它只读取本地源码和依赖，
不下载 Mihomo、不要求代理在线。若所选 Python 已具备所需依赖，可省略
`--wheelhouse`。`$HOME/.local/bin` 未在 `PATH` 时，使用上述绝对入口；
安装器不会修改 Shell 启动文件来设置 `PATH`。

用同一 V1 引导器安装另一份源码归档或 wheel 目录：

```bash
bash install.sh --source /absolute/path/to/mihomoctl-source.tar.gz \
  --wheelhouse /absolute/path/to/wheelhouse
bash install.sh --source /absolute/path/to/project-wheel-directory \
  --manifest /absolute/path/to/reviewed-release/release-manifest.json \
  --wheelhouse /absolute/path/to/wheelhouse
```

wheel 目录放置目标平台的项目 wheel；依赖放在 `--wheelhouse`。
源码、manifest、wheel 和摘要必须来自同一已审核发布。
也可在独立 Python 虚拟环境用 `pip install --no-index --find-links WHEELHOUSE
PROJECT.whl` 安装 wheel；这种安装由该环境的 pip 管理，不使用世代安装器接管。

系统安装须由管理员显式 `sudo bash install.sh --system ...`，且先将已审核源码、
依赖和 Python 放到 root 属主、普通用户不可写的可信路径。不能以 root
直接执行普通用户可写的检出副本。

根目录旧 `bootstrap.py` 及旧 `scripts/offline_install.py` / `scripts/update.py`
已经退役；V1 使用 `scripts/bootstrap.py`、`install.sh` 和 `mihomoctl update`。
旧安装教程保留作迁移参考，不能替代本节 V1 流程。

安装器**只安装控制层**。它不会隐式下载或升级 Mihomo 核心，
不会启动或 enable 服务，也不会覆盖已有凭据。

## 2. 首次初始化（用户作用域，默认）

```bash
mihomoctl init --core /absolute/path/to/mihomo
mihomoctl start
mihomoctl profile list
mihomoctl status
```

- 默认作用域是 **user**，默认运行后端是 **process**：不需要 root，也不需要 systemd。
- `init` 显式创建受管配置、凭据、默认 profile 和一个**仅回环、已认证**的命名
  mixed listener。
- 需要内核二进制时，见下一节；也可以引用一个已有二进制（保持 adopted / 只读）。

## 3. 安装受管内核（显式 + 摘要校验）

```bash
mihomoctl core install --version vX.Y.Z --sha256 <DIGEST>
mihomoctl version
```

- 固定版本 + 摘要校验，**显式**执行，不会被隐式触发。
- 已知版本使用仓库内维护者固定摘要，不匹配即失败；**未知版本必须显式给
  `--sha256 <DIGEST>`**，否则拒绝。没有摘要就没有可校验的对象，不提供绕过开关。
- 校验顺序：下载资产的 SHA256 与维护者固定摘要或用户显式提供的摘要比对
  → 受限 gzip 解压 → ELF 架构检查 → 非特权身份执行 `mihomo -v` 核对目标版本
  → 在隔离目录校验活动配置。工具不会查询 GitHub API `digest` 作为该流程的校验步骤。
- 只能说"与维护者固定摘要一致"。**不可**说"已校验官方发布""已签名验证"
  "可复现构建"：上游没有发布签名，构建也不可复现。
- 下载与校验在停止旧内核**之前**完成；激活失败恢复先前的二进制与配置。

## 4. 选择运行后端

`mihomoctl start|stop|restart|status|logs` 管理的是 **Mihomo 自身运行时**，
默认 process 后端直接使用它们。`service` 是 systemd 后端的**并列**命令，不是替代。

```text
# 用户作用域：默认 process 后端，无需 systemd
mihomoctl start
mihomoctl status
mihomoctl logs --lines 50
mihomoctl restart
mihomoctl stop

# 用户作用域：显式切换为 systemd（仅对已停止的受管运行时生效）
mihomoctl stop
mihomoctl service install
mihomoctl service start
mihomoctl status
mihomoctl service uninstall --dry-run

# 系统作用域：管理员显式操作，全程需要 UID 0
sudo mihomoctl --system init --core /usr/local/bin/mihomo
sudo mihomoctl --system service install
sudo mihomoctl --system start
sudo mihomoctl --system status
```

- `--user` 与 `--system` 互斥，缺省为 `--user`。UID 0 **不会**被自动提升作用域：
  root 不加 `--system` 可读取用户路径，但变更操作会被拒绝。
- 切换后端只对**已停止**的受管运行时生效；活动后端不会被静默替换。
- systemd 不可用时**没有**静默降级，直接报错。
- 安装 unit 只写受管文件并 reload 自己的 manager：**从不** enable、start
  或设置 linger。


## 5. 让程序走代理

```bash
# 一次命令
mihomoctl exec -- curl --head https://example.com/

# 看会注入哪些变量（默认脱敏）
mihomoctl env show
mihomoctl env show --profile work

# 导出可接入的声明；真实值只写到显式私有文件
mihomoctl env export --binding worker --output "$HOME/.config/proxy.env"
```

生成的变量是 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY` 及其小写对应项。
`exec` 在应用 profile 前只清除这**八个**继承来的代理变量，其余环境保持不变；
它在 `execve` 前要求本地健康检查通过（fail-closed），随后透传目标命令的退出码。
`exec` 不修改父 Shell，也不修改 systemd 的 manager 环境。

## 6. 让后台服务走代理（只写配置）

先在 `manager.yaml` 的 `bindings` 定义 `worker`，指定 `adapter: systemd`、
`profile: default` 和既有目标服务的 `target`；`worker` 是接入名称。

```bash
mihomoctl integration install worker              # 写 proxy.env + 受管 drop-in
mihomoctl integration show worker                 # 查看声明
mihomoctl integration remove worker
```

- systemd 接入**只**写私有 `proxy.env` 和带标记的受管 drop-in，
  然后 reload 自己的 manager。
- **绝不**执行 `start` / `stop` / `restart` / `enable` 第三方单元。
  是否应用、何时应用由你决定。
- 已存在的单元若被自定义或漂移，工具**拒绝覆盖**并报告。
- 单元已经运行时，需要**你自己**安排重启窗口。

## 7. 容器与 CI（只导出）

```bash
# 先在 manager.yaml 声明这些 bindings 的 adapter/profile/connect_host；NAME 是 binding 名称
mihomoctl integration export container-worker --output-dir "$HOME/.config/mihomoctl/export-container"
mihomoctl integration export cluster-worker --output-dir "$HOME/.config/mihomoctl/export-cluster"
mihomoctl integration export ci-worker --output-dir "$HOME/.config/mihomoctl/export-ci"
```

**容器内的 `127.0.0.1` 是容器自己的回环，不是宿主机回环。**
必须显式给出真正可达的地址；通配地址永远不会被当作客户端地址输出。
导出产物不会自动部署，也不会重启任何容器。

## 8. TUN（仅管理员，默认关闭）

```bash
mihomoctl tun status
sudo mihomoctl --system tun enable
sudo mihomoctl --system tun disable
```

- 用户作用域**没有** TUN 选项。
- V1 仅允许管理员显式通过系统作用域启用 TUN；这是产品权限策略，并非断言内核禁止所有非 root TUN 使用。
- 启用在一个可回滚事务内完成；仅在启用时授予能力，不做全局 `setcap`，
  不使用特权 helper。
- 关闭与回滚只处理本工具自有的设备与路由，**绝不**清空宿主机路由表或防火墙。

## 9. 迁移（显式 --dry-run / --apply）

```bash
mihomoctl migrate --dry-run
mihomoctl migrate --apply
```


- 导入旧配置与凭据，**只移除能确证属于本项目的 loader**，保留文件其余字节，
  并备份所有被修改的文件。
- 被自定义或形态含糊的 loader 一律**拒绝**，不猜测。
- 已存在的第三方单元只**报告**，绝不停止或删除。

## 10. 卸载

```bash
bash uninstall.sh --dry-run
bash uninstall.sh
```

卸载控制层会保留核心、配置、凭据、订阅、缓存与备份。
历史遗留的受管单元只会被**检测并提示**，工具不会代为删除或执行 `daemon-reload`。
安装和卸载会返回备份目录。需要恢复时，使用该备份携带的恢复入口：

```bash
python3 -I /absolute/path/to/BACKUP/bootstrap.py rollback /absolute/path/to/BACKUP
```

系统安装/卸载/回滚均须显式 `--system` 和管理员身份。
V1 更新从本地已审核来源执行 `mihomoctl update /absolute/path/to/SOURCE
--wheelhouse /absolute/path/to/wheelhouse`；旧协议升级须先显式迁移，不能调用旧安装路径。

## English summary

Install, configure and access. The default scope is **user** with the **process**
backend: no root, no systemd, and **no shell startup file** — the installer never
writes `.bashrc`, `.zshrc` or `profile`, so first use does not depend on a login
shell.

`mihomoctl init --core PATH` creates the managed configuration, credentials, a
default profile and one loopback-only authenticated named mixed listener.
`mihomoctl profile list` shows the redacted profiles, and `mihomoctl status`
always reports seven facts: core, controller, every listener, the active config,
the proxy layer, the routing mode, TUN and errors.

The managed core is installed explicitly with a digest gate:
`mihomoctl core install --version vX.Y.Z --sha256 <DIGEST>`; an unknown version without an
explicit digest is refused, and there is no bypass switch. The strongest statement you may make is
"matches the maintainer-curated pin"; never "signature verified" or "reproducible build".

`mihomoctl start`, `stop`, `restart`, `status` and `logs` manage the Mihomo runtime
itself and are what the default process backend uses. Choose a backend explicitly with
`mihomoctl service install` for user `systemd`, or `sudo mihomoctl --system ...` for
system scope; `mihomoctl service start|stop|restart` is offered in parallel, not as a
replacement. `--user` and `--system` are mutually exclusive and UID 0 is not promoted
automatically.

Proxy access is always explicit: `mihomoctl exec -- COMMAND` injects the eight
proxy variables, clears only those eight inherited keys, requires confirmed local
health before `execve`, and passes the child's exit code through. It never
changes the parent shell.

Long-running services use `mihomoctl integration install NAME`, which writes a
private `proxy.env` and a marked drop-in and reloads only its own manager. It
**never** enables, starts, stops or restarts a third-party unit. Docker,
Kubernetes, PM2, Supervisor and CI are **export only** — and a container's
`127.0.0.1` is not the host loopback, so exports require an explicit
reachable `connect_host` declared in `manager.yaml`.

TUN is administrator-only and disabled by default
(`sudo mihomoctl --system tun enable`). This is the V1 privilege policy, not a
claim that the kernel forbids all non-root TUN use. Migration is an explicit
`migrate --dry-run` / `migrate --apply`
that removes only a positively identified project loader and backs up everything
it touches.
