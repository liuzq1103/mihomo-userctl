# Shared Node/Codex, private identity and proxy

[中文](../zh-CN/shared-runtime.md) · [Deployment contract](deployment-contract.md) · [Local installation](offline-install.md)

Use this mode on multi-user servers with administrator-managed tools: **share programs, keep
identity data and network configuration per Linux user**. Personal machines without shared tools
can explicitly select personal installation. Online/local acquisition and shared/personal runtime
are independent choices.

| Layer | Ownership and boundary |
| --- | --- |
| Shared Node/npm/Codex | Administrator maintains pinned versions and rollback; users read/execute only |
| Codex identity/state | Each user's HOME, state directory, credential store and sessions; no shared login |
| Mihomo/controller | Each user's core, configuration, credentials, systemd user service and loopback port |

`/usr/bin/node`, `/usr/bin/npm` and `/usr/bin/codex` are examples, not mandatory paths. Record
administrator-confirmed entrypoints, resolved targets and versions. Program ownership does not
make a normal user's process root; verify the actual UID. Never launch Codex with sudo.

## Administrator preparation and user installation

The administrator separately installs/upgrades the shared runtime using pinned versions, reviewed
sources/checksums and compatible Node/install methods, with rollback and coordination of active
sessions. The ordinary-user prompt never runs apt, system npm installation, chown/chmod of shared
directories or shared upgrades. Do not follow unpinned latest. Shared executables, symlink targets,
ancestors and npm global directories must not be writable by ordinary users. Never loosen permissions
or change global npm prefix to bypass an installation permission error.

In shared mode, users install only missing personal Mihomo and mihomo-userctl. Missing, unsuitable
or untrusted shared tools block the dependent steps and become administrator actions, not a silent
personal fallback. OpenCode requires its own explicit selection/source/scope. Offline archives in
a shared directory are distribution material, not a common writable runtime. The default shared-mode
bundle needs only Mihomo and controller source; Node/Codex archives are optional for personal mode.

## PATH and NVM audit

Read-only checks cover command type, PATH precedence, symlink targets, versions and npm prefix/root.
Do not return alias/function definitions that could contain secrets or raw environment dumps. Check
more than the Codex entrypoint: a launcher using `#!/usr/bin/env node` selects Node from runtime PATH,
even if Codex is in a system directory. Inspect the selected launcher's actual format before assuming
a Node dependency; native standalone Codex archives do not imply one.

A fresh login shell and proxy child must resolve the selected shared tools. After auditing PATH:

```bash
type -P node npm codex
node --version
npm --version
codex --version
with_proxy bash --noprofile --norc -c 'command -v node; node --version; command -v npm; npm --version; command -v codex; codex --version'
```

The proxy check requires the user's own ready Mihomo. Version output proves launch only. For npm
launchers, additionally verify the process's actual Node executable and Codex package identity,
without printing full arguments or secrets. An absolute `/usr/bin/codex` path alone does not force
`env node` to use the shared Node.

If NVM, personal standalone/npm Codex or PATH conflicts exist, report exact current-user paths and
impact while preserving them. Migrate only after explicit selection: back up startup configuration
and record the previous defaults. If supported by the installed NVM, `nvm alias default system`,
`nvm use system` and `hash -r` are possible migration steps, never automatic defaults. Recheck a new
login and retain instructions for restoring the previous default. Never delete entire `.nvm` or
`.codex` directories. Removing one installation requires identifying its installer, npm prefix and
exact directory; do not copy removal commands from another server's notes. Project-specific Node
switching can remain available, but must not be reported as satisfying shared-runtime acceptance.

## Private identity and acceptance

Codex state defaults to `~/.codex`; `CODEX_HOME` can override it. Check the actual current-user HOME,
effective state path and permissions without repointing them to another identity. Credentials can
also live in a user OS credential store: missing `auth.json` does not prove the user is logged out.
Refer to the official [authentication](https://learn.chatgpt.com/docs/auth) and
[environment-variable](https://learn.chatgpt.com/docs/config-file/environment-variables) guidance
for the selected release. Never share credential files, keys or sessions, or link state into a public
directory. Inspect only the current user's state and preserve it. The user completes their own login
via `with_proxy codex` when necessary; do not send tokens or login codes to chat.

Add shared entrypoints/resolved targets/versions, normal and proxy-shell resolution, npm prefix/root,
actual Node interpreter where applicable, UID, private state path and migration defaults/rollback to
the final report. Continue separate Listener, proxy-egress and model-request [acceptance](acceptance.md).
Shared programs do not imply shared accounts; paths or distinct ports alone do not prove complete
isolation. Administrator/root access is outside the ordinary-user isolation threat boundary.

## Remote hook and persistent app-server

Whether `with_proxy codex` is necessary depends on the actual launch path. A verified Remote hook
with accepted outbound-server proxy behavior needs no additional wrapper. Merely configuring the
hook does not make plain terminal `codex` trigger it; explicit terminal entry remains recommended.
A plain CLI reusing a verified proxied server may also need no wrapper, but that is current service
state to recheck after reconnect/upgrade, not a guarantee for new users.

This project's `src/shell.bash` first calls `proxy_off`, then `proxy_on` only when the launcher
supplies nonempty `CODEX_REMOTE_PAYLOAD`; failed readiness exits. This is a locally verified
compatibility hook, not a stable public Codex API. Do not assume every Remote, code-mode or VS Code
launch supplies it. Verify the actual shell loads the managed loader; never persist the variable.

Distinguish ordinary default-direct shells, explicit terminal `with_proxy`/`mihomoctl exec`, and
verified Remote launch via the hook. Mihomo rules select egress after traffic enters, not transparent
interception. VS Code Extension Host retains its [separate integration](vscode-remote.md).

Some versions/launch modes permit this path; measure it rather than assuming it for all users:

```text
CLI (possibly no proxy variables) -> current-user Unix socket -> persistent app-server
  -> personal Mihomo listener -> routing rule -> actual egress
```

CLI `0/8` does not prove direct model traffic; CLI `8/8` does not prove an old server is proxied.
`mihomoctl direct` also changes only the new child, not a reused server. Shared program upgrades or
PATH fixes do not replace an existing server's version/environment. Record the actual outbound
process, not just the new CLI.

Use [troubleshooting](troubleshooting.md) to correlate CLI, any bridge and app-server UID/PID,
runtime identity, start time, environment classification, Unix socket, Listener connection and
same-request time/target/redacted routing evidence. Current diagnose output does not automatically
establish Unix peers or the full causal chain. Socket paths depend on version/state directory;
PPID=1, `8/8` or routing logs alone do not prove hook provenance or CLI linkage. Idle connections
may be absent; insufficient evidence is UNVERIFIED. Never return raw arguments, environments or logs.
Coordinate current-user session reconnect/restart; never automatically kill processes or delete
sockets/private state. New users still need their own authorized startup and login acceptance;
another user's working plain codex is not proof that proxy entry is unnecessary.
