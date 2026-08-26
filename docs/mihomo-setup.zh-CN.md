# 从零配置用户级 Mihomo

本教程解释完整结构，但 `mihomo-userctl` v0.1 不自动执行这些安装步骤。不要把
真实订阅 URL、用户名或密码提交到 Git。

## 1. 目录和权限

```bash
install -d -m 700 "$HOME/.local/bin"
install -d -m 700 "$HOME/.config/mihomo"
install -d -m 700 "$HOME/.local/share/mihomo/proxy_providers"
install -d -m 700 "$HOME/.config/systemd/user"
```

将经过 SHA256 验证的官方 Mihomo 二进制安装为：

```text
~/.local/bin/mihomo       mode 755
```

下载资产时应固定版本、资产名和官方摘要；先在候选路径执行 `mihomo -v`，再
原子替换正式文件。

## 2. 生成 Listener 凭据

在服务器本地生成随机值，不要把秘密放进命令历史。推荐用户名为随机标识，
密码至少使用 32 字节密码学随机数。真实凭据只进入权限 `600` 的配置和
`client.env`。

若用户名或密码包含 `: / @ ? #` 等 URL 保留字符，写入 `client.env` 前必须
进行百分号编码。最简单的办法是生成只含十六进制字符的密码。

## 3. 最小 config.yaml 结构

下面是结构示例，不是可直接包含真实订阅的文件：

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

rules:
  - DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT
  - DOMAIN-SUFFIX,github.com,Ai+
  - DOMAIN-SUFFIX,chatgpt.com,Ai+
  - MATCH,DIRECT
```

关键点：

- 不设置全局 `mixed-port`；
- Listener 只绑定 `127.0.0.1`；
- 必须认证；
- 不配置 TUN、external-controller、external-ui；
- provider 缓存相对于 Mihomo HomeDir；
- 订阅由服务器直接获取；
- 最后一条规则为 `MATCH,DIRECT`；
- 大数据域名应使用精确 DIRECT，避免粗暴直连整个云厂商域名。

保存后：

```bash
chmod 600 "$HOME/.config/mihomo/config.yaml"
"$HOME/.local/bin/mihomo" -t \
  -d "$HOME/.local/share/mihomo" \
  -f "$HOME/.config/mihomo/config.yaml"
```

## 4. 用户级 systemd service

`~/.config/systemd/user/mihomo.service`：

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
systemctl --user is-enabled mihomo
```

期望最后一条输出 `disabled`。不要执行 `enable`、`loginctl enable-linger`、
`sudo systemctl`，也不要创建 `/etc/systemd/system` 服务。

## 5. client.env

```ini
MIHOMO_HTTP_PROXY='http://username:password@127.0.0.1:17890'
MIHOMO_HTTPS_PROXY='http://username:password@127.0.0.1:17890'
MIHOMO_ALL_PROXY='socks5h://username:password@127.0.0.1:17890'
```

```bash
chmod 600 "$HOME/.config/mihomo/client.env"
```

## 6. 安装控制层并验收

```bash
./install.sh --port 17890 --bashrc "$HOME/.bashrc"
exec bash
proxy_status
mihomoctl doctor
with_proxy curl https://chatgpt.com
```

未认证请求必须失败；认证 HTTP 和 SOCKS5H 请求必须成功。普通新 Shell 必须
显示 `shell=direct`。
