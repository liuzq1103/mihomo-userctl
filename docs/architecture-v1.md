# mihomoctl V1 architecture and implementation contract

Status: accepted for v1.0.0. Date: 2026-10-11.

This decision supersedes conflicting proposals in architecture-vnext.md and ADR
0001, particularly application-specific daemon management and the exclusion of
explicit administrator-managed TUN. It does not claim that acceptance has passed.

## Product boundary

mihomoctl manages Mihomo lifecycle and proxy configuration. Its shared domain
model is Proxy Profile + Environment Injection + Runtime Integration + Health
Check. It never installs a shell startup hook or manages a third-party daemon.
Environment variables are inherited at process creation; they neither enforce
network routing nor change an already-running application's environment.

The baseline is the existing 0.9.3 working tree, including uncommitted controller,
subscription, health and TUI work. Preserve that work and private learning notes.
The initial isolated Linux regression run passed 272 tests with 8 skips; real
systemd, multiple UIDs, real core and TUN acceptance remain separate release gates.

## Modules and dependency direction

Use a Python 3.10+ package named `mihomoctl` at the repository root. Keep
`src/mihomoctl` as a thin Python development launcher; installed wheels expose the
same console entry point. Bash is only an installer bootstrap. The package must
not import application-specific lifecycle code.

CLI / TUI -> application service -> config, profile, environment, health,
integration, lifecycle, transactions -> OS / Mihomo / systemd adapters.

Configuration, ownership, credentials, endpoint resolution and health policy have
one implementation. Existing Controller/selection/subscription/policy functions
are retained behind a Python bridge and packaged as reviewed components. Optional
Textual and optional trusted JavaScript overrides do not gate the base CLI.
No CLI or TUI business operation calls the Bash CLI in a subprocess.

The shared facade is `mihomoctl.app.Application(system=False, config_dir=None)`:

* `status()` returns the status data described below.
* `health(profile=None, egress_url=None)` returns structured checks.
* `lifecycle(action)` implements start/stop/restart and returns status data.
* `profiles()` returns redacted profile projections.
* `context` exposes resolved scope paths; `config_path` exposes the active core
  configuration for the retained Controller bridge.

The CLI owns serialization, not domain decisions. TUI consumes these methods
directly. Backend, scope and security decisions stay out of rendering code.

## Configuration and paths

One managed Mihomo runtime per scope is sufficient for V1. Multiple proxy
profiles select listeners on that runtime; bindings name consuming instances.
User paths respect XDG config/data/state/cache/runtime roots, using a private
state-directory runtime fallback if XDG_RUNTIME_DIR is unavailable. System paths
are /etc/mihomoctl, /var/lib/mihomoctl, /var/cache/mihomoctl and /run/mihomoctl.
Never discover a system configuration from HOME, CWD or an untrusted environment.

The management file is `manager.yaml`. The canonical shape is:

```yaml
version: 1
core:
  binary: /absolute/path/to/mihomo
  config: /absolute/path/to/config.yaml
  backend: process
default_profile: default
profiles:
  default:
    http_listener: proxy
    socks_listener: proxy
    credentials_file: /absolute/private/path/credentials.yaml
    no_proxy: [localhost, 127.0.0.1, '::1']
    health:
      timeout: 10
bindings:
  worker:
    profile: default
    adapter: systemd
    target: worker.service
    connect_host: 127.0.0.1
```

Credential files contain username/password data, never executable assignments.
Profiles resolve their ports from named listeners, not a second port setting.
Unknown fields, duplicate YAML keys, unsafe aliases, invalid scope paths and
cross-scope secret references are rejected with actionable errors. Data and
credentials are private; system core-readable configuration is root-owned 0640
with the dedicated service group, while manager/secret files remain root-private.
Trusted installed code may be root-owned and readable by ordinary users; it must
not be group/other writable. User-installed code must be owned by the user.

