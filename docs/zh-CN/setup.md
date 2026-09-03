# 从安装 Mihomo 开始配置完整环境

这是一份“新 Linux 用户从零开始”的教程。顺序是：安装 Mihomo 核心 → 创建
认证 Listener 和个人策略 → 创建用户服务 → 创建客户端凭据 → 安装
`mihomo-userctl`。控制层本身不会替你下载或升级 Mihomo。

不要把订阅 URL、Listener 用户名、密码或完整 `client.env` 提交到 Git、粘贴到
issue，或直接写在命令参数中。项目没有默认端口；同一服务器上的每个用户必须
选择不同端口。

## 1. 只读预检

```bash
uname -s
uname -m
getconf LONG_BIT
ldd --version 2>&1 | head -n 1
bash --version | head -n 1
systemctl --user show-environment >/dev/null && echo 'systemd user manager: ready'
command -v curl gzip sha256sum ss journalctl openssl
proxy_var_count=0
for name in http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
  [[ -n ${!name:-} ]] && proxy_var_count=$((proxy_var_count + 1))
done
printf 'proxy_vars_present=%s/8\n' "$proxy_var_count"
```

期望 Linux、64 位、Bash 5+，并且候选端口没有未知监听。若 systemd 用户管理器
不可用、端口归属不明或某一步需要 sudo，先停止；本教程不授权使用管理员账户。

## 2. 从官方 Release 安装 Mihomo

