# CLI 命令参考

由实际解析定义生成；初始化前也可使用 `mihomoctl COMMAND --help`。

`mihomoctl [--user|--system] COMMAND [ARGS...] [--json]`

Scope flags precede COMMAND. `exec` and `direct` pass everything after `--` to the child.

外层 Shell 运算符不属于 `exec` 的子进程；安装管道应包裹整个 Shell，见 [代理继承与下载审阅](../first-run.md#通过代理安装第三方-cli)。

Compatibility: `profiles` = `profile list`; `export --binding NAME` = `integration export NAME`; `dashboard` = `ui`; `health` = `health check`. Retired: `codex`, `paseo`, `opencode`, `diagnose`, `ready`.

## init

```text
usage: mihomoctl init [-h] --core CORE [--port PORT] [--config CONFIG]
                      [--allow-non-loopback ALLOW_NON_LOOPBACK] [--json]

Initialize a user-scoped runtime configuration.

Effects: Writes private manager/configuration/credentials; no download or start. Existing state is preserved.

options:
  -h, --help            show this help message and exit
  --core CORE           trusted Mihomo executable; does not download a core
  --port PORT           explicit authenticated loopback proxy port; otherwise
                        allocate per user
  --config CONFIG       explicit core YAML file (private, same scope)
  --allow-non-loopback ALLOW_NON_LOOPBACK
                        authorize this exact non-loopback address (repeatable;
                        no firewall changes)
  --json                emit the mihomoctl/v1 JSON envelope
```

## start

```text
usage: mihomoctl start [-h] [--json]

Start the managed Mihomo runtime.

Effects: Starts only the owned runtime. May allocate authenticated loopback ports.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## stop

```text
usage: mihomoctl stop [-h] [--json]

Stop the managed runtime.

Effects: Stops only the owned runtime; interrupts its proxy connections.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## restart

```text
usage: mihomoctl restart [-h] [--json]

Restart to apply saved configuration.

Effects: Stops and starts the owned runtime to apply saved configuration.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## status

```text
usage: mihomoctl status [-h] [--json]

Show runtime facts and evidence.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## logs

```text
usage: mihomoctl logs [-h] [--lines LINES] [--follow] [--json]

Read managed runtime logs.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help     show this help message and exit
  --lines LINES  maximum log lines (default: 50)
  --follow       stream logs until interrupted
  --json         emit the mihomoctl/v1 JSON envelope
```

## config

```text
usage: mihomoctl config [-h] {validate,check} ...

Validate the active or specified configuration.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {validate,check}

options:
  -h, --help        show this help message and exit
```

### config validate

```text
usage: mihomoctl config validate [-h] [--file FILE] [--profile PROFILE]
                                 [--json]

Validate the active or specified configuration.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help         show this help message and exit
  --file FILE        configuration file to validate
  --profile PROFILE  named manager profile; mutually exclusive with --binding
  --json             emit the mihomoctl/v1 JSON envelope
```

### config check

```text
usage: mihomoctl config check [-h] [--file FILE] [--profile PROFILE] [--json]

Validate the active or specified configuration.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help         show this help message and exit
  --file FILE        configuration file to validate
  --profile PROFILE  named manager profile; mutually exclusive with --binding
  --json             emit the mihomoctl/v1 JSON envelope
```

## profile

```text
usage: mihomoctl profile [-h] {list,show,validate,set-default} ...

Inspect and select proxy profiles.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {list,show,validate,set-default}

options:
  -h, --help            show this help message and exit
```

### profile list

```text
usage: mihomoctl profile list [-h] [--json]

Inspect and select proxy profiles.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### profile show

```text
usage: mihomoctl profile show [-h] [--json] name

Inspect and select proxy profiles.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  name        exact configured name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### profile validate

```text
usage: mihomoctl profile validate [-h] [--json] name

Inspect and select proxy profiles.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  name        exact configured name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### profile set-default

```text
usage: mihomoctl profile set-default [-h] [--json] name

Inspect and select proxy profiles.

Effects: Saves the manager default profile; existing processes keep their environment.

positional arguments:
  name        exact configured name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## env

```text
usage: mihomoctl env [-h] {show,export} ...

Show or export scoped proxy variables.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {show,export}

options:
  -h, --help     show this help message and exit
```

### env show

```text
usage: mihomoctl env show [-h] [--profile PROFILE] [--binding BINDING]
                          [--reveal] [--json]

Show or export scoped proxy variables.

Effects: Read-only and redacted by default. --reveal explicitly exposes credentials.

options:
  -h, --help         show this help message and exit
  --profile PROFILE  named manager profile; mutually exclusive with --binding
  --binding BINDING  declared integration binding
  --reveal           explicitly expose credentials; never upload or log this
                     output
  --json             emit the mihomoctl/v1 JSON envelope
```

### env export

```text
usage: mihomoctl env export [-h] [--profile PROFILE] [--binding BINDING]
                            (--output OUTPUT | --reveal) [--json]

Show or export scoped proxy variables.

Effects: Writes a private environment file; --reveal explicitly prints credentials instead. Does not modify the caller shell.

options:
  -h, --help         show this help message and exit
  --profile PROFILE  named manager profile; mutually exclusive with --binding
  --binding BINDING  declared integration binding
  --output OUTPUT    private output file; writes credentials with mode 0600
  --reveal           explicitly expose credentials; never upload or log this
                     output
  --json             emit the mihomoctl/v1 JSON envelope
```

## exec

```text
usage: mihomoctl exec [-h] [--profile PROFILE] [--binding BINDING] [--json]

Run a child with a selected proxy environment.

Effects: After local health passes, replaces this process with COMMAND and injects private proxy variables into that child only. Child exit/signal semantics are preserved.

options:
  -h, --help         show this help message and exit
  --profile PROFILE  named manager profile; mutually exclusive with --binding
  --binding BINDING  declared integration binding
  --json             emit the mihomoctl/v1 JSON envelope
```

## direct

```text
usage: mihomoctl direct [-h] [--json]

Run a child with proxy variables removed.

Effects: Replaces this process with COMMAND after removing proxy variables from that child only.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## integration

```text
usage: mihomoctl integration [-h] {list,show,check,export,install,remove} ...

Inspect and export declarative application bindings.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {list,show,check,export,install,remove}

options:
  -h, --help            show this help message and exit
```

### integration list

```text
usage: mihomoctl integration list [-h] [--json]

Inspect and export declarative application bindings.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration show

```text
usage: mihomoctl integration show [-h] [--json] name

Inspect and export declarative application bindings.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  name        exact configured name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration check

```text
usage: mihomoctl integration check [-h] [--json] name

Inspect and export declarative application bindings.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  name        exact configured name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration export

```text
usage: mihomoctl integration export [-h] [--output-dir OUTPUT_DIR] [--reveal]
                                    [--json]
                                    name

Inspect and export declarative application bindings.

Effects: Writes declared integration files, which may contain private credentials; no third-party restart.

positional arguments:
  name                  exact configured name

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        destination directory; exported files may contain
                        credentials
  --reveal              explicitly expose credentials; never upload or log
                        this output
  --json                emit the mihomoctl/v1 JSON envelope
```

### integration install

```text
usage: mihomoctl integration install [-h] [--json] name

Inspect and export declarative application bindings.

Effects: Installs only the declared owned integration files; no third-party restart.

positional arguments:
  name        exact configured name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### integration remove

```text
usage: mihomoctl integration remove [-h] [--json] name

Inspect and export declarative application bindings.

Effects: Removes only receipt-owned integration files; no third-party restart.

positional arguments:
  name        exact configured name

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## service

```text
usage: mihomoctl service [-h]
                         {install,start,stop,restart,status,uninstall} ...

Manage the owned systemd service.

Effects: Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.

positional arguments:
  {install,start,stop,restart,status,uninstall}

options:
  -h, --help            show this help message and exit
```

### service install

```text
usage: mihomoctl service install [-h] [--json]

Manage the owned systemd service.

Effects: Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service start

```text
usage: mihomoctl service start [-h] [--json]

Manage the owned systemd service.

Effects: Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service stop

```text
usage: mihomoctl service stop [-h] [--json]

Manage the owned systemd service.

Effects: Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service restart

```text
usage: mihomoctl service restart [-h] [--json]

Manage the owned systemd service.

Effects: Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service status

```text
usage: mihomoctl service status [-h] [--json]

Manage the owned systemd service.

Effects: Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### service uninstall

```text
usage: mihomoctl service uninstall [-h] [--dry-run] [--json]

Manage the owned systemd service.

Effects: Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.

options:
  -h, --help  show this help message and exit
  --dry-run   preview without applying the requested change
  --json      emit the mihomoctl/v1 JSON envelope
```

## tun

```text
usage: mihomoctl tun [-h] {status,enable,disable} ...

Inspect or change explicit TUN settings.

Effects: Inspection is read-only; enable/disable require explicit --system and administrator authorization. Never self-elevates.

positional arguments:
  {status,enable,disable}

options:
  -h, --help            show this help message and exit
```

### tun status

```text
usage: mihomoctl tun status [-h] [--json]

Inspect or change explicit TUN settings.

Effects: Inspection is read-only; enable/disable require explicit --system and administrator authorization. Never self-elevates.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### tun enable

```text
usage: mihomoctl tun enable [-h] [--json]

Inspect or change explicit TUN settings.

Effects: Inspection is read-only; enable/disable require explicit --system and administrator authorization. Never self-elevates.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### tun disable

```text
usage: mihomoctl tun disable [-h] [--json]

Inspect or change explicit TUN settings.

Effects: Inspection is read-only; enable/disable require explicit --system and administrator authorization. Never self-elevates.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## core

```text
usage: mihomoctl core [-h] {install,update,adopt,list} ...

Install, adopt or list Mihomo binaries.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {install,update,adopt,list}

options:
  -h, --help            show this help message and exit
```

### core install

```text
usage: mihomoctl core install [-h] --version VERSION [--sha256 SHA256]
                              [--dry-run] [--json]

Install, adopt or list Mihomo binaries.

Effects: Acquires and verifies an explicit fixed core version. Does not start it or replace an active core.

options:
  -h, --help         show this help message and exit
  --version VERSION  explicit pinned version vX.Y.Z
  --sha256 SHA256    expected SHA-256 from the reviewed input or preview
  --dry-run          preview without applying the requested change
  --json             emit the mihomoctl/v1 JSON envelope
```

### core update

```text
usage: mihomoctl core update [-h] --version VERSION [--sha256 SHA256]
                             [--dry-run] [--json]

Install, adopt or list Mihomo binaries.

Effects: Installs an explicitly selected verified core; active-core replacement remains explicit.

options:
  -h, --help         show this help message and exit
  --version VERSION  explicit pinned version vX.Y.Z
  --sha256 SHA256    expected SHA-256 from the reviewed input or preview
  --dry-run          preview without applying the requested change
  --json             emit the mihomoctl/v1 JSON envelope
```

### core adopt

```text
usage: mihomoctl core adopt [-h] --path PATH [--json]

Install, adopt or list Mihomo binaries.

Effects: Records a trusted existing binary; does not copy or download it.

options:
  -h, --help   show this help message and exit
  --path PATH  trusted existing executable to adopt
  --json       emit the mihomoctl/v1 JSON envelope
```

### core list

```text
usage: mihomoctl core list [-h] [--json]

Install, adopt or list Mihomo binaries.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## health

```text
usage: mihomoctl health [-h] [--profile PROFILE] [--binding BINDING]
                        [--egress-url EGRESS_URL] [--json]

Check runtime readiness and proxy access.

Effects: Probes local authenticated listeners; an explicit egress URL sends an external request. Does not prove another application used a remote node.

options:
  -h, --help            show this help message and exit
  --profile PROFILE     named manager profile; mutually exclusive with
                        --binding
  --binding BINDING     declared integration binding
  --egress-url EGRESS_URL
                        optional public HTTPS probe; does not prove another
                        application used the proxy
  --json                emit the mihomoctl/v1 JSON envelope
```

## doctor

```text
usage: mihomoctl doctor [-h] [--json]

Diagnose configuration and runtime prerequisites.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## migrate

```text
usage: mihomoctl migrate [-h] (--dry-run | --apply) [--remove-loader]
                         [--no-import] [--core CORE] [--json]

Preview or apply migration from the legacy layout.

Effects: Preview with --dry-run. --apply changes owned legacy configuration; --remove-loader explicitly changes the reviewed legacy loader.

options:
  -h, --help       show this help message and exit
  --dry-run        preview without applying the requested change
  --apply          apply only after reviewing the preview and obtaining
                   explicit authorization
  --remove-loader  explicitly remove the reviewed legacy shell loader
  --no-import      migrate without importing the legacy configuration
  --core CORE      trusted Mihomo executable; does not download a core
  --json           emit the mihomoctl/v1 JSON envelope
```

## reset

```text
usage: mihomoctl reset [-h] (--dry-run | --apply) [--core CORE]
                       [--plan-sha256 PLAN_SHA256] [--json]

Restore the managed runtime to its initial defaults.

Effects: DESTRUCTIVE: replaces configuration and credentials and stops the owned runtime. First use --dry-run; only after explicit human authorization use --apply --plan-sha256 HASH. Runtime state changes invalidate the preview. No historical rollback.

options:
  -h, --help            show this help message and exit
  --dry-run             preview without applying the requested change
  --apply               apply only after reviewing the preview and obtaining
                        explicit authorization
  --core CORE           trusted Mihomo executable; does not download a core
  --plan-sha256 PLAN_SHA256
                        reset preview digest; required with --apply; stale
                        state requires a new preview
  --json                emit the mihomoctl/v1 JSON envelope
```

## rollback

```text
usage: mihomoctl rollback [-h] [--json] backup

Historical rollback is not supported.

Effects: Historical rollback is disabled. Unfinished transaction recovery remains available automatically.

positional arguments:
  backup      historical rollback is disabled

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## release

```text
usage: mihomoctl release [-h] {check,fetch} ...

Check or fetch release artifacts.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {check,fetch}

options:
  -h, --help     show this help message and exit
```

### release check

```text
usage: mihomoctl release check [-h] [--json]

Check or fetch release artifacts.

Effects: Queries official stable-release metadata; does not install or prove the current version is latest.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

### release fetch

```text
usage: mihomoctl release fetch [-h] --output-dir OUTPUT_DIR
                               [--version VERSION]
                               [--target {linux-x86_64,ubuntu22.04-x86_64-py310,ubuntu24.04-x86_64-py312}]
                               [--json]

Check or fetch release artifacts.

Effects: Downloads and validates official assets into the explicit output directory; does not install.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        destination directory; exported files may contain
                        credentials
  --version VERSION     explicit pinned version vX.Y.Z
  --target {linux-x86_64,ubuntu22.04-x86_64-py310,ubuntu24.04-x86_64-py312}
                        explicit validated release platform
  --json                emit the mihomoctl/v1 JSON envelope
```

## update

```text
usage: mihomoctl update [-h] [--dry-run] [--latest] [--allow-same-version]
                        [--allow-downgrade] [--wheelhouse WHEELHOUSE]
                        [--python PYTHON] [--extras GROUP | --no-extras]
                        [--json]
                        [source]

Preview or install a reviewed release.

Effects: Complete installations only: atomically replaces managed program code. Does not replace the active core. --latest downloads reviewed assets; local-source updates are offline. External Python installs must use their package manager; this command also refuses --dry-run for those installs.

positional arguments:
  source                reviewed local release archive or directory

options:
  -h, --help            show this help message and exit
  --dry-run             preview without applying the requested change
  --latest              fetch a reviewed stable release from the official
                        repository
  --allow-same-version  explicitly allow reinstalling the installed version
  --allow-downgrade     explicitly authorize installing an older version
  --wheelhouse WHEELHOUSE
                        trusted local dependency wheel directory (no index
                        access)
  --python PYTHON       trusted existing Python interpreter
  --extras GROUP        select optional dependencies (repeatable)
  --no-extras           clear optional dependencies
  --json                emit the mihomoctl/v1 JSON envelope
```

## rules

```text
usage: mihomoctl rules [-h] {status,check} ...

Inspect and validate custom rule state.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {status,check}

options:
  -h, --help      show this help message and exit
```

### rules status

```text
usage: mihomoctl rules status [-h] [--home-dir HOME_DIR] [--config CONFIG]
                              [--json]

Inspect and validate custom rule state.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help           show this help message and exit
  --home-dir HOME_DIR  explicit private Mihomo data directory
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

### rules check

```text
usage: mihomoctl rules check [-h] [--home-dir HOME_DIR] [--config CONFIG]
                             [--json]

Inspect and validate custom rule state.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help           show this help message and exit
  --home-dir HOME_DIR  explicit private Mihomo data directory
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

## version

```text
usage: mihomoctl version [-h] [--json]

Show the installed CLI version.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help  show this help message and exit
  --json      emit the mihomoctl/v1 JSON envelope
```

## controller

```text
usage: mihomoctl controller [-h] {status,initialize,setup,token} ...

Inspect or initialize the local controller.

Effects: status is read-only; initialize/setup write private controller configuration. token reveals the secret only in a private terminal, never JSON.

positional arguments:
  {status,initialize,setup,token}

options:
  -h, --help            show this help message and exit
```

### controller status

```text
usage: mihomoctl controller status [-h] [--config CONFIG] [--json]

Inspect or initialize the local controller.

Effects: status is read-only; initialize/setup write private controller configuration. token reveals the secret only in a private terminal, never JSON.

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

### controller initialize

```text
usage: mihomoctl controller initialize [-h] [--port PORT]
                                       [--home-dir HOME_DIR] [--config CONFIG]
                                       [--json]

Inspect or initialize the local controller.

Effects: status is read-only; initialize/setup write private controller configuration. token reveals the secret only in a private terminal, never JSON.

options:
  -h, --help           show this help message and exit
  --port PORT          explicit authenticated loopback proxy port; otherwise
                       allocate per user
  --home-dir HOME_DIR  explicit private Mihomo data directory
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

### controller setup

```text
usage: mihomoctl controller setup [-h] [--port PORT] [--home-dir HOME_DIR]
                                  [--archive ARCHIVE] [--sha256 SHA256]
                                  [--config CONFIG] [--json]

Inspect or initialize the local controller.

Effects: status is read-only; initialize/setup write private controller configuration. token reveals the secret only in a private terminal, never JSON.

options:
  -h, --help           show this help message and exit
  --port PORT          explicit authenticated loopback proxy port; otherwise
                       allocate per user
  --home-dir HOME_DIR  explicit private Mihomo data directory
  --archive ARCHIVE    reviewed local dashboard archive
  --sha256 SHA256      expected SHA-256 from the reviewed input or preview
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

### controller token

```text
usage: mihomoctl controller token [-h] [--config CONFIG] [--json]

Inspect or initialize the local controller.

Effects: status is read-only; initialize/setup write private controller configuration. token reveals the secret only in a private terminal, never JSON.

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## nodes

```text
usage: mihomoctl nodes [-h] [--config CONFIG] [--json]

List exact node names from the core proxy table.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## groups

```text
usage: mihomoctl groups [-h] [--config CONFIG] [--json]

Inspect routing groups and selected chains.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## select

```text
usage: mihomoctl select [-h] [--allow-cross-level] [--config CONFIG] [--json]
                        group node

Select a member of a manual group.

Effects: Changes a Selector immediately; read-back confirms selection. May persist the current choice; existing connections stay open. Record the old choice first. --allow-cross-level requires explicit authorization.

positional arguments:
  group                exact Selector group name from groups --json
  node                 exact unambiguous node/member name; quote spaces and
                       Unicode

options:
  -h, --help           show this help message and exit
  --allow-cross-level  explicitly authorize selecting a leaf in a group
                       containing subgroups
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

## latency

```text
usage: mihomoctl latency [-h] [--provider PROVIDER] [--global]
                         [--config CONFIG] [--json]
                         node

Probe one node against the public HTTPS target.

Effects: Sends a public HTTPS probe through the exact node identity; may update core probe state. Not application end-to-end evidence.

positional arguments:
  node                 exact unambiguous node/member name; quote spaces and
                       Unicode

options:
  -h, --help           show this help message and exit
  --provider PROVIDER  exact provider identity; never resolve duplicate names
                       by guessing
  --global             use the global node identity rather than a provider
                       identity
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

## connections

```text
usage: mihomoctl connections [-h] [--details] [--config CONFIG] [--json]

Inspect active connection chains.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help       show this help message and exit
  --details        include sensitive connection details; do not log or share
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## traffic

```text
usage: mihomoctl traffic [-h] [--config CONFIG] [--json]

Sample upload and download rates.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## subscription

```text
usage: mihomoctl subscription [-h] {preview,apply} ...

Preview and apply a private subscription.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {preview,apply}

options:
  -h, --help       show this help message and exit
```

### subscription preview

```text
usage: mihomoctl subscription preview [-h] [--source-file SOURCE_FILE]
                                      [--url-file URL_FILE] [--stdin]
                                      [--policy {auto,nodes,provider,policy}]
                                      [--home-dir HOME_DIR] [--config CONFIG]
                                      [--json]

Preview and apply a private subscription.

Effects: Reads private input; may download subscription/provider resources; writes private temporary preview material. Does not apply configuration.

options:
  -h, --help            show this help message and exit
  --source-file SOURCE_FILE
                        private subscription YAML file; never pass a
                        subscription URL as an argument
  --url-file URL_FILE   private file containing the subscription URL
  --stdin               read subscription input from stdin
  --policy {auto,nodes,provider,policy}
                        subscription merge policy; preview before applying
  --home-dir HOME_DIR   explicit private Mihomo data directory
  --config CONFIG       explicit core YAML file (private, same scope)
  --json                emit the mihomoctl/v1 JSON envelope
```

### subscription apply

```text
usage: mihomoctl subscription apply [-h] --sha256 SHA256 [--home-dir HOME_DIR]
                                    [--config CONFIG] [--json]
                                    id

Preview and apply a private subscription.

Effects: Writes the reviewed preview after digest validation. Configuration changes need explicit restart.

positional arguments:
  id                   private preview identifier

options:
  -h, --help           show this help message and exit
  --sha256 SHA256      expected SHA-256 from the reviewed input or preview
  --home-dir HOME_DIR  explicit private Mihomo data directory
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

## tui

```text
usage: mihomoctl tui [-h] [--home-dir HOME_DIR] [--plain]
                     [--engine {curses,textual,plain}] [--theme {dark,light}]
                     [--ascii] [--stdin]
                     [--policy {auto,nodes,provider,policy}] [--script SCRIPT]
                     [--details] [--flclash-compat] [--config CONFIG] [--json]

Open the interactive console.

Effects: INTERACTIVE HUMAN OPERATION ONLY. May initialize, save configuration or change the runtime after confirmation. Agents must use explicit CLI commands.

options:
  -h, --help            show this help message and exit
  --home-dir HOME_DIR   explicit private Mihomo data directory
  --plain               human interactive plain menu
  --engine {curses,textual,plain}
                        human interactive frontend; plain is the terminal
                        fallback
  --theme {dark,light}  human interface color theme
  --ascii               use ASCII interface characters
  --stdin               read subscription input from stdin
  --policy {auto,nodes,provider,policy}
                        subscription merge policy; preview before applying
  --script SCRIPT       trusted override script; executes code during preview
  --details             include sensitive connection details; do not log or
                        share
  --flclash-compat      explicit compatibility mode for a trusted FlClash
                        script
  --config CONFIG       explicit core YAML file (private, same scope)
  --json                emit the mihomoctl/v1 JSON envelope
```

## providers

```text
usage: mihomoctl providers [-h] [--config CONFIG] [--json]

List proxy providers and their state.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## provider

```text
usage: mihomoctl provider [-h] {refresh} ...

Request a proxy provider refresh.

Effects: Read-only inspection; default output omits credentials.

positional arguments:
  {refresh}

options:
  -h, --help  show this help message and exit
```

### provider refresh

```text
usage: mihomoctl provider refresh [-h] [--config CONFIG] [--json] name

Request a proxy provider refresh.

Effects: Requests a provider download/refresh; response confirms the request, not refresh completion.

positional arguments:
  name             exact configured name

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## dns

```text
usage: mihomoctl dns [-h] [--config CONFIG] [--json] name [record]

Query DNS through the controller.

Effects: Sends a DNS query through the local owned controller.

positional arguments:
  name             exact configured name
  record           DNS record type (default: A)

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```

## mode

```text
usage: mihomoctl mode [-h] [--config CONFIG] [--json] {rule,global,direct}

Change the running core routing mode.

Effects: Changes running-core routing mode immediately; does not save configuration or close existing connections.

positional arguments:
  {rule,global,direct}  running-core routing mode; existing connections remain
                        open

options:
  -h, --help            show this help message and exit
  --config CONFIG       explicit core YAML file (private, same scope)
  --json                emit the mihomoctl/v1 JSON envelope
```

## health-check

```text
usage: mihomoctl health-check [-h] [--apply] [--home-dir HOME_DIR]
                              [--config CONFIG] [--url URL]
                              [--expected-status EXPECTED_STATUS]
                              [--interval INTERVAL] [--timeout TIMEOUT]
                              [--lazy {true,false}] [--tolerance TOLERANCE]
                              [--preset {resilient}] [--json]
                              {group,provider} name

Preview or save group/provider probe settings.

Effects: Preview by default; --apply saves probe settings. Explicit restart required.

positional arguments:
  {group,provider}      group or provider probe settings
  name                  exact configured name

options:
  -h, --help            show this help message and exit
  --apply               apply only after reviewing the preview and obtaining
                        explicit authorization
  --home-dir HOME_DIR   explicit private Mihomo data directory
  --config CONFIG       explicit core YAML file (private, same scope)
  --url URL             public HTTPS health-check target
  --expected-status EXPECTED_STATUS
                        accepted probe HTTP status range
  --interval INTERVAL   probe interval in seconds
  --timeout TIMEOUT     probe timeout in milliseconds
  --lazy {true,false}   whether the core may defer idle-group probes
  --tolerance TOLERANCE
                        URLTest switching tolerance in milliseconds
  --preset {resilient}  explicit probe settings preset
  --json                emit the mihomoctl/v1 JSON envelope
```

## manual

```text
usage: mihomoctl manual [-h] [--apply] [--home-dir HOME_DIR] [--config CONFIG]
                        [--json]
                        group

Preview conversion to a manual routing group.

Effects: Preview by default; --apply converts the group to a Selector in saved configuration. Explicit restart required.

positional arguments:
  group                exact Selector group name from groups --json

options:
  -h, --help           show this help message and exit
  --apply              apply only after reviewing the preview and obtaining
                       explicit authorization
  --home-dir HOME_DIR  explicit private Mihomo data directory
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

## override

```text
usage: mihomoctl override [-h] --script SCRIPT [--apply] [--flclash-compat]
                          [--home-dir HOME_DIR] [--config CONFIG] [--json]

Preview a trusted routing script.

Effects: Executes the explicitly trusted script for preview; --apply writes its reviewed configuration. Explicit restart required.

options:
  -h, --help           show this help message and exit
  --script SCRIPT      trusted override script; executes code during preview
  --apply              apply only after reviewing the preview and obtaining
                       explicit authorization
  --flclash-compat     explicit compatibility mode for a trusted FlClash
                       script
  --home-dir HOME_DIR  explicit private Mihomo data directory
  --config CONFIG      explicit core YAML file (private, same scope)
  --json               emit the mihomoctl/v1 JSON envelope
```

## ui

```text
usage: mihomoctl ui [-h] [--config CONFIG] [--json]

Show the configured dashboard access URL.

Effects: Read-only inspection; default output omits credentials.

options:
  -h, --help       show this help message and exit
  --config CONFIG  explicit core YAML file (private, same scope)
  --json           emit the mihomoctl/v1 JSON envelope
```
