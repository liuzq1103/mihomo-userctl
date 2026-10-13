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
# Paseo 代理注入：生产机实施报告

**以下步骤由人工在生产机执行。开发和回归测试不得连接或重启生产 daemon，也不得自动发起真实模型请求。**

## 因果复核与证据边界

仓库 HEAD 的 0.9.2 发布提交 `6ccc94d` 仅更新发布标记；功能提交 `66a24c3` 集中于 Controller 初始化、任务控制台和订阅导入。对比 v0.9.1/v0.9.2，代理公共模块只有版本号变化，shell 和 Codex 诊断链未变。缺少后台 daemon 启动入口属于历史覆盖缺口，回滚 0.9.2 不会给已有 daemon 添加代理环境。

初始提交 `366ffe2`（v0.1.0）已经包含普通 shell 的 `proxy_off`，因此不能把 direct-by-default 的起点写成 0.9.0。旧 daemon 曾继承历史 shell 代理环境的解释与已提供的诊断一致，但具体启动时间/环境仍待人工现场核实。

用户提供的线上证据：国内主机上的当前 Paseo worker 没有代理变量；OpenAI 直连超时/重置/地域拒绝，经认证 listener 能收到目标 HTTP 响应；Mihomo 和订阅节点正常。这些是输入证据，本次开发没有重新连接生产验证。实际端口、凭证、provider baseURL、Paseo 版本、进程身份和真实 turn 成功必须现场确认。

0.9.3 增加 daemon 进程边界、漂移检测和可选 systemd user 托管。保留普通 shell 直连、不全局导出、不使用 TUN、不更换他人端口或终止他人进程的约束。

## 维护前检查

使用运行 daemon 的目标用户登录，先检查 agent 是否仍在运行，并安排维护窗口：

```bash
paseo --version
paseo daemon status --json
paseo ls
mihomoctl version
mihomoctl doctor --offline --json
```

确认 home 与目标实例一致；非默认实例给后续 mihomoctl paseo 命令添加 `--home /absolute/path`，同时为 Paseo CLI/诊断设置同一 `PASEO_HOME`。不要通过远程 host 选择器执行本流程。保留配置文件和当前已安装版本的私有备份。

按[升级指南](update.md)安装 0.9.3；控制层安装不应重启任何 daemon。按[使用指南](paseo.md)维护直连清单，核对国内 provider 的实际 baseURL。执行：

```bash
mihomoctl ready --json
mihomoctl paseo preflight --json
```

漂移时 BLOCKED 是预期结果，不代表应该回滚工具。UNVERIFIED 必须先查明权限、CLI 接口或身份问题，不能强制跳过。

## 经 listener 的独立探测

下面仅在子进程中注入凭证，不在 argv 中放代理 URL，也不全局 source/export client.env；端口由已有配置选择：

```bash
mihomoctl exec -- bash --noprofile --norc -c '
for host in chatgpt.com api.openai.com auth.openai.com; do
  printf "%s " "$host"
  rc=0
  curl --disable --head --globoff --proto =https --silent --show-error \
    --noproxy "" --max-time 10 --output /dev/null \
    --write-out "http=%{http_code} connect=%{http_connect} peer=%{remote_ip}:%{remote_port} seconds=%{time_total}\n" \
    "https://$host/" || rc=$?
  printf "curl_rc=%s\n" "$rc"
done'
```

要求 curl_rc=0、CONNECT=200、peer 为配置的回环 listener，且有目标 HTTP 状态；403/421 可用于确认连通，不能当作模型可用。preflight 另行提供强制直连结果；必要性未证实并不会阻止代理启动。

## 人工切换与开机常驻

**以下停止和启动会中断 agent，仅在已安排的维护窗口执行。** 首次切换到 systemd：

```bash
# 尚未由 systemd 托管时：完整停止旧 supervisor，不用 worker restart。
paseo daemon stop
mihomoctl paseo install-unit --dry-run
mihomoctl paseo install-unit
loginctl enable-linger "$USER"
systemctl --user enable --now paseo.service
systemctl --user status paseo.service --no-pager
mihomoctl paseo preflight --json
```

如果系统策略拒绝 enable-linger，由管理员为该用户启用，不改为系统级全局代理。Mihomo user unit 必须已存在；Paseo unit 的 Requires/After 会在启动时拉起它。单元自身含 Restart=on-failure，不保存凭证值。