只从 [MetaCubeX/mihomo 官方 Releases](https://github.com/MetaCubeX/mihomo/releases)
选择固定版本和与 CPU/指令集匹配的资产。不要把教程示例理解为“永远最新版”。

下面是经过固定的 amd64 compatible 示例：Mihomo `v1.19.30`，资产
`mihomo-linux-amd64-compatible-v1.19.30.gz`，SHA256
`db214c7a2517e63c150d123178d16d102e03a241ccdae4e5e07ffbe9cf56c6f9`。
其他版本或架构必须从对应官方 Release 重新取得摘要，不能复用这个值。

```bash
umask 077
install -d -m 700 "$HOME/.local/bin"
install -d -m 700 "$HOME/.local/share/mihomo/downloads"

MIHOMO_VERSION='v1.19.30'
MIHOMO_ASSET='mihomo-linux-amd64-compatible-v1.19.30.gz'
MIHOMO_SHA256='db214c7a2517e63c150d123178d16d102e03a241ccdae4e5e07ffbe9cf56c6f9'
MIHOMO_DOWNLOAD_DIR=$(mktemp -d "$HOME/.local/share/mihomo/downloads/install.XXXXXX")

curl --fail --location --proto '=https' --tlsv1.2 \
  "https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/${MIHOMO_ASSET}" \
  --output "$MIHOMO_DOWNLOAD_DIR/$MIHOMO_ASSET"

printf '%s  %s\n' "$MIHOMO_SHA256" "$MIHOMO_DOWNLOAD_DIR/$MIHOMO_ASSET" \
  | sha256sum --check --strict

gzip --decompress --stdout "$MIHOMO_DOWNLOAD_DIR/$MIHOMO_ASSET" \
  > "$MIHOMO_DOWNLOAD_DIR/mihomo.candidate"
chmod 755 "$MIHOMO_DOWNLOAD_DIR/mihomo.candidate"
"$MIHOMO_DOWNLOAD_DIR/mihomo.candidate" -v
```

只有摘要显示 `OK` 且候选版本正确时才安装。已有正式二进制时先备份，再用同一
文件系统中的候选原子替换；不要边下载边覆盖活动文件。

```bash
if [[ -e "$HOME/.local/bin/mihomo" ]]; then
  cp -p "$HOME/.local/bin/mihomo" \
    "$HOME/.local/bin/mihomo.backup.$(date +%Y%m%d-%H%M%S)"
fi
mv "$MIHOMO_DOWNLOAD_DIR/mihomo.candidate" "$HOME/.local/bin/mihomo"
chmod 755 "$HOME/.local/bin/mihomo"
"$HOME/.local/bin/mihomo" -v
```

## 3. 获取控制层源码并选择用户专属端口

调用本项目的任何脚本前，先在当前用户拥有的目录中获取并审阅固定版本。
例如：

```bash
MIHOMO_USERCTL_REF='REPLACE_WITH_APPROVED_TAG_OR_FULL_COMMIT'
git clone --no-checkout \
  https://github.com/liuzq1103/mihomo-userctl.git "$HOME/mihomo-userctl"
cd "$HOME/mihomo-userctl"
git remote -v
git checkout --detach "$MIHOMO_USERCTL_REF"
git rev-parse HEAD
```

先把引用占位符替换为已审核、包含验收脚本的固定已发布标签，并核对其 commit；
如需使用尚未发布的改进，必须明确批准固定的完整 commit 并记录来源偏差。
旧标签可能不含本教程的新验收脚本，不得沿用旧标签后声称新检查已通过。

如果目标目录已存在，应先检查并复用，不要直接覆盖。不使用 `curl | bash`。
本文后续命令均假定当前目录是这份已验证的代码检出。

在 `mihomo-userctl` 仓库根目录运行只读建议器：

```bash
PROXY_PORT=$(./install.sh --suggest-port)
printf '候选端口=%s\n' "$PROXY_PORT"
ss -lnt "sport = :$PROXY_PORT"
```

建议器从 `20000–29999` 中、以当前 UID 推导的位置为起点寻找当时未监听的
候选值，但不会绑定或预留它。必须由用户确认，与同服务器其他用户协调，并在
启动 Mihomo 前再次运行 `ss`。不同用户不能同时绑定相同的回环地址和端口；
认证只能减少误用，不能解决端口绑定冲突。

也可以把 `PROXY_PORT` 改为用户选择的其他 `1024–65535` 端口。应避开现有代理
软件的惯用端口和 `ss` 已显示的任何端口。

## 4. 创建私有目录和 Listener 凭据

```bash
install -d -m 700 "$HOME/.config/mihomo"
install -d -m 700 "$HOME/.local/share/mihomo"
install -d -m 700 "$HOME/.local/share/mihomo/proxy_providers"
install -d -m 700 "$HOME/.local/share/mihomo/backups"
install -d -m 700 "$HOME/.config/systemd/user"
```

在服务器本地生成随机用户名和至少 32 字节随机密码。推荐只使用十六进制，避免
URL 百分号编码错误：

```bash
openssl rand -hex 8
openssl rand -hex 32
```

把输出直接填入本地权限 `600` 的文件，不要贴回聊天或公开日志。用户名和密码
要同时填入 Mihomo `config.yaml` 与后面的 `client.env`。

## 5. 创建 `config.yaml`

用本地编辑器创建 `~/.config/mihomo/config.yaml`，然后立即 `chmod 600`。完整
最小结构如下；把三个 `replace-...` 占位符替换为本地敏感信息：

```yaml
allow-lan: false
mode: rule
log-level: info
ipv6: false

listeners:
  - name: authenticated-loopback
    type: mixed
    listen: 127.0.0.1
    port: PORT_SELECTED_BY_USER
    udp: false
    users:
      - username: replace-with-local-username
        password: replace-with-local-password

proxy-providers:
  subscription:
    type: http
    url: "replace-with-private-subscription-url"
    path: ./proxy_providers/subscription.yaml
    interval: 86400
    proxy: DIRECT
    size-limit: 5242880
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 600

proxy-groups:
  - name: Proxy
    type: url-test
    use: [subscription]
    url: https://www.gstatic.com/generate_204
    interval: 600

rules:
  - DOMAIN-SUFFIX,github.com,Proxy
  - DOMAIN-SUFFIX,chatgpt.com,Proxy
  - DOMAIN-SUFFIX,api.openai.com,Proxy
  - DOMAIN-SUFFIX,openai.com,Proxy
  - DOMAIN-SUFFIX,google.com,Proxy
  - MATCH,DIRECT
```

关键约束：没有全局 `mixed-port`、TUN、`external-controller`、Dashboard 或
路由修改；Listener 只绑定 `127.0.0.1` 且必须认证；provider 缓存位于 Mihomo
HomeDir；最后固定 `MATCH,DIRECT`。上面的域名和 `Proxy` 组只是通用示例，不是
项目内置策略。数据集、科研站点、订阅节点和其他自定义路由必须由每位用户在
自己的 Mihomo 配置中维护，不能写成公共项目的专属要求。

```bash
chmod 600 "$HOME/.config/mihomo/config.yaml"
"$HOME/.local/bin/mihomo" -t \
  -d "$HOME/.local/share/mihomo" \
  -f "$HOME/.config/mihomo/config.yaml"
```

配置测试失败时不要创建或启动服务。错误输出如含 provider 信息，分享前脱敏。

运行配置测试前，把 `PORT_SELECTED_BY_USER` 替换为刚确认的纯数字端口。

## 6. 创建用户级 systemd service

创建 `~/.config/systemd/user/mihomo.service`：

```ini
[Unit]
Description=User-level Mihomo proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/.local/bin/mihomo -d %h/.local/share/mihomo -f %h/.config/mihomo/config.yaml
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=default.target
```

```bash
chmod 644 "$HOME/.config/systemd/user/mihomo.service"
systemctl --user daemon-reload
systemctl --user start mihomo
systemctl --user is-active mihomo
systemctl --user is-enabled mihomo
ss -lntp "sport = :$PROXY_PORT"
```

期望 `active`、`disabled`，且只看到 `127.0.0.1:$PROXY_PORT`。绝不执行 `enable`、
`loginctl enable-linger`、`sudo systemctl`，也不创建系统级 unit。重启或停电后
服务不自动运行是设计目标，不是故障。

## 7. 创建 `client.env`

创建 `~/.config/mihomo/client.env`，使用与 Listener 完全相同的用户名、密码和
端口：

```ini
MIHOMO_HTTP_PROXY='http://username:password@127.0.0.1:PORT_SELECTED_BY_USER'
MIHOMO_HTTPS_PROXY='http://username:password@127.0.0.1:PORT_SELECTED_BY_USER'
MIHOMO_ALL_PROXY='socks5h://username:password@127.0.0.1:PORT_SELECTED_BY_USER'
```

```bash
chmod 600 "$HOME/.config/mihomo/client.env"
stat -c '%U %a %n' "$HOME/.config/mihomo/config.yaml" \
  "$HOME/.config/mihomo/client.env"
```

如果不是十六进制凭据，URL 用户信息必须正确百分号编码。不要 `source`
`client.env`；`mihomo-userctl` 会用白名单解析它。

把三处 `PORT_SELECTED_BY_USER` 替换为同一个已确认数字端口；它们必须与 Mihomo
Listener 完全一致。

## 8. 安装 `mihomo-userctl`

在仓库根目录先测试，再 dry-run：

```bash
bash tests/test.sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tests/audit-test.sh
bash tests/docs-test.sh
bash tests/secret-scan.sh
./install.sh --dry-run --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
./install.sh --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
exec bash
```

安装器不会启动或 enable 服务，也不会覆盖现有 `client.env`。写入活动
文件前，它会在 `~/.local/share/mihomo-userctl-backups/` 中创建权限 `700`
的事务备份。如果最后的 `mihomoctl doctor` 失败，安装器会自动恢复
原有控制器、模块、补全、非敏感配置和 `.bashrc`，并保留备份供排查。

## 9. 验收

按[安装验收与证据要求](acceptance.md)执行，保留真实退出码与观察值：

```bash
proxy_status
mihomoctl doctor
mihomoctl ready
systemctl --user is-enabled mihomo

acceptance_rc=0
bash scripts/acceptance.sh \
  --url https://www.gstatic.com/generate_204 --expect-status 204 \
  || acceptance_rc=$?
printf 'acceptance_rc=%s\n' "$acceptance_rc"
```

脚本需要 Python 3.8+，只执行不会停服的 Listener 基线检查，并输出
PASS / FAIL / UNVERIFIED / DEFERRED。正常基线通过后仍有端到端待验证项时，
退出码为 2，不等于安装失败。不要只检查管道末尾命令的退出码。

新普通 Shell 应为 direct，服务 active 且 disabled。脚本核对实际 HTTP 状态、
本地对端、无认证 HTTP 的 407，以及 SOCKS5 明确拒绝无认证方法；网络失败不算
认证拒绝。还需独立验证 `proxy_on/off`、`with_proxy` 隔离、已安装 loader、
hook、下载连接和可选 VS Code，不能由脚本的 Listener 结果推断它们已经通过。

此示例中的 `gstatic.com` 命中 `MATCH,DIRECT`。它可验证 Listener 请求，
不能证明 Proxy 节点可用；需另选已获批且命中 Proxy 的目标，关联脱敏路由证据。
小文件下载成功不能代替 S3 或大文件的实测。

### 可选：VS Code Remote

终端 `with_proxy codex` 和 Codex Remote hook 验收成功，并不代表 VS Code
Extension Host 会继承同一环境。需要在 VS Code Remote 中使用 Codex 扩展时，
继续阅读 [VS Code Remote 推荐配置](vscode-remote.md)。该步骤必须单独选择，
会把认证 URL 写入远程 Machine Settings，并可能影响其他遵循该设置的扩展；
普通 Shell 和大型下载仍保持直连。

## 10. 停止、重启与回滚

```bash
mihomoctl stop
mihomoctl start
mihomoctl restart
mihomoctl logs --lines 100
```

`stop` 端口未释放时只会报错，不会杀进程。要回滚已成功安装的控制层，
使用[更新指南](update.md)中本次备份的精确恢复命令，不要混用不同版本模块；回滚
Mihomo 二进制使用步骤 2 的精确备份；配置或 unit 回滚前
先停止用户服务，再恢复自己的备份、运行 `mihomo -t` 和 `daemon-reload`。

回滚不能引入新的外部隧道，也不能清理无关 Listener。当前用户明确范围之外的
对象一律保持不变。

安装前备份与 after-test 快照不是一回事；全新文件须记录原先不存在。先停服，
再恢复二进制/配置并验证；彻底撤销全新安装时最后才移除二进制。控制层卸载
会保留核心、unit 和配置，详见[回滚顺序](acceptance.md#5-回滚顺序)。

后续仅更新控制层请使用[更新指南](update.md)或[更新 Prompt](agent-update-prompt.md)。
安装与更新需要 Python 3.8+。
