# Fixed-link installation

[English overview](../../README.en.md) · [简体中文](../zh-CN/quick-install.md)

```bash
curl -fsSL https://raw.githubusercontent.com/liuzq1103/mihomo-userctl/main/bootstrap.py -o mihomo-userctl-bootstrap.py && python3 mihomo-userctl-bootstrap.py
```

Download the complete script into the current directory before running it. Unpublished development code is never treated as a stable release. No Coding Agent is required.
The default is the latest stable GitHub Release. To pin or preview:

```bash
python3 mihomo-userctl-bootstrap.py --version vX.Y.Z --dry-run
python3 mihomo-userctl-bootstrap.py --version vX.Y.Z --port YOUR_PROXY_PORT
```

Replace placeholders with an actual published tag and unused numeric port. A fresh installation without `--port` calls
the release's `install.sh --suggest-port` and passes that port explicitly to the installer. Existing installations retain
their port/path contract. A dry run downloads the release but does not install the control layer.

This installs **the control layer only**. It does not prepare Mihomo, subscriptions, configuration or service units, start
services, change global proxies or elevate privileges. Follow [full setup](setup.md), [local archives](offline-install.md),
or [nodes and dashboards](control-plane.md) as appropriate. Existing dependencies and authorization remain applicable.
Installed users should prefer the existing [update command](update.md).

Trust: the bootstrap link tracks main and relies on GitHub HTTPS and the repository maintainers. Inspect it before execution.
It accepts published stable releases, resolves tags to immutable commits, then downloads that source archive. It rejects
traversal, links, oversized archives and manifest/version mismatches, recording provenance and a local SHA256.
That digest records downloaded content; it is **not independent signature verification**. Downloads can use an existing
caller proxy without printing its value or upstream error bodies. Never pass subscriptions or credentials in command arguments or URLs.
