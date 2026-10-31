# Current repository and runtime architecture

| Location | Responsibility | Shipped in wheel |
| --- | --- | --- |
| mihomoctl/ | CLI grammar, application/configuration, lifecycle, integration, install/recovery | yes, exact manifest files |
| mihomoctl/controller/ | Controller API, subscription/rule transactions, console/UI and private IO/probes | yes |
| scripts/bootstrap.py | thin stable installer entry | source only |
| scripts/release/ | build, version synchronization, artifact/offline verification | source only |
| scripts/ci/ | generated interfaces, docs/secret checks, Linux acceptance runner | source only |
| tests/ | current product regression | source only |
| legacy/v0.9/ | old Bash/Paseo and historical tests | source only, not discovered |
| docs/en/, docs/zh-CN/ | current tutorials, reference, operations | source only |
| docs/archive/ | historical designs/tutorials | source only |

CLI dispatch validates the centralized grammar before loading manager data for an operation. Help is configuration-free. Profiles select authenticated named listeners; environment injection and declarative adapters share application services. The controller bridge invokes the current packaged controller, never Bash. Installation and self-contained recovery use code delivered inside the runtime package, without a source scripts dependency.

Interactive no-command execution opens Textual in the complete bundle; plain numbered menus remain available. Noninteractive, help and JSON calls remain CLI-only. The portable distribution contains an independent pinned interpreter, all UI dependencies and the pinned core, plus exact inventory hashes and license notices. Standard Python source/wheel installation is supported alongside complete bundles, with Python 3.10+, PyYAML and a separately prepared core. Textual remains optional. The distribution/new assets use mihomo-userctl; import, CLI, XDG and service identities stay mihomoctl.

Each account owns its private manager, subscription credentials, core process and authenticated loopback listeners. Managed auto-assigned ports have bounded conflict retries. UI exit leaves the process backend running. Default simple onboarding establishes a manual Proxy selector and default proxy rule only for new routing; existing managers are preserved.

Updates and configuration changes retain only the current managed state. Durable transaction journals support failure recovery and interrupted-operation recovery, then are deleted. History and historical rollback are disabled. Whole-session generation leases refuse code replacement while an installed console is open. Core/config cleanup is receipt- and ownership-scoped; foreign files are not historical tool backups.

The manager schema remains version 1 and public JSON mihomoctl/v1. Default user/process scope, private-path trust, exact per-file inventories and explicit system TUN remain unchanged. [Configuration contract](en/reference/configuration.md) · [Release operations](en/operations/release.md).
