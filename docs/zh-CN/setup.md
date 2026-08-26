# 从安装 Mihomo 开始配置完整环境

这是一份“新 Linux 用户从零开始”的教程。顺序是：安装 Mihomo 核心 → 创建
认证 Listener 和个人策略 → 创建用户服务 → 创建客户端凭据 → 安装
`mihomo-userctl`。控制层本身不会替你下载或升级 Mihomo。

不要把订阅 URL、Listener 用户名、密码或完整 `client.env` 提交到 Git、粘贴到
issue，或直接写在命令参数中。示例端口 `17890` 必须按每个用户分别选择。

## 1. 只读预检

```bash
uname -s
uname -m
getconf LONG_BIT
ldd --version 2>&1 | head -n 1
bash --version | head -n 1
systemctl --user show-environment >/dev/null && echo 'systemd user manager: ready'
command -v curl gzip sha256sum ss journalctl openssl
env | grep -iE '^(http|https|all|no)_proxy=' || true
ss -lntp 'sport = :17890'
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

## 3. 创建私有目录和 Listener 凭据

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

## 4. 创建 `config.yaml`

用本地编辑器创建 `~/.config/mihomo/config.yaml`，然后立即 `chmod 600`。完整
最小结构如下；把三个 `replace-...` 占位符替换为本地秘密：

```yaml
allow-lan: false
mode: rule
log-level: info
ipv6: false

listeners:
  - name: authenticated-loopback
    type: mixed
    listen: 127.0.0.1
    port: 17890
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
  - name: Ai+
    type: url-test
    use: [subscription]
    url: https://www.gstatic.com/generate_204
    interval: 600
  - name: 学术搜索
    type: select
    proxies: [Ai+, DIRECT]
  - name: 学术访问
    type: select
    proxies: [DIRECT, Ai+]

rules:
  - DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT
  - DOMAIN-SUFFIX,github.com,Ai+
  - DOMAIN-SUFFIX,chatgpt.com,Ai+
  - MATCH,DIRECT
```

关键约束：没有全局 `mixed-port`、TUN、`external-controller`、Dashboard 或
路由修改；Listener 只绑定 `127.0.0.1` 且必须认证；provider 缓存位于 Mihomo
HomeDir；SEA-AD 只精确直连确认的域名，不粗暴直连整个 `amazonaws.com`；最后
固定 `MATCH,DIRECT`。真实策略可扩展，但必须保留这些安全不变量。

```bash
chmod 600 "$HOME/.config/mihomo/config.yaml"
"$HOME/.local/bin/mihomo" -t \
  -d "$HOME/.local/share/mihomo" \
  -f "$HOME/.config/mihomo/config.yaml"
```

配置测试失败时不要创建或启动服务。错误输出如含 provider 信息，分享前脱敏。

## 5. 创建用户级 systemd service

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
ss -lntp 'sport = :17890'
```

期望 `active`、`disabled`，且只看到 `127.0.0.1:17890`。绝不执行 `enable`、
`loginctl enable-linger`、`sudo systemctl`，也不创建系统级 unit。重启或停电后
服务不自动运行是设计目标，不是故障。

## 6. 创建 `client.env`

创建 `~/.config/mihomo/client.env`，使用与 Listener 完全相同的用户名、密码和
端口：

```ini
MIHOMO_HTTP_PROXY='http://username:password@127.0.0.1:17890'
MIHOMO_HTTPS_PROXY='http://username:password@127.0.0.1:17890'
MIHOMO_ALL_PROXY='socks5h://username:password@127.0.0.1:17890'
```

```bash
chmod 600 "$HOME/.config/mihomo/client.env"
stat -c '%U %a %n' "$HOME/.config/mihomo/config.yaml" \
  "$HOME/.config/mihomo/client.env"
```

如果不是十六进制凭据，URL 用户信息必须正确百分号编码。不要 `source`
`client.env`；`mihomo-userctl` 会用白名单解析它。

## 7. 安装 `mihomo-userctl`

在仓库根目录先测试，再 dry-run：

```bash
bash tests/test.sh
bash tests/docs-test.sh
bash tests/secret-scan.sh
./install.sh --dry-run --port 17890 --bashrc "$HOME/.bashrc"
./install.sh --port 17890 --bashrc "$HOME/.bashrc"
exec bash
```

安装器不会启动或 enable 服务，也不会覆盖现有 `client.env`。

## 8. 验收

```bash
proxy_status
mihomoctl doctor
mihomoctl ready
systemctl --user is-enabled mihomo
```

新 Shell 应为 `shell=direct service=up endpoint=127.0.0.1:17890`，enable 状态
必须为 `disabled`。未认证请求必须失败：

```bash
curl --fail --silent --show-error --max-time 10 \
  --proxy http://127.0.0.1:17890 https://example.com/ && echo 'ERROR: auth bypass'
```

随后验证显式代理和父 Shell 隔离：

```bash
with_proxy curl --fail --silent --show-error https://example.com/ >/dev/null
proxy_status
```

仍应为 direct。要专门验证 SOCKS5H，可在临时子 Shell 中先 `proxy_on`，清除
HTTP/HTTPS 变量，只保留 `ALL_PROXY/all_proxy` 后运行 curl，退出子 Shell 后
父 Shell 不受影响。

普通 `axel`/S3 下载前检查 `proxy_status` 为 direct。Mihomo 正在监听不等于
普通程序会经过它。

## 9. 停止、重启与回滚

```bash
mihomoctl stop
mihomoctl start
mihomoctl restart
mihomoctl logs --lines 100
```

`stop` 端口未释放时只会报错，不会杀进程。回滚控制层使用安装器打印的
`.bashrc` 备份；回滚 Mihomo 二进制使用步骤 2 的精确备份；配置或 unit 回滚前
先停止用户服务，再恢复自己的备份、运行 `mihomo -t` 和 `daemon-reload`。

不要把 Windows SSH RemoteForward 恢复成长期方案，也不要清理归属不明的
`127.0.0.1:7890`。
