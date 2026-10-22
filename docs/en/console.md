# Console

## Choose a frontend

`mihomoctl tui` chooses Textual if importable, otherwise the numbered menu. Opening a console never installs dependencies. An interactive Linux terminal (including SSH PTY or tmux) is required.

| Entry | Use | Delay tests |
| --- | --- | --- |
| `mihomoctl tui --engine plain` or `--plain` | Numbered tasks: status, node selection, subscriptions, controller setup, lifecycle, mode, restore, probe settings, journal and access | **No speed test** |
| `mihomoctl tui --engine curses` | Standard-library, two-pane group/node view; zero extra UI installation | `t` tests a node; `c` connections, `f` traffic |
| `mihomoctl tui --engine textual` | Full pages, search, single/batch delay tests, diagnostics and previews | `t` single, `T` batch |

`mihomoctl --help` groups commands with English descriptions under common, service/configuration, nodes/routing, environment/access and installation/release. Bare `mihomoctl` shows the same guide, then reports a missing command with exit code 2.

## Install Textual privately for the current user

The CLI requires Python 3.10+. In an online preparation environment matching the target interpreter and architecture, explicitly download the pinned wheels:

```bash
python3 -m pip download --require-hashes --only-binary=:all: \
  -r scripts/textual-requirements.txt -d /ABS/wheelhouse
bash install.sh --user --python /usr/bin/python3 --wheelhouse /ABS/wheelhouse --extras tui
mihomoctl tui --engine textual
```

The canonical private-install command is `bash install.sh --user --python <python> --wheelhouse <wheelhouse-dir> --extras tui`.

Run installation from the complete release source directory. `--extras` is repeatable; `tui` pins textual==8.2.8. Explicit requests require a wheelhouse with PyYAML, Textual and all dependencies; missing extra wheels fail with `extra-wheels-unavailable`, naming the group and missing requirement. The installer is offline: it only reads local wheels, never downloads, runs system pip or writes system site-packages, so no sudo is needed. Dependencies share the generation's private `lib/`, ownership checks, file digests and read-only lifecycle. The launcher prepends that directory to its import path. Unknown groups fail with `unknown-extra`. A fresh install without extras adds no UI packages. An upgrade without explicit extras inherits the installed selection: if the current wheelhouse lacks the extra, its attributed, verified modules and distribution metadata are carried forward and reported in `extras_carried_forward`. This works with the PyYAML-only release kit. If no attributed copy exists, the group is removed with an `extras-dropped` warning in both the result and record. `extra_packages` records the top-level files/directories belonging to each extra. `bootstrap.py verify/status` reports extras. The offline release bundle does not additionally include Textual wheels.

`mihomoctl update --extras tui --wheelhouse /ABS/wheelhouse` explicitly selects the extra, while `mihomoctl update --no-extras` clears it. These options also apply with a local source or `--latest`. Bootstrap `install` supports the same mutually exclusive options. Omitting both means inherit; explicitly clearing means no extras.

If this interpreter cannot import textual/rich, use `mihomoctl tui --engine curses` and press `t`, or perform the private install above.

## Pages and delay tests

The primary navigation offers Overview, Nodes, Subscriptions and Access; More contains the other pages. 80×24 uses the full layout; 60×14 uses a compact layout. `--ascii` selects ASCII markers; `--theme dark|light` sets the theme, and `NO_COLOR=1` disables color. No special font is required.

| Page identifier | Contents |
| --- | --- |
| overview | Controller/service observations, rates, memory, connections, initialization, lifecycle and routing mode |
| proxies | Group/node panes, search, sort, confirmed selection, delay tests, manual-group and trusted JS previews |
| subscriptions | Source, policy, counts, preview, save and pending restart; legacy profiles routes here |
| profile | Redacted proxy profiles, declarative bindings and environment boundaries; no third-party lifecycle management |
| connections | Read-only chains/traffic, search, sort and pause; no connection close action |
| rules | Rule-type counts and rule provider state; no private rule body |
| logs | Controller stream, level and pause; `: journal` queries service history |
| providers | Type, node count, update time and explicit refresh |
| diagnostics | General runtime health with evidence levels |
| runtime | Seven facts: core, controller, listeners, active config, proxy mode, TUN and errors |

