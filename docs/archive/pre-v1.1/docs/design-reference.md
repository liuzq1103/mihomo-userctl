# 设计参考 / Design Reference

- 状态：**V1 设计依据**（记录已核实的外部事实与由此推出的边界，不描述未实现行为）
- 对应：[vNext 目标架构](architecture-vnext.md) · [ADR 0001](adr/0001-vnext-foundation.md)
- 基线核实日：2026-10-11；mihomo 核实版本 **v1.19.32**（release id `400265188`，发布于 2026-09-30）

本文只记录**可复现核实**的外部事实，以及由这些事实直接推出的 V1 边界。
凡是推断、约定或尚未实现的内容，都显式标注，不与已核实事实混写。

---

## 1. 证据等级

本文使用三档标注，与 [architecture-vnext.md](architecture-vnext.md) 的 Evidence 模型一致：

| 标注 | 含义 |
| --- | --- |
| `verified` | 直接读取官方文档或官方源码得到的原文事实 |
| `derived` | 由 `verified` 事实推出的设计结论，逻辑可复核 |
| `unverified` | 本次未能核实，**不得作为设计前提** |

## 2. 调研限制（必须先读）

三项限制直接影响部分结论的可复现性：

1. `freedesktop.org` 在核实环境下返回 HTTP 418（反机器人页）。systemd 相关结论改为核对
   systemd 仓库内的 man 源文件（`man/*.xml`），二者同源。
2. GitHub REST API 在核实环境下取不到 mihomo 仓库的可靠资料（`GET /repos/MetaCubeX/mihomo`
   返回了同名但无关的条目）。**该响应不作为任何项目事实使用**；mihomo 结论一律取自
   `raw.githubusercontent.com/MetaCubeX/mihomo/Meta/`（默认分支 `Meta`，真实 Go 源码）。
   `releases/*/assets` 端点与 `expanded_assets` 页面的返回则与 release 页面一致，已交叉核对。
   资产 digest 另经父 Agent 独立经 GitHub API 复核（见 §6.3）。
3. `raw.githubusercontent.com/SagerNet/sing-box` 在核实环境下全部 404，sing-box **源码级**结论
   未核实；本文 sing-box 部分仅基于其官方文档站可访问页面，并逐条标注。

---

## 3. Mihomo 内核（`verified`）

来源：`https://github.com/MetaCubeX/mihomo/blob/Meta/main.go`（默认分支 `Meta`）

### 3.1 flag 与环境变量等价

`init()` 以 `os.Getenv` 作为 flag 默认值，因此每个 flag 都有环境变量等价物：

| flag | 环境变量 | 作用 |
| --- | --- | --- |
| `-d` | `CLASH_HOME_DIR` | 配置根目录 |
| `-f` | `CLASH_CONFIG_FILE` | 配置文件路径 |
| `-config` | `CLASH_CONFIG_STRING` | base64 编码的配置内容 |
| `-age-secret-key` | `CLASH_AGE_SECRET_KEY` | age 密钥 |
| `-ext-ctl` | `CLASH_OVERRIDE_EXTERNAL_CONTROLLER` | 覆盖控制面地址 |
| `-ext-ctl-unix` | `CLASH_OVERRIDE_EXTERNAL_CONTROLLER_UNIX` | 覆盖 unix socket 地址 |
| `-ext-ctl-tls` | `CLASH_OVERRIDE_EXTERNAL_CONTROLLER_TLS` | 覆盖 TLS 控制面地址 |
| `-secret` | `CLASH_OVERRIDE_SECRET` | 覆盖 API secret |
| `-post-up` / `-post-down` | `CLASH_POST_UP` / `CLASH_POST_DOWN` | **由内核执行 shell 脚本** |
| `-t` | — | 校验配置后退出 |

另有三个早于守护流程返回的离线子命令：`convert-ruleset`、`generate`、`age`。

文档：<https://wiki.metacubex.one/en/startup/service/>

### 3.2 `-t` 是纯解析，但会触发 geodata 下载

`main.go` 中 `testConfig` 分支只调用 `executor.Parse()` / `executor.ParseWithBytes()`，
即 `config.Parse(buf)` → `UnmarshalRawConfig` → `ParseRawConfig`。
**`ParseRawConfig` 不调用 `ApplyConfig`**，而 `ApplyConfig` 才是
`updateListeners` / `updateTun` / `updateIPTables` / `updateProxies` 的所在
（`hub/executor/executor.go`）。

> `derived` 因此 `-t` 不会 bind 任何 listener、不会创建 TUN 设备、不会改 iptables。
> 校验阶段不与运行中的实例争抢端口。

但 `ParseRawConfig` 含有明确注释：

> `// The loading and downloading of geodata in the parseRules and parseRuleProviders rely on these.`