`init --core PATH [--config FILE]` explicitly creates managed configuration,
credentials, a default profile and a loopback authenticated named mixed listener.
Importing an existing configuration copies it into managed storage after
validation, preserving routing policy. An externally referenced binary remains
adopted/read-only until an explicit managed core install.

## Endpoint and environment contract

Normalize active named `listeners` and legacy top-level `port`, `socks-port` and
`mixed-port` into Endpoint records. Disabled zero ports do not shadow listeners.
An endpoint has name, type, address, port, transport and authentication metadata.
Reject ambiguous names, duplicate binds and incompatible profile selections.
Managed V1 proxy/controller ports are unprivileged integer ports (1024-65535).
Validate all configured listening surfaces, not merely the chosen proxy port.

By default listeners are authenticated IPv4 loopback; explicitly configured IPv6
loopback must receive consistent validation/probing. Controller is authenticated
loopback only. Policy/subscription input cannot alter listener/auth/controller,
TUN, redirect, binding, DNS listening or routing security controls.

System administrators can explicitly authorize particular non-loopback addresses
using `init --allow-non-loopback ADDRESS` or the corresponding explicit config
authorization operation. User scope cannot authorize these. No firewall changes
are made. Bindings for separate network namespaces must specify a reachable host;
wildcard bind addresses are never emitted as client addresses.

Environment generation emits HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and NO_PROXY plus
their lowercase counterparts. HTTP(S) uses an HTTP-capable endpoint; ALL_PROXY
uses socks5h. Missing protocol support is reported instead of guessing. URL
credentials are percent-encoded. Exec clears only these eight inherited proxy
keys before applying the selected profile; unrelated environment is retained.
Direct removes these keys only. Neither changes the parent shell or systemd's
manager environment. Exec requires confirmed local health before execve and
then transparently passes the target's exit/signal result.

## Runtime and security contract

Global --user/--system flags are mutually exclusive, default user. UID 0 must use
explicit --system for mutations; there is no automatic scope promotion or sudo.
System mutations require UID 0. User mode cannot create TUN, touch global network
state, manage system units or affect another user's files/processes.

User init defaults to process backend. Service installation explicitly switches a
stopped managed runtime to systemd; an active backend cannot be silently replaced.
System scope requires systemd and runs the core as a dedicated account. Installing
a unit only writes owned files and reloads its manager: never enable, start or
set linger. Explicit start/stop/restart only operate on the managed Mihomo unit.
There is no silent backend fallback when systemd is unavailable.

Process state contains PID, UID, process start time, executable and config
identity. Start is lock-protected; preflight checks all binds and postflight
checks socket/process ownership plus proxy and controller authentication. Before
signaling, re-read identity. PID reuse or unobservable ownership fails closed.
Never use process-name killing, kill unrelated sockets, or claim a bind-and-close
probe reserves a port. Process crashes are reported; explicit restart recovers.
Systemd uses Restart=on-failure with rate limiting and the same health checks.

Validate candidates using a private staging directory and the exact selected
binary. Do not execute an untrusted/user-writable binary as root. Drop privilege
for system validation. Strip CLASH_* overrides, post-up/down and unsafe Python
environment influence. `mihomo -t` can populate geodata, so it cannot use the live
data directory. Real daemon startup uses a file, not stdin/base64; this preserves
file-based reload semantics. External egress checks are opt-in and are never an
installer or local-start success gate.

TUN is an independent module, default disabled. Only an administrator explicitly
invoking `--system tun enable` may authorize it. Update core config, authorization
receipt and service capability drop-in in one rollbackable transaction. Grant
CAP_NET_ADMIN only when enabled; no global setcap or privileged helper. Disabling
and rollback restore the prior managed files and only the tool-owned device and
routes. Never flush host routes/firewalls. No application or policy adapter can
enable TUN. Network-changing acceptance runs in a disposable network namespace.

