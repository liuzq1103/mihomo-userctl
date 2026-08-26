# 故障排查

## 电脑或服务器停电重启后

服务设计为 `disabled`，所以不会自动启动：

```bash
mihomoctl status
mihomoctl start
```

启动成功只代表 loopback 代理可用，当前 Shell 仍为 direct。需要代理某条命令时
使用 `with_proxy`。

## `proxy_status` 显示 inconsistent

表示八个变量只设置了一部分、值不是当前凭据，或服务/listener 已不可用：

```bash
proxy_off
mihomoctl doctor
```

不要手工补齐几个变量；修复服务或凭据后重新执行 `proxy_on`。

## 服务 active，但 ready 失败

```bash
mihomoctl doctor
mihomoctl logs --lines 100
ss -lntp 'sport = :17890'
```

常见原因：订阅失效、节点不可用、`config.yaml` 与 `client.env` 凭据不同、端口
不同、READY URL 被规则阻断。诊断输出不会显示密码。

## 端口被占用

停止用户服务：

```bash
mihomoctl stop
```

若仍提示占用，只做只读检查：

```bash
ss -lntp 'sport = :17890'
```

不要杀死未知 sshd、其他用户进程或范围外端口。确认归属前停止切换并联系管理
员。`mihomo-userctl` 不会自动清理端口。

## Codex Remote 启动失败

Codex 专用 hook 采用 fail closed：

```bash
mihomoctl start
mihomoctl ready
mihomoctl doctor
```

三项通过后正常重连 Codex。不要让普通 `.bashrc` 自动启动服务；否则会改变
“重启后默认不运行”的设计。

## `client.env must have mode 600`

确认文件属于当前用户后：

```bash
chmod 600 "$HOME/.config/mihomo/client.env"
```

如果所有者不是当前用户，不要用管理员账户强行修改未知文件；先查明来源。

## 怎样确认 axel 没走 Mihomo

在运行下载的同一个 Shell：

```bash
proxy_status
env | grep -iE '^(http|https|all|no)_proxy='
```

应显示 `shell=direct` 且第二条无输出。还可观察 Mihomo 日志或连接统计，确认下载
域名未进入 Listener。Mihomo 正在监听并不代表普通下载会经过它。
