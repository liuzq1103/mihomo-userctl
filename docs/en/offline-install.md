# Offline installation

Use the complete kit matching Ubuntu 22.04 x86_64 Python 3.10 or Ubuntu 24.04 x86_64 Python 3.12. Verify its outer .sha256 against independently obtained release checksums before extraction; inspect and verify SHA256SUMS inside. The kit contains source, wheel, dependency wheelhouse and an installer. Extract into a private, owned directory; no symlinks or group/other writable code paths.

Read the kit README.txt and invoke its install.sh from that extracted directory. It checks target compatibility and installs with --no-index from wheelhouse. No pre-expanded public deployment directory is required. Installation remains user-scoped by default and performs no runtime/service actions. Keep the reported self-contained backup. See [INSTALL.md](../../INSTALL.md) and [upgrade/rollback](update.md). Offline core provisioning is separate: provide an already verified executable and initialize it explicitly.
