# Local packages: complete agent installation prompt

[简体中文](../zh-CN/agent-local-install-prompt.md) · [Setup](setup.md) · [Offline layouts](offline-install.md)

Copy this prompt into OpenCode, Codex or another agent that can execute Linux commands. Default completion includes controller, core and initialization, with the runtime stopped. `install.sh` itself still installs only the controller. Local packages allow a subsequent explicit core download; add “strictly offline” if no network access is permitted.

```text
Actually install and verify mihomoctl from local packages, default source /mnt/nas/public/software.
Complete controller/dependencies, a trusted Mihomo core, initialization and configuration validation. Do not start the runtime by default.

1. Inspect user, HOME/XDG paths, Linux distribution, architecture, Python 3.10+, Bash, existing mihomoctl, manager and trusted cores without revealing credentials. Use the current ordinary user's --user scope. If running as root without a specified target ordinary user, ask for that user first.
   Before installation report package version/type, target compatibility and network conditions. Read the package's INSTALL.md, setup.md and offline-install.md. Local source does not mean strictly offline.

2. Locate source archives, complete offline kits, checksums, receipts/gate and dependencies. Set umask 077, create an owned 700 private working directory under HOME and copy all required materials, including wheelhouse, into it. Do not execute code or use dependencies from a shared writable NAS path. Do not modify/delete files or recursively chmod the NAS.
   Verify outer digests before extraction; inspect archive paths/types/links and refuse traversal or suspicious entries. Verify inner SHA256SUMS, release consistency and target compatibility after extraction. Colocated checksums are not independent publisher authentication. Stop on verification failure; never bypass trust/version gates.
   Distinguish a complete release fetch output directory from a downloaded offline tarball; expand using offline-install.md and actual paths. Code and ancestors must meet installer ownership/permission requirements.

3. Decide core preparation before modifying the installation. Preserve an existing manager: do not repeat init or proactively run core install. A missing/broken configured core is a repair blocker; report it instead of activating a replacement, since core install may restart an existing runtime.
   Without a manager, prefer a verified existing core with safe permissions and matching architecture. If none exists and networking is allowed, on x86_64 default to the explicit mihomoctl core install --version v1.19.32 using the package's maintained asset digest. Do not ask for a version: this is a fixed tested version, not “latest”. On other architectures without a matching built-in digest, request a trusted local core or checked corresponding asset SHA256 before installation; do not force another architecture's binary.
   For strict offline use, report missing core/dependencies before installation; controller-only installation is not complete success. Initial downloads need working direct access or an existing trusted proxy. Do not bootstrap through this installation's uninitialized/stopped mihomoctl exec.

4. Follow the matching kit README and installer help: run --dry-run, then install with the same arguments excluding --dry-run. Explicitly select --user, the correct --python and local --wheelhouse. For a source-only archive, reuse a trusted Python environment with complete dependencies if available; otherwise report missing inputs. Do not modify system Python or use sudo.
   Upgrade older versions with the verified new installer, preserving configuration, credentials, subscriptions, caches and cores. Record its backup path. Do not use the old updater or version shims. Do not edit shell startup files; set PATH only in this session. Set MIHOMOCTL_NO_UPDATE_CHECK=1 during installation to avoid unrelated background queries.

5. After controller verification, carry out the core preparation chosen in step 3. Without a manager, initialize exactly once: mihomoctl init --core /absolute/trusted/core; if configuration was explicitly supplied, pass --config in that same init. Run mihomoctl config validate. Use the path reported by core install; the default XDG path is ${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo.
   Do not automatically start/restart, import subscriptions, operate third-party services, enable systemd or TUN. Default MATCH,DIRECT does not establish remote routing.

6. Outside the source directory, run the installed launcher's version and --help, and use the chosen installation Python with the absolute /release/source/scripts/bootstrap.py path to run verify --user. Report controller installation, core version and initialization/config validation separately as PASS/FAIL/UNVERIFIED. With the default stopped runtime, runtime health and actual remote routing are UNVERIFIED, not an installation failure.
   Report version, installation user, launcher/Python/core paths, verification results, backup path and an executable rollback command. Retain the self-contained backup. Uninstalling controller code does not roll back initialization data; list newly created data and paths and never delete existing user data.
   Provide the session PATH command and next steps for explicit start, subscriptions/rules and actual client verification. Ask only for missing inputs or actions outside authorization; do not defer an already defaulted core version choice until the end. Redact output.
```

See [first run](first-run.md) for acceptance stages and installer proxy inheritance, [offline installation](offline-install.md) for strict offline preparation, and [upgrade/rollback](update.md) for backup recovery.
