# 安全边界

默认 user 作用域和 process 后端。不自动 sudo/提权，不改 Shell 启动文件，不设置全局代理，不操作第三方服务生命周期。root 的变更须明确选择 --system；TUN 仅允许明确的 system 操作。

exec 必须通过本地健康检查，否则拒绝启动；direct 清除八个标准代理变量，但两者都不能强制应用遵守环境代理。Controller 凭据与消费端代理凭据分离。凭据保存于私有文件，仅显式 reveal/export 会披露；不能记录导出内容或把订阅 URL 放进参数。配置错误不回显输入的秘密值。

规则检查只读。订阅 apply 在激活前核验原配置摘要、候选 SHA256、字段白名单及核心验证，保留备份/回滚。Node JS override 是可信本地代码执行，Node vm 不是沙箱；不得运行不可信脚本。

更新和卸载保留配置、凭据、订阅、缓存、核心。代码路径必须由本人/root 拥有且不可被组或其他人写入。发布清单逐文件授权；scripts 和 legacy 不进入 wheel 运行时。安全问题参见 [SECURITY.md](../../SECURITY.md)。
