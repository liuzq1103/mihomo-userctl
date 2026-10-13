# systemd、容器和 CI 接入

编辑初始化后私有 manager.yaml 的 bindings，合并保留已有绑定。下面使用已存在的 default profile；target 和地址须按本机调整：

```yaml
bindings:
  worker:
    profile: default
    adapter: systemd
    target: worker.service
    connect_host: 127.0.0.1
  container:
    profile: default
    adapter: docker
    connect_host: 172.17.0.1
  pipeline:
    profile: default
    adapter: ci
```

```bash
mihomoctl config validate
mihomoctl integration check worker
mihomoctl integration install worker
```

systemd adapter 写受管 drop-in 和 integration 目录中的私有 proxy.env，再 reload 用户 unit manager。用 `mihomoctl integration show worker` 检查。它不 enable/start/stop/restart worker.service；准备好后由操作者明确重启自己的应用，已运行进程不会自动改变环境。`integration remove worker` 只删除受管接入文件，不删除用户原有 unit。

对 Mihomo 本身，可用 `mihomoctl service install` 后显式 `mihomoctl service start` 切换用户 systemd 管理；这与第三方应用 binding 不同。不会自动设置 linger 或 enable。

## 容器

172.17.0.1 只是可达主机地址的示例；容器的 loopback 指向容器自己。connect_host 只改导出的代理 URL，不会创建 listener 或开放防火墙。必须明确配置容器可达且带认证的 listener，在 manager.allow_non_loopback 授权地址，并限制网络访问。私有导出：

```bash
umask 077
mihomoctl integration export container --output-dir "$HOME/private/container-proxy"
```

输出含 docker.env 和 compose 片段。compose 片段直接引用随附的 docker.env，审阅后合并进自己的配置；也可在自己的 `docker run --env-file` 中引用 docker.env。工具不部署或重启容器。Kubernetes 同样要求 connect_host；导出 Secret 的 base64 内容仍是敏感信息。

## CI

```bash
umask 077
mihomoctl integration export pipeline --output-dir "$HOME/private/ci-proxy"
. "$HOME/private/ci-proxy/ci-env.sh"
```

在可信 runner 的明确步骤中使用，关闭命令追踪并配置秘密脱敏。不要上传导出文件或打印内容。当前 Shell 后续创建的进程继承环境，工具不运行流水线。分离 runner 需要可达 listener 和安全的私有环境传递。supervisor、pm2 也支持只导出接入配置。