> `derived` geodata 在**解析阶段**加载，缺失时下载并写入 `-d` 指定的 home dir。
> **V1 约束：`-t` 必须以 `-d <staging_dir>` 执行，绝不能指向运行中的 home dir。**

### 3.3 `-t` 的校验盲区

`main()` 控制流顺序：`version → homeDir → geodataMode → ageSecretKey → 配置来源解析 →
if testConfig { return } → options(hub.Option) → hub.Parse(...)`。

`hub.Option` 在 `testConfig` 的 `return` **之后**才构造。

> `derived` **`-t` 模式下 `-ext-ctl` / `-secret` / `-ext-ctl-unix` 及对应 `CLASH_OVERRIDE_*`
> 全部不生效，也不在校验范围内。** 控制面地址与 secret 必须写进候选配置文件本身，
> `-t` 才有校验价值。任何"用环境变量注入控制面地址"的方案，其控制面配置未经校验。

### 3.4 stdin 校验

```go
} else if configFile == "-" {
    configBytes, err = io.ReadAll(os.Stdin)
}
```

`-f -` 从 stdin 读配置，并跳过 `config.Init(homeDir)`（该调用在 else 分支内）；
`C.SetHomeDir(homeDir)` 在更早处执行。

> `derived` `mihomo -t -d "$STAGING_DIR" -f - < candidate.yaml` 是可用形式：
> 候选配置永不落盘到正式配置路径，geodata 落在 staging dir。**这是 V1 校验门禁的推荐形式。**

### 3.5 SIGHUP 确实重读磁盘文件（含两条例外）

`main.go` 信号循环：

```go
signal.Notify(hupSign, syscall.SIGHUP)
case <-hupSign:
    if err := hub.Parse(configBytes, options...); err != nil {
        log.Errorln("Parse config error: %s", err.Error())
    }
```

分派逻辑（`hub/hub.go`）：

```go
func Parse(configBytes []byte, options ...Option) error {
    if len(configBytes) != 0 { cfg, err = executor.ParseWithBytes(configBytes) }
    else                    { cfg, err = executor.Parse() }
    ...
}
```

而 `hub/executor/executor.go`：

```go
func Parse() (*config.Config, error)          { return ParseWithPath(C.Path.Config()) }
func ParseWithPath(path string) (...)        { buf, err := readConfig(path); ... }
func readConfig(path string) ([]byte, error)  { os.Stat(path) ...; os.ReadFile(path) ... }
```

> `verified` **正常守护模式下 `configBytes` 为 nil，SIGHUP 触发 `os.ReadFile` 重新读取配置，
> 确实重读磁盘。** 解析失败时只记录日志，旧配置继续运行，进程不退出 —— 非破坏性。

必须同时记录的两条例外：

1. 若以 `-f -`（stdin）或 `-config <base64>` 启动，`configBytes` **非空**，
   SIGHUP 重放的是**内存中的旧字节**，不再读盘；`-f -` 情况下不存在文件。
   > `derived` **V1 守护进程必须用 `-d` + `-f <file>`（或默认路径），不得用 `-f -`。**
   > 注意 V1 校验门禁正是用 `-f -`，两者是不同用途，启动形态不得混用。
2. `C.SetConfig(configFile)` 只在启动时执行一次，`C.Path.Config()` 的**路径**在 reload 时
   不重新解析；重读的是该路径下的**内容**。

### 3.6 不支持 sd_notify

`main.go` 中 `NOTIFY_SOCKET` / `sd_notify` 均不出现。

> `derived` **必须 `Type=simple`；`Type=notify` 不可用。**

### 3.7 出厂默认值

来源：`config/config.go` 的 `DefaultRawConfig()`

| 键 | 默认值 | 含义 |
| --- | --- | --- |
| `AllowLan` | `false` | 默认仅本机可达 |
| `BindAddress` | `"*"` | 仅在 `allow-lan: true` 时生效 |
| `Authentication` | `[]string{}` | **代理端口默认无认证** |
| `LanAllowedIPs` | `0.0.0.0/0`, `::/0` | 一旦开 allow-lan 则全放开 |
| `Tun.Enable` | `false` | TUN 默认关闭 |
| `GeoAutoUpdate` | `false` | 默认无后台更新 |
| `DNS.Enable` | `false` | — |
| `external-controller` | 字面量中**未设置** | 默认不监听 REST 控制面 |

文档：<https://wiki.metacubex.one/en/config/general/>

> `derived` 真实风险不是"出厂即 `0.0.0.0:9090`"，而是**用户启用控制面却未设 `secret`，
> 此时控制面完全无认证**（`secret: ""`）。V1 的凭据缺失 fail-closed 门禁针对这一条。

### 3.8 控制面可走 unix socket

`external-controller-unix: mihomo.sock`，官方文档原文：

