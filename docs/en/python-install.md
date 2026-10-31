# Standard Python installation

These instructions target version 1.5.0. Index commands require the corresponding PyPI publication; release wheels and local source remain available independently.

```bash
uv tool install mihomo-userctl
pipx install mihomo-userctl
python3 -m pip install --user mihomo-userctl
python3 -m pip install --no-index --find-links /absolute/wheelhouse mihomo-userctl
```

Use `"mihomo-userctl[tui]"` for optional Textual. Python 3.10+ and PyYAML are required. Core and interpreter are separate. Ubuntu PEP 668 may reject pip user installation: prefer uv/pipx or a venv. Never use sudo or bypass the externally-managed marker.

## Local source and development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
python -m pip install -e ".[tui]"
mihomoctl --help
mihomoctl version --json
```

```bash
uv sync --group dev --extra tui
uv run mihomoctl --help
uv run ruff check
uv run pyright
```

## Upgrade and uninstall

```bash
uv tool upgrade mihomo-userctl
uv tool uninstall mihomo-userctl
pipx upgrade mihomo-userctl
pipx uninstall mihomo-userctl
python3 -m pip install --user --upgrade mihomo-userctl
python3 -m pip uninstall mihomo-userctl
```

Run pip in the same interpreter/environment used for installation. Remove legacy distribution `mihomoctl` with its original manager before installing the renamed package; both provide the same CLI. Do not install different methods over each other's launcher. `mihomoctl update` refuses external installs, including `--dry-run`, even if this user still has an old complete-install receipt. Uninstall removes package code; it does not remove manager data or stop a core. Stop the owned runtime explicitly before removing the tool if required.

Offline wheelhouse installation requires all compatible dependency wheels. Installing an sdist offline additionally requires trusted build dependencies. No package post-install hook initializes a manager or downloads a core.

[Setup](setup.md) · [Complete offline installation](offline-install.md) · [CLI](reference/cli.md)
