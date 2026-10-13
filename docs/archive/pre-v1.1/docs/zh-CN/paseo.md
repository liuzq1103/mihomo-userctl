<!-- ARCHIVED: retired in v1.0.0. The daemon lifecycle this page documents no
     longer exists. Keep the file for historical reference only; do not follow
     its commands. -->

# 【已归档】Paseo 后台 daemon 代理注入

> **状态：历史归档，命令面已在 v1.0.0 退役。**
>
> v1.0.0 移除了对第三方 daemon 生命周期的管理。`mihomoctl paseo start|stop|restart|run|install-unit`
> **不再存在**；旧调用会返回迁移指引，**不会**启动、停止或替换任何第三方进程或单元。
>
> **请改用** [V1 命令与配置契约](v1.md) 中的通用接入：
>
> | 你原来想做的 | V1 做法 |
> | --- | --- |
> | 让后台服务走代理 | `mihomoctl --system integration install NAME` 为你自己的单元写受管 drop-in + `proxy.env`，再由**你自己**执行 `daemon-reload` |
> | 临时让某个命令走代理 | `mihomoctl exec -- COMMAND` |
> | 检查代理是否可用 | `mihomoctl health` |
> | 让容器走代理 | `mihomoctl integration export container-worker --output-dir "$HOME/.config/mihomoctl/export-container"`（可达地址在 `manager.yaml` 的 `connect_host` 声明；容器内 `127.0.0.1` 不是宿主机回环） |
>
> 本工具**永远不会**自动停止第三方应用。历史遗留单元只会被检测并报告。
>
> 以下内容仅供追溯当时的实现与决策，**不是当前操作指南**。

---
# Paseo 后台 daemon 代理注入

从 0.9.3 起，Paseo 可以在进程启动边界继承经验证的 Mihomo 代理。普通 shell 仍默认直连，不修改 TUN、系统代理、路由规则或其他用户的进程。完整生产切换见[人工实施报告](paseo-production.md)。

## 检查与启动

```bash
mihomoctl paseo preflight --json
mihomoctl paseo start
mihomoctl paseo exec -- COMMAND ARGUMENTS
```

preflight 返回 `SAFE_TO_LAUNCH`（0）、`BLOCKED`（1）或 `UNVERIFIED`（2）。检查 Mihomo 服务、listener 绑定、HTTP/SOCKS 匿名拒绝、凭证、ready 健康，以及 chatgpt.com、api.openai.com、auth.openai.com 的直连/代理路径。代理探测要求实际对端为所选回环 listener、CONNECT 200、TLS 成功和目标 HTTP 响应。403、421 等响应仅证明网络可达；`model_request` 和远程传输仍为 `UNVERIFIED`。直连恢复不阻止代理启动，必要性单独报告。

命令默认选择 `PASEO_HOME` 或 `~/.paseo`；可用 `--home /absolute/path` 指定另一个本地实例。忽略 `PASEO_HOST`，不提供远程 daemon 控制。支持具备 `daemon start/run/stop/status --home` 和本地状态 JSON 的 Paseo CLI；本次对照 0.11.2 接口。未知版本/状态结构、不完整进程身份或不可读环境均拒绝推断安全，不自动升级 Paseo。

已运行且健康的 daemon 上重复 `start` 不重启。已有环境漂移时，`start` 和 `exec` 拒绝启动并指向以下命令：

```bash
# 会中断现有 agent，由人工安排维护窗口执行。
mihomoctl paseo restart
```

完整重启先验证代理与选定 home 的当前用户 supervisor/worker 身份，再经 Paseo CLI stop/start；原生 `paseo daemon restart` 只换 worker，会保留 supervisor 的旧环境，不能修复本问题。工具不使用 `--force`，不自行杀进程；停止失败不继续启动。新进程必须具有当前八个代理变量，并再次通过 ready 和 OpenAI listener 探测，才能报告成功。启动失败不恢复为直连 daemon。

`exec` 原样传递参数、退出码，仅给新命令注入环境；不能修改已有进程。`doctor [--offline] [--json]` 增加 Paseo 漂移项。离线告警标明仅依据 provider 配置判断 OpenAI 依赖，不能证明当前网络封锁。

## 国内 provider 与 NO_PROXY

