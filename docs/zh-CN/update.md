# 更新与失败恢复

完整包包含程序、解释器和界面依赖。将已核验的完整包传入服务器，然后运行：

```bash
mihomoctl update /absolute/path/to/verified-portable-bundle.tar.gz --dry-run
mihomoctl update /absolute/path/to/verified-portable-bundle.tar.gz
```

旧源码安装使用新完整包中的 `./install.sh --user` 迁移；不要求旧 updater 识别新格式。主动联网更新仍可用 `mihomoctl update --latest`，但需要已经发布通过验收的完整包及 release gate。

成功后只保留当前版本，并删除工具拥有的历史版本和备份。更新管理器不自动替换活动核心、不重启运行时、不修改用户配置及 Shell 启动文件。`mihomoctl rollback BACKUP` 返回 `historical-rollback-disabled`。

失败时先恢复本次操作前状态；中断后下次操作或界面启动时自动处理未完成事务。恢复失败或检测到外部手动修改时保留临时材料并报告，避免覆盖未知变更。历史版本不能恢复；需要重新安装时必须重新获取核验后的软件包。

安装、更新或卸载前关闭本账号所有 mihomoctl 界面，否则 `installation-console-open` 会在切换前拒绝操作；核心可继续运行。若显示已提交但清理待完成，表示新状态已经生效，下次加锁操作会重试清理，不能据此认为已恢复到旧版本或旧配置。
