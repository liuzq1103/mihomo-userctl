# 从大型 `.bashrc` 代理块迁移

## 迁移前

先确认：

```bash
systemctl --user is-active mihomo
systemctl --user is-enabled mihomo
ss -lntp 'sport = :17890'
proxy_status
```

暂停迁移的情况：

- 配置端口被未知进程占用；
- `client.env` 不是当前用户所有或不是 `600`；
- `.bashrc` 中存在多个旧块或多个 managed marker；
- 正在进行不能中断的重要下载且迁移步骤需要重启服务。

本项目迁移 Shell 集成不需要重启 Mihomo，也不应中断普通 SSH。

## dry-run

```bash
./install.sh --dry-run --port 17890 --bashrc "$HOME/.bashrc"
```

dry-run 只报告将安装的文件以及 `.bashrc` 处理模式，不写入任何内容。

## 正式迁移

```bash
./install.sh --port 17890 --bashrc "$HOME/.bashrc"
```

安装器只自动识别两种情况：

1. 已存在唯一的 `mihomo-userctl managed loader`；
2. 已存在本项目明确支持的旧代理块起点和 Codex 结尾。

遇到模糊结构时安装器停止，不使用“删除所有包含 proxy 的行”之类的正则。
原 `.bashrc` 备份权限会收紧为 `600`。

## 新会话验收

不要依赖当前已加载旧函数的 Shell。新开普通 SSH 后执行：

```bash
type mihomoctl proxy_on proxy_off proxy_status with_proxy
proxy_status
mihomoctl status
mihomoctl ready
```

普通 Shell 应为 direct。然后测试父 Shell 隔离：

```bash
with_proxy curl https://github.com
proxy_status
```

第二条仍应显示 direct。

## 回滚

安装器会打印备份路径：

```text
~/.bashrc.mihomo-userctl-backup.YYYYMMDD-HHMMSS
```

回滚时先保存当前文件，再将该备份恢复为 `.bashrc`，执行 `bash -n ~/.bashrc`，
然后新开 Shell 验证。回滚 Shell 集成不需要修改 Mihomo、订阅、端口或服务。