每次启动安全读取 `client.env`，成对设置 `HTTP_PROXY/http_proxy`、`HTTPS_PROXY/https_proxy`、`ALL_PROXY/all_proxy` 和 `NO_PROXY/no_proxy`。代理 URL 含凭证，但不会进入命令参数、诊断输出或生成的 unit。

NO_PROXY 必含 `127.0.0.1,localhost,::1,relay.paseo.sh`，保护 Paseo 与 Codex app-server 的本机 HTTP/MCP 通信。可选配置位于 `${XDG_CONFIG_HOME:-$HOME/.config}/mihomo/paseo-proxy.json`，必须当前用户所有、0600、普通文件：

```bash
# 在源代码目录执行；已有配置时请人工合并，不覆盖个人清单。
install -m 600 examples/paseo-proxy.json \
  "${XDG_CONFIG_HOME:-$HOME/.config}/mihomo/paseo-proxy.json"
```

- `direct_domains`：直接加入 NO_PROXY 的主机清单；提供此字段会替换内置可选清单，固定四项仍保留。
- `opencode_allowed_domains`：允许从 OpenCode baseURL 发现主机的域名范围，匹配域名本身及其子域；仅加入实际发现的完整主机。
- `opencode_config_files`：补充配置文件的绝对路径，如项目专用配置。

默认覆盖智谱、DeepSeek、MiniMax API。读取全局 `opencode/opencode.json` / `.jsonc`、`OPENCODE_CONFIG`、补充文件和当前启动环境的 `OPENCODE_CONFIG_CONTENT`，提取 `provider.*.options.baseURL` 的主机并取并集；这只是域名发现，不实现 OpenCode 全部配置合并逻辑。不遍历工作区、不执行配置、不读取 `{file:...}` 或输出 API key。baseURL 的 `{env:NAME}` 只从当前启动环境解析；未解析值会阻止启动。未获准主机在 `pending_direct_domains` 中提示，仍使用代理。OpenAI 等代理域名不会从 provider 配置自动加入直连清单；显式冲突清单和通配符被拒绝。

已验证的 Paseo 进程树中的 Codex 可使用此扩展清单；独立 Codex 仍使用原有严格门禁。检查非默认实例时，为诊断命令设置同一 `PASEO_HOME`。

## systemd user 托管

```bash
mihomoctl paseo install-unit --dry-run
mihomoctl paseo install-unit
```

生成 `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/paseo.service`，只执行 daemon-reload，不 enable/start。相同内容重复安装不改写；拒绝覆盖其他来源或其他 home 的 unit。只支持一个此名称的 user unit；其他实例仍可手动管理。

单元固定稳定 mihomoctl/Paseo 路径、home、安装时 PATH 和配置路径，`ExecStart` 使用 `mihomoctl paseo run`，`ExecStop` 使用 Paseo 自身 stop。`run` 保持前台，验证 worker 后等待 supervisor 生命周期并传递退出/信号；已有实例时拒绝附着。设置 `Restart=on-failure`、`RestartSec=10`，依赖所选 Mihomo user service，因此无需改变 Mihomo 的 enabled/disabled 策略。Mihomo unit 必须已存在。

**首次切换由人工在生产机执行**：安排维护窗口，停止旧 daemon 后再启用单元；详见[实施步骤](paseo-production.md)。开机常驻需 `loginctl enable-linger "$USER"`，按系统策略可能需要管理员协助。

凭证仅在每次启动时从 `client.env` 读取，unit 不保存凭证值。轮换凭证或修改直连清单后，在维护窗口运行 `systemctl --user restart paseo.service` 并复验。改动二进制路径、PATH 或配置文件路径时重新安装 unit，然后重启。systemd 不继承交互 shell 的任意变量；使用文件中的显式 baseURL，或自行维护必要的非秘密环境设置。`install-unit` 拒绝将含密钥的 `OPENCODE_CONFIG_CONTENT` 固化到单元。

工具识别到托管 unit 时，start/restart 经 systemd，且运行中的目标必须属于对应 cgroup；不竞争 systemd 的自动重启。失败详情查看 Paseo home 的日志和 `journalctl --user -u paseo.service`。卸载工具前先人工 stop/disable Paseo 单元。

接口依据：[Paseo CLI](https://paseo.sh/docs/cli)、[OpenCode 配置](https://opencode.ai/docs/config/)。