System administrators may isolate the managed service using the exact owned
`60-mihomoctl-namespace.conf` drop-in: the managed unit marker, `[Service]`, and
one `NetworkNamespacePath=/run/netns/<safe-name>` directive. Only system scope
accepts this format. The file, ancestry and namespace entry must be trusted and
root-owned; symlinks and writable paths are refused. The loaded property and
managed core's network namespace inode must match. Run management commands with
`ip netns exec <safe-name> mihomoctl --system ...` so listener, route and TUN
observations use the same namespace. The CLI never enters namespaces implicitly;
all other unknown unit overrides remain refused.

## Integration and output contract

Bindings and adapters are declarative data. Built-ins: exec, systemd, docker,
kubernetes, supervisor, pm2 and ci. Custom adapters use a versioned template with
an allowlist of placeholders and format-specific escaping; no eval, imports or
command execution. Exported artifacts are not deployed automatically.

Systemd integration writes a private proxy.env and marked owned drop-in referencing
EnvironmentFile. Install/remove may daemon-reload but never start/stop/restart or
enable third-party units. Refuse to replace unowned/drifted files. Docker and
Kubernetes export only, with an explicitly reachable address; no Docker/Kubernetes
API or privilege escalation. Check reports intended binding, artifact hash drift
and available live evidence. Existing processes require operator-managed restart.

Env show and all status/health output are redacted. Export real secrets to an
explicit private output file; stdout requires --reveal. Do not put credentials in
argv, unit text, exception messages or logs. EnvironmentFile is an integration
format, not secret isolation; document process inheritance and systemd exposure.

CLI status shows scope/backend, core, controller, every listener, active config,
proxy layer, Mihomo routing mode, TUN and errors. JSON is one envelope with schema
`mihomoctl/v1`, command, scope, overall, data, checks and errors. Checks use PASS,
FAIL, UNVERIFIED, SKIPPED with evidence confirmed/inferred/unavailable. Exit codes
are 0 success, 1 observed failure/health block, 2 usage/permission/unverified.
After exec starts, child exit results are not remapped. Logs must redact secrets.
Retained controller commands use the same public envelope in V1.

## Transactions, migration, delivery and acceptance

Mutations use locks, staged validation, backups, atomic publication, activation,
acceptance and finalization. Rollback failure is a distinct reported failure.
Install and update do not require a live proxy. Preserve generation switching and
self-contained recovery. Never default-edit bashrc/zshrc/profile, aliases or
functions. Migration is an explicit preview/apply operation: import old config and
credentials, remove only a positively identified project loader, preserve outside
bytes and back up all modified files. Customized/ambiguous loaders are refused.
Existing third-party units are reported, never stopped or removed. Old application
lifecycle commands return migration guidance instead of retaining daemon control.
The V1 installer/update protocol is 2; incompatible old updaters fail before writes.

Core install/update is explicit, fixed-version and checksum-gated. Known versions
use reviewed pinned digests; unknown versions require --sha256. Check architecture,
bounded decompression and reported version. Record digest provenance without
claiming upstream signature verification. Download/verify before stopping old
Mihomo; restore prior binary/config on failed activation. CLI install never
implicitly downloads/replaces Mihomo.

Mandatory release gates: Ubuntu 22.04/24.04 real user/system systemd lifecycle,
two real UIDs on one VM, real core listener/auth/config checks, process crash/PID
reuse/concurrent operations, isolated TUN enable/disable/failure cleanup, exec and
noninteractive environment inheritance, profile/artifact/credential drift, legacy
migration/rollback, controller/subscription/TUI regressions, packaging installation,
secret scans and independent review. Skipped mandatory checks block release.

Release only explicitly reviewed files. Private notes stay local. Build source
tar.gz/zip and wheel plus SHA256SUMS from the reviewed commit. Push a release branch,
pass CI on that exact commit, merge main, create an immutable annotated v1.0.0 tag,
test artifact installation, publish a non-prerelease GitHub Release, then verify
remote tag/commit/assets/digests agree.
