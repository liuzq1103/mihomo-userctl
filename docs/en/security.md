# Safety boundaries

Default scope is user and default backend is process. No automatic sudo/elevation, shell startup writes, global proxy changes or third-party service lifecycle actions. root must explicitly select --system for mutations. TUN is system-only and explicit.

exec requires confirmed local health and fails closed; direct clears eight standard proxy variables. Neither forces an application to obey proxy variables. Controller credentials are separate from consumer proxy credentials. Credentials stay in private files; only explicit reveal/export discloses them. Do not log exports or place subscription URLs in argv. Configuration errors do not echo supplied secret values.

exec does not change the parent shell or an outer pipeline's right-hand environment. Explicitly proxy the whole third-party installation shell; prefer [downloading and reviewing before execution](first-run.md#install-a-third-party-cli-through-the-proxy). pipefail reports failure but cannot authenticate scripts or prevent streamed execution. HTTP 200 HTML can still be an error response.

Rules checks are read-only. Subscription apply validates original-config digest, candidate SHA256, allowed fields and core validation before activation, with temporary failure recovery; successful operations retain no history. Node JS overrides execute trusted local code; Node vm is not a sandbox. Do not run untrusted scripts.

Update/uninstall preserve user configuration, credentials, subscriptions, cache and core. Code paths must be owned by you/root and not group/other writable. Release inventory is an exact per-file allowlist; scripts and legacy code are not wheel runtime. Report security issues through [SECURITY.md](../../SECURITY.md).
