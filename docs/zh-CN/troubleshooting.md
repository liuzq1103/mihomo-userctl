# 安装与运行排障

- 只有 mihomoctl、没有 Mihomo：控制器包不含核心。新装按 [初始化教程](setup.md) 复用可信核心或显式安装固定版本，再 init 一次；已有 manager 不重复初始化，也不盲目 core install。
- NAS 或 wheelhouse 权限被拒：复制所需整套材料到本人私有目录再核验，不递归放宽权限。核对 [两种离线包布局](offline-install.md)。
- Python/目标不匹配：核对 Linux 发行版、架构和 Python；不要把其他目标套件强装。严格离线缺核心或依赖时提前准备。
- 安装脚本后续下载 DNS 失败：检查整个安装 Shell 是否在 exec 内；外层管道右侧不会继承左侧变量。
- Bash 报 `<` / HTML 语法错误：下载到的可能是地区限制或登录网页。curl -f 不拒绝 HTTP 200 HTML。停止执行，按 [下载审阅与代理继承教程](first-run.md#通过代理安装第三方-cli) 检查，不关闭 TLS 校验。
- init 成功但 exec 被健康门阻止：默认初始化不启动。准备好后显式 start，检查配置、端口和日志。不要用尚未运行的代理下载自身核心。
- 本地请求成功却未走远端：默认 MATCH,DIRECT；检查订阅、规则、NO_PROXY 和真实客户端连接链，见 [分层验证](first-run.md)。

报告控制器、核心、初始化、运行态及真实远端请求各阶段的 PASS/FAIL/UNVERIFIED。不要上传原始凭据或连接明细。