On Nodes, choose a group then a node. Enter selects a Selector member; automatic groups are read-only. `t` tests the current node; `T` asks for confirmation before testing visible nodes, with at most four concurrent probes. The delay-ms column shows `delay_ms`. The fixed target is `https://www.gstatic.com/generate_204`. This measures public HTTPS delay, not bandwidth or model end-to-end success; `model_request: UNVERIFIED` means no model request was verified. `: cancel` or Esc cancels queued probes; running requests finish or time out. `v` shows the complete result.

Delay HTTP 404 maps to `node-not-in-core` (节点不在核心代理表中), 503 to `node-unreachable` (节点存在但探测失败), and 504 to `delay-timeout` (探测超时). A name missing at the pre-check yields `unknown-node` and the exact requested name. Batch failure rows retain these codes. `: chain` explains missing references, automatic paths and shared entry groups without changing the chain verdict. See [troubleshooting](troubleshooting.md).

## Keys and commands

Textual: Tab/Shift+Tab changes focus, arrows browse, Enter selects/confirms; `/` search, `r` refresh, `t` single delay, `T` batch, `[`/`]` previous/next group; `p` pauses connections/logs, `s` changes sorting, `c` connections, `f` traffic, `v` full result; `m` manual-group preview, `o` trusted script preview, `y` review and save; Esc cancels input/preview/queued tests, `q` outside input or Ctrl+C exits, `?` opens help, `:` opens commands. Letters typed into inputs do not trigger global actions.

curses: arrows browse, Tab/left/right changes pane, Enter enters nodes or selects; `/` search, `r` refresh, `t` delay, `c` connections, `f` traffic, `m` manual preview, `o` script preview, `y` save, `q`/Esc quit. Two legend rows use terminal display width. The plain menu uses the displayed numbers and has no Textual shortcuts or speed test.

Textual `:` commands (these are not shell commands):

```text
page overview|proxies|subscriptions|profile|connections|rules|logs|providers|diagnostics|runtime
group GROUP_NAME
start
stop
restart
mode rule|global|direct
dns NAME [TYPE]
provider NAME
subscribe /ABS/private-nodes.yaml
subscribe-url /ABS/private-url.txt
chain
health-check group "Auto" --preset resilient
health-check provider "nodes" --timeout 5000
health
ready
doctor
status
profile
profiles
rules-status
rules-check
journal --since "2026-10-01" --until "2026-10-22"
diagnose url PUBLIC_HTTPS_URL
diagnose process PID
cancel
log-level debug|info|warning|error
theme dark|light
```

## Probe settings and saving

CLI examples preview first; review before adding `--apply` to save:

```bash
mihomoctl health-check group "Auto" --preset resilient --json
mihomoctl health-check provider "nodes" --timeout 5000 --json
```

In the numbered probe task and after Textual `: health-check`, the first word must literally be `group` or `provider`, followed by the name: `group "Ai+"`, never just `Ai+`. Group probes accept only configured `url-test` / `fallback` groups. For a Selector, probe the provider behind it using `provider NAME`. Options: `--url`, `--expected-status`, `--interval` (seconds), `--timeout` (milliseconds), `--lazy true|false`, `--tolerance` (milliseconds), and `--preset resilient`. Textual `y` confirms saving. Restart explicitly to activate saved changes; reimporting a subscription can overwrite probe settings. Provider probes affect every referencing group.

Refresh retains selection/search. Failed refreshes retain the previous snapshot with stale/error evidence; unobserved facts remain UNVERIFIED. Writes are never replayed automatically. Saving and activation are separate; restarting interrupts connections. `--details` explicitly permits private connection/log details, while known credentials remain masked; logs are not exported by default.

Subscription/rule/policy operations use the same manager, core path and safety gates. See [subscriptions](subscriptions.md), [rules](rules.md) and [CLI reference](reference/cli.md). JS overrides execute trusted code; Node vm is not a sandbox.