> "Accessing API endpoints via Unix socket does not verify secrets. If enabled, please ensure
> security measures are in place."

认证方式为 `Authorization: Bearer <secret>`（<https://wiki.metacubex.one/en/api/>）。

> `derived` 该路径可消除控制面端口争抢，但**无认证**；若采用，socket 必须置于 `0700` 目录内
> 并由 V1 自行做可达性检查。

### 3.9 `listeners` 是独立旁路入口

`listeners[]` 支持 `name` / `type` / `listen` / `port` / `routing-mark` / `rule` / `proxy`
（<https://wiki.metacubex.one/en/config/inbound/listeners/>）；`name` 可被 inbound rule 匹配。

> `derived` **安全 envelope 必须同时封禁顶层 port 类键与 `listeners` 数组**，
> 否则 envelope 存在绕过路径。见 §10.2。

---

## 4. systemd（`verified`）

渲染文档：<https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html> ·
<https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html> ·
<https://www.freedesktop.org/software/systemd/man/latest/loginctl.html>

本文结论核对自同源 man 文件：
`https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml` ·
`.../systemd.service.xml` · `.../loginctl.xml`

### 4.1 EnvironmentFile= 语法

> "Empty lines, lines without a `=` separator, or lines starting with `;` or `#` will be ignored…
> A line ending with a backslash will be continued to the following one…"
> "**If the file does not exist, cannot be read, or contains invalid content, the service will
> fail to start.** To make the file optional, prefix the path with `-`."

> `derived` **V1 不使用 `-` 前缀**：保留"缺文件即启动失败"作为 fail-closed 门禁。

### 4.2 环境变量不是机密隔离机制

`Environment=` 条目原文：

> "**Note that environment variables are not suitable for passing secrets (such as passwords,
> key material, …) to service processes. Environment variables set for a unit are exposed to
> unprivileged clients via D-Bus IPC**, and generally not understood as being data that requires
> protection. Moreover, environment variables are propagated down the process tree, including
> across security boundaries (such as setuid/setgid executables)… Use `LoadCredential=`…"

`EnvironmentFile=` 在文档中被描述为 "Similar to `Environment=`"。

> `unverified` **该警告针对 `Environment=` 的 unit 属性，不能据此断定 `EnvironmentFile=`
> 读入的每一个值都经同一路径对任意 UID 可读。** 本次调研未逐一核实 systemd 对
> EnvironmentFile getter 的实现与可见性，因此不做该断言。systemd 文档此处是"不应用环境变量
> 传密钥"的通用告警，不构成对 envfile 具体读取路径的验证。

文档中可确立的是**继承风险**，与取值来源无关：环境变量随进程创建被继承，并沿进程树传播、
跨越 setuid/setgid 等安全边界；进程运行中亦可自行改写。**这使得环境变量在原理上不适合作为
机密载体**，而不依赖于它是否出现在 unit 正文。

> `derived` **V1 由此得出的做法（不否定已批准的 `EnvironmentFile=` 设计）：**
> 1. **不把密钥写进 unit 正文**（`Environment=` 及单元文件内的任何字面值）。
> 2. **真实值只落在受限私有文件**（目录 `0700` / 文件 `0600`，owner-only），即 mihomo 自身
>    读取的 `0600` 生成配置文件（`external-controller` 与 `secret`，结合 §3.3）。
> 3. **`EnvironmentFile=` 可承载带认证的代理 URL**：按已批准设计由 V1 生成 0600 文件，
>    unit 正文只引用文件路径。此文件含凭据，必须按秘密文件处理。
> 4. **文档须说明继承风险**：代理凭据随目标进程及其子进程环境传播；不得声称环境变量
>    提供秘密隔离，也不得把认证 URL 误称为非机密参数。
> 5. `LoadCredential=` 是 systemd 给出的更强选项，但 mihomo 无法从 credential 文件读取
>    secret；除非引入 exec wrapper，**V1 不适用**。

### 4.3 ExecStart 前缀表

`systemd.service.xml` 原文表格：

| 前缀 | 效果 |
| --- | --- |
| `@` | 第二个 token 作为 `argv[0]` |
| `-` | 非零退出码被记录但不影响结果 |
| `:` | 不做环境变量替换 |
| `+` | **以完整权限执行**：忽略 `User=` / `Group=` / `CapabilityBoundingSet=` 与各类命名空间限制（不影响其他 `ExecStart=` 行；cgroup 级如 `DevicePolicy=` 仍生效） |
| `!` | 类似 `+`，但**只**放宽 `User=` / `Group=` / `SupplementaryGroups=` |
| `\|` | 独立出现 = 调用 `User=` 的 shell；作为前缀 = 用 `sh -c` 包装 |
| `!!` | 完整权限 + 不受命名空间限制 |

