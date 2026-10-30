# mihomo-userctl · CLI `mihomoctl`

An Agent-first, user-level Mihomo manager for shared Linux servers, implemented in Python.

[中文](README.md) · [Installation](INSTALL.md) · [Documentation](docs/en/README.md)

<!-- stable-version: 1.5.0.dev0 -->
Source version: **1.5.0.dev0**, unreleased. The PyPI commands below describe the installation entry points after formal publication. Until then, use local source or reviewed candidate artifacts; no development Release is promised.

## Two installation paths

For developers who already have uv or pipx, after publication:

```bash
uv tool install mihomo-userctl
pipx install mihomo-userctl
```

Use `"mihomo-userctl[tui]"` for the optional Textual human interface. The minimal CLI requires PyYAML, but includes neither a Python interpreter nor the Mihomo core.

```bash
python3 -m pip install --user mihomo-userctl
python3 -m pip install --no-index --find-links /absolute/wheelhouse mihomo-userctl
```

`pip --user` requires an interpreter that permits user installation. Ubuntu PEP 668 environments may reject it too: use uv, pipx or a venv rather than bypassing system protection. An offline wheelhouse must contain compatible dependency wheels. See [Python installation](docs/en/python-install.md) for source, editable, upgrade and uninstall recipes.

Complete offline bundles remain a separate supported path, containing pinned Python, Textual, dependencies and Mihomo for Ubuntu 22.04/24.04 x86_64. Follow [INSTALL](INSTALL.md), verify provenance and checksums, then run the bundled `./mihomoctl` or explicitly install with `./install.sh --user`. The installer never downloads uv, initializes a manager, starts the core or edits shell startup files.

## Agent entry point

```bash
mihomoctl --help
mihomoctl status --json
mihomoctl doctor --json
mihomoctl groups --json
mihomoctl nodes --json
```

Top-level help supplies workflows, safety boundaries and exit codes; command help describes arguments and effects. Public JSON remains `mihomoctl/v1`: PASS=0, FAIL=1, UNVERIFIED=2. After child startup, `exec`/`direct` preserve child exit/signal semantics.

Record every affected group's original choice. Adjust the regional group first, then its entry group, verify the actual request, explicitly restore all changed choices and read the groups again. `select` already verifies membership, rejects ambiguous provider names and reads back the actual selection. Aggregate groups reject direct leaf selection unless explicitly authorized with `--allow-cross-level`. Selection and probe success do not prove an application's request used a remote node. Current selection persistence (`store-selected`) stays enabled; no selection history or cache-deletion restoration is added.

## Initialize and integrate

Python installations need a trusted core. On a new x86_64 setup, explicitly install the maintained fixed version if needed. Preserve existing managers and active cores:

```bash
mihomoctl core install --version v1.19.32
mihomoctl init --core /absolute/path/to/mihomo
mihomoctl config validate
mihomoctl start
mihomoctl exec -- curl --head https://example.com
mihomoctl direct -- curl --head https://example.com
```

Import subscriptions using private files, private URL files or stdin; preview before digest-bound apply. Never put subscription URLs or secrets on argv. Use declarative bindings and generic integrations for persistent consumers; this tool does not manage third-party application lifecycles. See [setup](docs/en/setup.md), [subscriptions](docs/en/subscriptions.md) and [integrations](docs/en/operations/integrations.md).

TUI is an interactive human interface. Agents must not launch it or reset autonomously. Reset requires `mihomoctl reset --dry-run --json`, explicit human authorization, then `--apply --plan-sha256 HASH` from that preview. State drift invalidates the proof. The digest binds reviewed content; it is not human authorization.

## Isolation and maintenance

Each Linux account owns private manager files, credentials, core process and authenticated ports. Default scope/backend is user/process with 127.0.0.1 listeners and no root requirement; systemd --user is optional. No privilege escalation, global proxy takeover, shell startup edits or other-user operations. System scope and non-local listeners require explicit authorization.

Install, update and uninstall never edit `.bashrc`, `.zshrc`, `.profile` or other shell startup files.

uv/pipx/pip installations are upgraded and uninstalled by their original tool. Built-in `update` refuses to take over an external Python install. If the old `mihomoctl` distribution exists in the same environment, uninstall it with the original tool before installing the renamed distribution. Complete installations retain transactional updates. Old updaters cannot recognize renamed assets: 1.4.x users verify the new complete bundle and run its installer once, preserving manager data, credentials and the active core.

Successful managed operations retain only current state. Private journals recover unfinished operations and are removed on completion; historical rollback remains disabled. Package-manager caches are outside mihomoctl's automatic cleanup. [Security](docs/en/security.md) · [Updates](docs/en/update.md) · [Release acceptance](docs/en/operations/release.md)

## Related projects and licenses

See [mihomo-ctrl](https://github.com/wonder-missing/mihomo-ctrl) for an Agent CLI workflow and [mihoro](https://github.com/spencerwooo/mihoro) for Linux user-instance management. This project focuses on shared-server isolation, generic CLI/integration, transactions and complete offline delivery; these links imply no dependency or affiliation.

The manager uses [MIT](LICENSE). Complete bundles retain component licenses for Python, dependencies and Mihomo (GPL-3.0), listed in `licenses.json`, `core/LICENSE` and `core/SOURCE.txt`. [CHANGELOG](CHANGELOG.md) · [Architecture](docs/architecture-v1.md)
