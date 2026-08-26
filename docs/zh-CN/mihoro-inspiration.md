# 从 Mihoro 借鉴什么，以及明确不照搬什么

本项目研究了 [spencerwooo/mihoro](https://github.com/spencerwooo/mihoro) 的
产品设计。Mihoro 不是本项目的依赖、fork 或源码基础。

## 借鉴的理念

- 无 root、每用户独立安装；
- 用统一 CLI 管理 `systemctl --user` 生命周期；
- 配置与程序分离，不硬编码用户和路径；
- 幂等安装，以及一致的 status、logs、help、补全接口；
- 把上手、日常维护和排错都作为正式文档。

## 明确不同

Mihoro 的生命周期范围更广，可以初始化或更新 Mihomo core、远程配置、geodata、
Dashboard、cron 和服务。`mihomo-userctl` v0.1 假定 Mihomo 核心与配置已经存在，
只管理用户服务和 Shell 是否显式进入代理。

Mihoro 文档使用 `eval $(mihoro proxy export)`；本项目不生成代码供 `eval`。
Shell 模块经过所有者和权限校验后才 source，凭据文件始终作为白名单数据解析。

本项目坚持服务 `disabled`、手动启动、带认证的 loopback-only Mixed Listener、
无 controller、无 Dashboard、无 TUN、无系统路由修改，并同时管理大小写八个
代理变量。Mihomo 内部规则和订阅仍完全归用户所有。

Mihoro 和本项目都采用 MIT，但本项目为原创 Bash 实现，没有复制 Mihoro 源码、
品牌、Logo 或资产。