另有：

> "redirection using `<`, `<<`, `>`, `>>`, pipes using `|`, running programs in the background
> using `&`, and other elements of shell syntax are **not supported**."

> `derived` **V1 禁用 `|` / `;` / `&&` / `||` 等一切 shell 包装前缀；`ExecStart=` 必须是直接
> argv。`EnvironmentFile=` 正是 shell wrapper 的替代品：动态内容移到数据文件，argv 保持静态。
> `+` 前缀是 system scope 下给 `ExecStartPre=` 单独提权的唯一正当途径。**

### 4.4 权限收敛（system scope）

| 指令 | 要点 |
| --- | --- |
| `CapabilityBoundingSet=` | 白名单外全部移除；**不使用则不修改任何限制**；空串 = 清空 |
| `AmbientCapabilities=` | 配合 `User=` 让非特权进程获得能力；**不影响 `+` 前缀命令** |
| `NoNewPrivileges=` | 阻止 `execve()` 获得新权限 |
| `ProtectSystem=full/strict` | 建议对长驻服务开启，配合 `ReadWritePaths=` 开口 |

### 4.5 user scope 的两个前提

- **linger**（`loginctl(1)`）："If enabled for a specific user, a user manager is spawned for the
  user at boot and kept around after logouts. This allows users who are not logged in to run
  long-running services." 为他人开启是特权操作。
- **XDG_RUNTIME_DIR**：非登录会话中通常为 `/run/user/$UID`
  （podman 文档亦以此为默认值）。临时文件与套接字路径必须从它派生，
  **不得硬编码 `/var/run`**。

> 交叉验证：Tailscale 的 `DefaultTailscaledSocket()` 在 `/var/run` 存在时返回
> `/var/run/tailscale/tailscaled.sock`，否则退化为 cwd 相对的 `tailscaled.sock`
> （<https://github.com/tailscale/tailscale/blob/main/paths/paths.go>）。
> 即非 root 场景必须显式指定用户自有 socket 路径。

### 4.6 不照抄 `ExecStartPre=/usr/bin/sleep 1s`

mihomo 官方 unit 示例含该行，是 `After=network.target` 竞态的权宜之计。
正规做法是 `After=network-online.target` + `Wants=network-online.target`。

---

## 5. TUN 与特权（`verified`）

### 5.1 内核门槛

来源：<https://github.com/torvalds/linux/blob/master/drivers/net/tun.c>

```c
static int tun_set_iff(struct net *net, struct file *file, struct ifreq *ifr)
{
	...
	if (!ns_capable(net->user_ns, CAP_NET_ADMIN))
		return -EPERM;
```

`CAP_NET_ADMIN` 定义（<https://manpages.debian.org/bookworm/man7/capabilities.7.en.html>）：
"interface configuration; administration of IP firewall…; modify routing tables; bind to any
address for transparent proxying…"

mihomo 额外需要（<https://wiki.metacubex.one/en/config/inbound/tun/>）：
`auto-route`（**默认 true**）改路由表；`auto-redirect` 自动配置 iptables/nftables；
`route-address-set` 明确要求 nftables + `auto-route` + `auto-redirect`。