暂不使用 systemd 时，在维护窗口运行 `mihomoctl paseo restart`，然后同样复验。已经托管时使用 `mihomoctl paseo restart` 或 `systemctl --user restart paseo.service`；不要另起裸 `paseo start`。

## /proc 环境验证与真实 turn

从新状态中记录 supervisor PID；从 preflight 的 `daemon.processes` 记录 worker PID。通过 provider diagnostic/进程树定位新 Codex PID，仅检查当前用户目标进程：

```bash
paseo daemon status --json
mihomoctl paseo preflight --json
paseo provider diagnostic codex --json

# 人工填写新 PID；不要使用旧 PID 或其他用户的 PID。
supervisor_pid=REPLACE_WITH_SUPERVISOR_PID
worker_pid=REPLACE_WITH_WORKER_PID
codex_pid=REPLACE_WITH_CODEX_PID
mihomoctl paseo exec -- python3 - "$supervisor_pid" "$worker_pid" "$codex_pid" <<'PY'
import os, pathlib, sys
names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
for arg in sys.argv[1:]:
    pid = int(arg)
    root = pathlib.Path("/proc") / str(pid)
    def identity():
        status = root.joinpath("status").read_text().splitlines()
        uid = int(next(x for x in status if x.startswith("Uid:")).split()[1])
        if uid != os.getuid():
            raise SystemExit("refusing foreign UID")
        return root.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
    before = identity()
    values = {}
    for item in root.joinpath("environ").read_bytes().split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            if key.decode(errors="replace") in names + tuple(x.lower() for x in names):
                if key in values:
                    raise SystemExit("duplicate proxy variable")
                values[key] = value
    if identity() != before:
        raise SystemExit("PID changed during inspection")
    matches = all(values.get(key.encode()) == os.environ[key].encode()
                  for upper in names for key in (upper, upper.lower()))
    print("pid={} proxy_vars={}/8 matches_current_config={}".format(pid, len(values), matches))
    if not matches:
        raise SystemExit(1)
PY
```

若尚无 Codex 进程，先执行下述冒烟，再定位新 PID 复验。provider diagnostic 原始输出可能含路径等私有信息，分享前脱敏。

```bash
smoke_dir=$(mktemp -d "${TMPDIR:-/tmp}/paseo-codex-smoke.XXXXXX")
chmod 700 "$smoke_dir"
(
  cd "$smoke_dir"
  paseo run --provider codex "仅回复 OK，不修改任何文件"
)
```

验收要求：通过 Paseo daemon 的真实 Codex turn 完成并回复 OK；不能仅凭 provider 模型列表或 curl 成功验收。若仍失败，保留脱敏 turn 错误、provider diagnostic 和 `journalctl --user -u paseo.service --since '-10 minutes'`，区分网络、登录、模型和 provider 配置问题。

## 轮换、停用与回退

凭证轮换后保持 client.env 的 owner/0600，并在维护窗口重启 Paseo 单元，重跑 preflight、/proc 校验和 listener 探测。直连清单变化采用相同流程；不需要重装 unit。路径或 PATH 改变时重新 install-unit，再重启。

人工停用：`systemctl --user disable --now paseo.service`。确认文件首行是本工具的 managed 标记后，人工删除该单元并 daemon-reload；不要删除其他来源的 unit。卸载工具前先执行停用。

需要回退控制层时，先停用此新增单元，再按[升级/回退指南](update.md)恢复已有安装代；保留 client.env、核心配置和订阅。回到 0.9.2 不会修复 daemon 的环境缺口，不应自动启动直连 daemon，也不建议恢复历史全局 shell 代理。

## 开发验证记录

回归使用私有 HOME、假网络/服务 CLI、假 /proc，以及实际 Linux supervisor/worker/Codex 替身。没有连接 MainServer，没有重启生产 Paseo，没有执行真实模型请求。本地 Linux/Python 3.10 回归：285 项 unittest 通过（5 项条件跳过：真实核心和 Node 可选检查），其中 Paseo 专项 33 项；Shell 53 项、安装审计 6 项通过。语法、ShellCheck、文档、秘密扫描及 git diff --check 均通过。systemd-analyze --user verify 返回 0；开发环境没有可用的 systemd user bus，未验证真实单元启停，也未执行 CI 的 Python 版本矩阵。生产验收只能由上述人工步骤补齐。
