# 标准 Python 安装

源码 1.5.0.dev0 尚未发布。公共索引命令须等正式发布后使用。

```bash
uv tool install mihomo-userctl
pipx install mihomo-userctl
python3 -m pip install --user mihomo-userctl
python3 -m pip install --no-index --find-links /absolute/wheelhouse mihomo-userctl
```

需要可选 Textual 时安装 `"mihomo-userctl[tui]"`。要求 Python 3.10+ 和 PyYAML；解释器及核心单独准备。Ubuntu PEP 668 可能拒绝 pip 用户安装，推荐 uv/pipx 或 venv，不使用 sudo 或绕过系统管理标记。

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

pip 必须使用原安装解释器/环境。旧 distribution `mihomoctl` 与新包提供同名 CLI，应先用原工具卸载旧包。不同安装方式不得覆盖彼此入口。即使用户目录有旧完整包回执，外部 Python 安装也不能使用内置 update 接管它，`--dry-run` 同样会被拒绝。卸载删除程序包，不删除 manager 数据、不停止核心；需要停止时先显式停止自己的运行时。

离线 wheelhouse 必须包含所有匹配的依赖 wheel；离线安装 sdist 还需可信构建依赖。安装包没有自动初始化 manager 或下载核心的后置钩子。

[Setup](setup.md) · [Complete offline installation](offline-install.md) · [CLI](reference/cli.md)