> `derived` **V1 的 TUN 仅允许管理员在 system scope 显式启用。** 内核检查的是目标网络
> 命名空间的 `CAP_NET_ADMIN`，不能据此推导“任何非 root 进程均无法使用 TUN”。
> [Linux TUN/TAP 官方文档](https://docs.kernel.org/networking/tuntap.html) 也描述了将持久设备
> 授权给非特权用户的情形。V1 不提供能力委派或用户命名空间 TUN 路径，这是产品权限边界。

### 5.2 已知但 V1 不实现的技术路径：sing-box netns

<https://sing-box.sagernet.org/configuration/network-namespace/unshare/>

> "Create a new network namespace, without root privilege. **Rootless operation requires the
> kernel to allow unprivileged user namespace creation.**"
> "`pid_file`: … The namespace can be entered with `nsenter -t <pid> -U
> --preserve-credentials -n` otherwise."

> `derived` 不采用：依赖发行版 `unprivileged_userns_clone` / `user.max_user_namespaces` 策略
> （部分发行版默认禁用）；且每个被代理进程都需额外包一层 `nsenter`，
> 与"零侵入接入"目标冲突。（sing-box 源码级细节 `unverified`，本环境 raw 404。）

### 5.3 降级形态模板：tailscale userspace networking

<https://tailscale.com/kb/1112/userspace-networking>

> "Userspace networking mode lets you run Tailscale where you don't have access to create a VPN
> tunnel device… `tailscaled` functions as a SOCKS5 or HTTP proxy…"
> `tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --outbound-http-proxy-listen=localhost:1055`

> `derived` **V1 采纳"能力探测 → 显式降级 → 明确报告"形态**：TUN 不可用时产出
> `UNVERIFIED` 并指明可用的降级注入形态，不静默跳过。

---

## 6. 供应链：core 安装与更新的校验

### 6.1 官方 release 资产清单（`verified`）

实测 **v1.19.32**（`github-actions[bot]` 发布，`target_commitish: main`）：

- 共 **127 个 asset**，其中**只有 `version.txt` 一个非二进制文件**
- 无 `*.sha256` / `checksums.txt`
- 无 `*.asc` / `*.sig` / `*.minisig` / `*.pem` / `*.crt`
- 无 `*.intoto.jsonl`，无 sigstore bundle，无任何 attestation

交叉核对 v1.19.14：同样只有 `version.txt` 一个非二进制资产，排除单次异常。

**资产格式**：Linux 为 `gzip -c mihomo-linux-amd64 > ….gz` —— **原始二进制的 gzip 流，
不是 tar**。没有 tar 成员/路径穿越问题，但仍需解压后大小上限（gzip bomb）。

### 6.2 三层信任必须分开表述

| 层 | 来源 | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| **维护者固定摘要** | 仓库内 `mihomo-digests.json`，经评审的 commit | 与维护者评审过的值一致 | 上游签名存在 |
| **GitHub API 摘要** | `GET /repos/{o}/{r}/releases/{id}/assets` 的 `digest` 字段（形如 `sha256:…`） | 未在传输中损坏 | **发布方真实性**；该值由上传方同一 `GITHUB_TOKEN` 体系产生，攻陷流水线者可同时替换二进制与摘要 |
| **上游签名** | —— | —— | **不存在** |

**GitHub API 摘要不是发布方承诺。** 检测传输损坏有效，检测恶意替换无效。

上游确实生成了 checksums，但未发布到稳定版（`verified`，`.github/workflows/build.yml`）：

- `Calculate checksums`（L342-346）只存在于 **`Upload-Prerelease`** job，目标标签为
  `Prerelease-${{ github.ref_name }}`（L353）
- 稳定版 `Upload-Release` job（L388-445）**无任何 checksum 步骤**，直接 `files: bin/*`
- 打标签为 `git tag ${{ inputs.version }}`（L419），**未签名**

**可复现构建同样不可用**（`verified`，同文件）：
L245 使用 `-buildid=""` 与 `-trimpath`（有意图），但 L201 `BUILDTIME=$(date)` 把墙钟时间经
ldflags 写入 `constant.BuildTime`；L233 把 runner 的 `ca-certificates.crt` 烤入二进制；
L204 `GOTOOLCHAIN=local` 依赖 runner 预装 Go 版本。故"本地重建比对摘要"不成立。

### 6.3 V1 可实现的精确策略

| 层 | 手段 | 证据等级 |
| --- | --- | --- |
| L1 传输完整性 | 本地 sha256 vs GitHub API `digest` | `transport-verified`（**不是** `confirmed`） |
| L2 **维护者固定摘要** | `mihomo-digests.json`：`version → platform/arch → sha256` | `confirmed` |
| L3 上游摘要（若将来出现） | 探测 `checksums.txt`（stable 或 `Prerelease-*`），匹配则升级等级 | `confirmed-upstream` |
| L4 结构校验 | ELF magic + `e_machine` 与请求架构一致 + `mihomo -v` 版本串 == 固定版本 | `confirmed` |

实现约束：

1. **L2 默认且强制**：固定表有条目则不匹配即 `FAIL`；**无条目则默认拒绝更新**
   （`BLOCKED`），需显式 `--allow-unpinned`。保持 fail-closed 语义。
2. **固定表须自带 provenance**：每条记录 `source` / `reviewed_at` / `reviewed_by`。
   若维护者本身也取自同一被攻陷通道，该 pin 无价值 —— 文档须直说。
3. **L1 永远执行**，但其等级必须命名为 `transport-verified` / `unavailable`。
4. **L4 的版本串比对性价比最高**：可挡住 tag/资产错配这一真实事故类型。
5. **验证器接受多来源并显式标注来源名**，不硬编码一种，以便上游补齐后自动升级而无需改码。
6. 解压前比对 `Content-Length`（API 提供 `size`），解压后设大小上限。

**文案红线**：不得宣称"已校验官方发布""已签名验证""可复现构建"。
可达到的最高表述是"与维护者固定摘要一致"。

### 6.4 已评审 pin 示例

以下条目可作为 L2 固定摘要的首条记录：

| version | asset | sha256 | 来源 |
| --- | --- | --- | --- |
| v1.19.32 | `mihomo-linux-amd64-compatible-v1.19.32.gz` | `ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20` | 父 Agent 独立经 GitHub API 核实 |

> 该值**是经评审的固定摘要（pin）来源，不是签名**。信任来自"评审动作 + 落入版本控制"，
> 不来自上游签名背书；与 §6.2 的 GitHub API `digest` 属同一类机制，不因多一道人工复核而
> 升格为上游签名。条目仍须按 §6.3 第 2 条补齐 `source` / `reviewed_at` / `reviewed_by`。

---

## 7. 对比项目：只取控制流

| 项目 | 来源 | 可借鉴 | 不引入 |
| --- | --- | --- | --- |
| clash-verge-rev | `src-tauri/src/cmd/service.rs`、`src-tauri/src/core/service.rs` | 安装/启动失败 → **带原因的显式降级**（`ServiceFallbackNotice::Unavailable \| CoreRejected \| NotAutoStarted`，降级为 `Sidecar { reason }`） | Windows Service + Tauri + 提权安装器（桌面 GUI 路径，与定位正交） |
| tailscale | <https://tailscale.com/kb/1112/userspace-networking> | daemon / CLI 分离，CLI 不常驻 | — |
| sing-box | <https://sing-box.sagernet.org/configuration/network-namespace/unshare/> | 能力分级降级 | netns rootless TUN（§5.2） |
| podman | <https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md> | — | rootless 容器托管 |
| docker | <https://docs.docker.com/engine/security/rootless/> | — | rootless 容器托管 |

> `derived` **容器化不是 V1 候选路径。** Podman 原文："**Root privileges are required to add or
> update entries within these files**"（指 `/etc/subuid`/`/etc/subgid`）；
> "**The majority of the work necessary to run Podman in a rootless environment is on the
> shoulders of the machine's administrator.**" Docker rootless 同样要求 65,536 个 subordinate
> UID/GID。前置条件全部是管理员一次性配置，与"默认无 root、用户自助安装"冲突。

---

## 8. V1 抽象：四层

V1 统一抽象为 **ProxyProfile + EnvironmentInjection + RuntimeIntegration + HealthCheck**。
**核心不含任何 Codex / Paseo / OpenCode 专属代码** —— 适配器只认识 `kind`，不认识工具名。

```text
  声明层  profiles.toml          profile 是纯数据注入模板；binding 声明"哪个实例用哪个 profile"
            │
            ▼
  注入层  EnvironmentInjection   profile + 目标 → 环境变量集合 + 文件产物（纯函数）
            │
            ▼
  接入层  RuntimeIntegration     声明式 adapter：generic-exec / systemd-user / systemd-system
            │                    + 产物导出：docker / k8s
            ▼
  验证层  HealthCheck            只对 runtime 生效，不对 workload 生效
```

### 8.1 ProxyProfile

profile 是**纯数据模板**，不含凭据：

```toml
[profiles.work.env]
HTTP_PROXY   = "{mixed_url}"
HTTPS_PROXY  = "{mixed_url}"
http_proxy   = "{mixed_url}"
https_proxy  = "{mixed_url}"
ALL_PROXY    = "{socks5_url}"
NO_PROXY      = "{no_proxy}"

[profiles.work.files]
".config/example/proxy.json" = "{rendered_json}"

[[bindings]]
profile = "work"
kind    = "generic-exec"
argv    = ["codex", "--profile", "work"]
```

> `derived` **凭据由 runtime 自己持有，不进入 profile 模板**；profile 只描述"如何引用"，
> 不描述"值是什么"。`{...}` 为受限占位符，仅接受白名单值
> （`mixed_url` / `socks5_url` / `no_proxy` / `http_bind` / `controller_bind`），
> 解析失败即硬错误。

### 8.2 边界矩阵

| 目标形态 | V1 做什么 | V1 **不**做什么 |
| --- | --- | --- |
| **generic-exec** | **原生**：设 env 后 `execvp`，透传 argv 与退出码 | 不修改目标已有环境；不观测该进程后续行为 |
| **systemd --user** | **原生**：写 `EnvironmentFile`（0600、owner-only）+ 可选 drop-in + `daemon-reload` | 不执行 `start/stop`（除用户显式要求）；**不把密钥写进 unit 正文**（见 §4.2） |
| **systemd --system** | 生成 unit 片段；**仅 TUN 时**加 `CapabilityBoundingSet` / `AmbientCapabilities` | 不 `sudo`；不自行提权 |
| **Docker** | **仅导出**：env-file 片段 + `docker run --env-file` / compose `env_file` 片段 | **不**重启容器、**不**调用 Docker API、**不**改 compose 文件 |
| **Kubernetes** | **仅导出**：ConfigMap/Secret 片段 + `envFrom` 片段 + 可选 Deployment patch | **不** apply、**不**等待 rollout |
| **shell profile** | 导出 `mihomoctl env --shell bash\|zsh\|fish` | **不**要求用户 source |

### 8.3 必须写明的三条限制

1. 环境变量是**创建时继承**，不是持续策略；进程可在运行中自行改写，不重新 exec 就没有更新。
2. 环境变量**不是网络强制策略**，不是防火墙。
3. **仅提供配置不能"控制"运行时。** Docker / K8s 路径只产出声明，不产生控制；
   是否应用、何时应用、是否重启，全部由用户或其 CD 流水线决定。

> 对通用 exec 与 systemd 只注入环境变量，**V1 不接管第三方进程/单元的生命周期**。

---

## 9. HealthCheck（只针对 runtime）

| 检查 | 手段 | 等级 |
| --- | --- | --- |
| 服务态 | `systemctl --user show -p ActiveState` | `confirmed`（仅证单元态） |
| 监听存在 | `bind()` 探测 mixed 端口 | `confirmed`（仅证有监听） |
| 监听归属 | `/proc` 同 UID 归属核对 | `inferred` |
| 代理可用 | 带认证 HTTP 探针 | `confirmed`（仅证该请求经该代理） |
| 出网真实性 | —— | **V1 不做，无法证实** |

保留 [architecture-vnext.md](architecture-vnext.md) §10.2 的边界：认证探针通过**不能**证明
流量经远端节点；节点选择**不**证明某次请求；未观察到 socket **不等于**直连；
`/proc/<pid>/environ` **不是**可靠的运行时环境接口。

---

## 10. V1 边界与红线

### 10.1 纳入

1. `mihomo -t -d <staging> -f -` 作为唯一校验门禁（§3.2 / §3.4）。
2. 控制面绑定 `127.0.0.1` + per-user `secret`，密钥只落在 `0600` owner-only 文件、**不写进
   unit 正文**（§3.7 / §4.2）。
3. `systemd --user` 单 scope，`Type=simple`，`ExecReload=/bin/kill -HUP $MAINPID`，
   `ExecStart=` 纯 argv，带认证代理 URL 只写入私有 `EnvironmentFile=` 文件（§4.2）。
4. `EnvironmentFile=` 不加 `-` 前缀（§4.1）。
5. profile + binding 声明式配置，核心零 workload 专属代码（§8.1）。
6. 两个原生 adapter：`generic-exec`、`systemd-user`；`docker` / `k8s` 仅导出产物（§8.2）。
7. 能力探测 + 显式降级报告（§5.3）。
8. 四层供应链校验，维护者固定摘要为信任锚（§6.3）。

### 10.2 安全 envelope 必须封禁的键

顶层：`port` / `socks-port` / `mixed-port` / `redir-port` / `tproxy-port` /
`bind-address` / `allow-lan` / `lan-allowed-ips` / `lan-disallowed-ips` /
`authentication` / `skip-auth-prefixes` /
`external-controller` / `external-controller-tls` / `external-controller-unix` /
`external-controller-cors` / `external-doh-server` / `secret` /
`tun` / `listeners[]`

> 对 `external-controller*` 与 `secret` 做**存在性检查**：不允许新增、不允许删除、不允许改值。
> 其余为硬拒绝。

### 10.3 明确不做

| 不做 | 依据 |
| --- | --- |
| `Type=notify` | mihomo 无 sd_notify（§3.6） |
| 密钥写进 unit 正文或经命令行传入 | 环境变量在原理上不是机密隔离机制：随创建继承并沿进程树传播、跨安全边界（§4.2） |
| 任何 shell wrapper（`ExecStart=\|`、`-post-up`、`-post-down`） | 违反"绝不依赖 shell hook"；`post-up/down` 由内核执行 shell（§3.1 / §4.3） |
| 守护进程用 `-f -` 启动 | SIGHUP 将重放内存字节而非重读文件（§3.5） |
| user scope 的 TUN | V1 明确禁止；内核能力要求见 §5.1 |
| 容器托管 runtime | rootless 需管理员预配 subuid/subgid（§7） |
| Docker / K8s 的控制能力 | 只导出产物（§8.2 / §8.3） |
| 用 `-ext-ctl` / env 注入控制面 | `-t` 不校验此类覆盖（§3.3） |
| 接管用户 crontab / 覆盖式自动更新 | ADR 0001 既有决策 |
| 声称"仅配置即可控制运行时" | env 是创建时继承，非持续策略（§8.3） |
| 宣称"已签名验证 / 可复现构建" | 上游无签名、构建不可复现（§6.2） |
| 声明 sing-box `check` 等价子命令 | `unverified`（§2） |

### 10.4 system scope 与非回环的唯一入口

> `derived` **user scope 不得启用 TUN，也不得配置非回环监听。**
> 二者仅在 system scope 且用户显式选择时可用：TUN 走受限
> `CapabilityBoundingSet` / `AmbientCapabilities`；非回环监听需显式指定且伴随
> per-user 认证与 `allow-lan` 语义确认（`lan-allowed-ips` 默认 `0.0.0.0/0`，§3.7）。
> 两者都属于特权操作，**V1 不自行提权、不使用 `sudo`**。

---

## 11. 与既有文档的关系

1. **[ADR 0001](adr/0001-vnext-foundation.md) 的审计对象不在本调研范围内。**
   ADR 0001 的 Route B 否决理由针对的是 **Mihoro**（`spencerwooo/mihoro`，审计 commit
   `c2b65e37`，v0.14.0）的默认 `external-controller: 0.0.0.0:9090` 与可空 secret。

   **本次调研只核实 mihomo 本体，未调研 Mihoro**，因此 §3.7 关于 mihomo
   `DefaultRawConfig()` 的结论**既不能证实也不能推翻** ADR 0001 对 Mihoro 的描述。
   两者是两个不同上游，结论不可互相推导。任何一方都需要对自己的上游单独取证。

   ADR 0001 对 Mihoro 的取证结论维持原状，本调研不作改写；后续若要复核，应对 Mihoro
   仓库单独执行同等核实。
2. [architecture-vnext.md](architecture-vnext.md) §7.1 的安全 envelope 键清单不完整，
   需按 §10.2 补齐，否则 envelope 存在绕过路径（`listeners[]` 尤其）。

---

## 12. English summary

**design-reference.md** records only externally verified facts and the V1 boundaries they
imply. Every claim is marked `verified`, `derived`, or `unverified`; the document states its
own research limits, including that `freedesktop.org` returned HTTP 418 (so systemd facts were
checked against the systemd repository's man sources) and that GitHub's REST API did not yield
reliable material for the mihomo repository in this environment — that response is explicitly
**not** treated as project fact, and mihomo conclusions come from
`raw.githubusercontent.com/MetaCubeX/mihomo/Meta/` instead. The asset digest was independently
re-checked by the parent agent via the GitHub API (§6.4).

Key verified facts: mihomo's `-t` calls `executor.Parse` only and never `ApplyConfig`, so it
binds no listener and creates no TUN device — but it **does** download geodata during parsing,
so it must be run with `-d <staging_dir>`; and `-t` returns before `hub.Option` is built, so
`-ext-ctl` / `-secret` and their `CLASH_OVERRIDE_*` equivalents are neither applied nor
validated. SIGHUP **does** re-read the config file from disk in normal daemon mode
(`configBytes` is nil → `executor.Parse` → `readConfig` → `os.ReadFile`), and a parse failure is
non-destructive — but if launched with `-f -` or `-config`, SIGHUP replays in-memory bytes and
never touches disk. mihomo has no `sd_notify`, so `Type=simple` is mandatory. systemd warns
that environment variables are unsuitable for secrets because they are inherited at process creation,
propagate down the process tree and cross setuid/setgid boundaries. That warning is **not** read
here as proof that every value read via `EnvironmentFile=` is D-Bus-readable by any UID -- this
survey did not verify each envfile getter -- so the claim is marked `unverified`. What follows from
the documented inheritance risk alone: V1 keeps keys out of unit body text, stores real values
only in owner-only `0600` files, and lets `EnvironmentFile=` reference private proxy credentials.
Authenticated proxy URLs are sensitive; their inheritance must be documented. `tun_set_iff` requires `ns_capable(CAP_NET_ADMIN)`
in the target network namespace. V1 intentionally exposes TUN only through administrator-managed
system scope; the capability check is not a universal prohibition on non-root processes using TUN.

On supply chain: the official v1.19.32 release has 127 assets of which only `version.txt` is
non-binary — no checksum file, no signature, no attestation. Upstream generates `checksums.txt`
only in the `Upload-Prerelease` job for `Prerelease-*` tags, tags are unsigned, and builds are
not reproducible because `BUILDTIME=$(date)`, a baked-in CA bundle, and `GOTOOLCHAIN=local` all
vary. V1 therefore separates three trust tiers explicitly — maintainer-curated pin (the only
real anchor), GitHub API `digest` (transport integrity only, **not** a publisher commitment),
and upstream signature (**nonexistent**) — and forbids the claims "signed" and "reproducible".

V1 is abstracted as ProxyProfile + EnvironmentInjection + RuntimeIntegration + HealthCheck:
declarative adapters keep workload-specific code out of the core; `generic-exec` and
`systemd --user` are natively integrated without managing third-party lifecycles, while
Docker/Kubernetes only receive exported artifacts; TUN and non-loopback listeners are available
only in system scope and never via self-escalation. TUN and non-loopback binding are restricted
to system scope, and V1 never self-escalates or uses `sudo`.
