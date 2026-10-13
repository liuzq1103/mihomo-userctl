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

The manager schema remains version 1 and public JSON mihomoctl/v1. Default user/process scope, private-path trust, exact per-file inventories and explicit system TUN remain unchanged. [Configuration contract](en/reference/configuration.md) · [Release operations](en/operations/release.md).
