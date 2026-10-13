# Complete V1 offline installation

[中文](../zh-CN/offline-install.md) · [Installation contract](../../INSTALL.md) · [Local agent prompt](agent-local-install-prompt.md)

This flow applies to 1.0.2 and later releases retaining the same kit format. A complete kit contains
only the mihomoctl control plane, source archives, project wheel and Python dependency wheels.
**Prepare or install Mihomo, OpenCode, Codex and Node yourself**; they are not included.

## Target and trusted material

| Target | OS | Interpreter | Architecture |
| --- | --- | --- | --- |
| ubuntu22.04-x86_64-py310 | Ubuntu 22.04 | CPython 3.10 | x86_64 |
| ubuntu24.04-x86_64-py312 | Ubuntu 24.04 | CPython 3.12 | x86_64 |

Inspect `uname -m`, `cat /etc/os-release` and `/usr/bin/python3 --version` first.
An Anaconda `python` on PATH does not change the installer's preference for `/usr/bin/python3`.
System Python 3.10.12 with PyYAML 5.4.1 does not satisfy `PyYAML>=6.0.1`, even when importing yaml
succeeds. Use the matching wheelhouse. Dependencies go into mihomoctl's own installation generation;
system and Anaconda PyYAML installations are not upgraded.

The maintainer supplies `mihomoctl-VERSION-offline-TARGET.tar.gz` and its `.tar.gz.sha256` sidecar.
**Obtain the expected digest, exact version and full commit from an independently trusted channel**
that cannot be modified together with the shared archive, such as a separately checked release record.
For ordinary source archives, `SHA256SUMS` is a release attachment, not a required file inside the
archive. Complete kits also contain an internal `SHA256SUMS`.

A shared directory is only storage. Mode 0777, ownership by the acting user or a writable mount
cannot establish independent provenance. Matching copy hashes, enclosed receipts and checksum files
beside the archive cannot do so either. Without a trusted external digest, report `UNVERIFIED` and
stop. Never substitute a freshly computed hash or change the shared directory's contents/permissions.

## Verify, then safely extract

Use system tools and the Python standard library before running received project code:

```bash
ARCHIVE='/absolute/shared/mihomoctl-1.0.2-offline-ubuntu22.04-x86_64-py310.tar.gz'
EXPECTED_SHA256='<64-character digest from an independently trusted channel>'
WORK=$(mktemp -d "$HOME/mihomoctl-offline.XXXXXX")
chmod 700 "$WORK"
cp -- "$ARCHIVE" "$WORK/"
ARCHIVE="$WORK/$(basename "$ARCHIVE")"
printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum --check --strict
DEST="$WORK/unpacked"
```

Stop on any failure. This standard-library extraction rejects links, special files, escapes,
duplicates and multiple roots; it bounds members and actual copied bytes. `DEST` must not exist.

```bash
/usr/bin/python3 - "$ARCHIVE" "$DEST" <<'PY'
import os, pathlib, sys, tarfile
os.umask(0o077)
out = pathlib.Path(sys.argv[2])
out.mkdir(mode=0o700)
seen, roots, used = set(), set(), 0
with tarfile.open(sys.argv[1], 'r:gz') as package:
    for index, entry in enumerate(package):
        parts = entry.name.split('/')
        if (index >= 20000 or not entry.isfile() or len(parts) < 2
                or any(p in ('', '.', '..') for p in parts)
                or '\\' in entry.name or ':' in entry.name
                or any(ord(c) < 32 or ord(c) == 127 for c in entry.name)
                or entry.name in seen or entry.size < 0):
            raise SystemExit('unsafe archive member')
        seen.add(entry.name)
        roots.add(parts[0])
        used += entry.size
        if len(roots) != 1 or used > 512 * 1024 * 1024:
            raise SystemExit('archive limit exceeded')
        target = out.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with package.extractfile(entry) as source, target.open('xb') as result:
            remaining = entry.size
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    raise SystemExit('truncated member')
                result.write(block)
                remaining -= len(block)
        target.chmod(0o600)
PY
```

Confirm the single kit root, then check its internal checksums and source identity:

```bash
KIT="$WORK/unpacked/mihomoctl-1.0.2-offline-ubuntu22.04-x86_64-py310"
cd "$KIT"
sha256sum --check --strict SHA256SUMS
cd release
sha256sum --check --strict SHA256SUMS
ARCHIVE="$KIT/release/mihomoctl-1.0.2.tar.gz"
DEST="$WORK/source"
```

Read `bundle-manifest.json` and `release/build-receipt.json`, checking version, commit and target
against the trusted record. Repeat the extraction block above with the new `ARCHIVE` and `DEST`.
Review the extracted INSTALL, source and repository constraints. Reject bytecode (`.pyc`, `.pyo`,
`__pycache__`) and unreviewed files. Statically check five matching versions: manifest, pyproject,
Python `__version__`, install.sh `VERSION=` and src/common.bash `MIHOMO_USERCTL_VERSION`.

## Install the control plane

```bash
cd "$WORK/source/mihomoctl-1.0.2"
bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse" --dry-run
bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse"
"$HOME/.local/bin/mihomoctl" version
/usr/bin/python3 -I scripts/bootstrap.py verify
```

Dry-run and installation share dependency/version/wheel compatibility prechecks. Missing packages,
wrong hashes or unsatisfied dependency versions stop installation; never run apt/npm/pip online as
a fallback. Omit wheelhouse only if both dependency versions and imports satisfy the selected Python.
Do not use sudo; system installation follows INSTALL's separate explicit `--system` flow.

The installer never writes `.bashrc`, registers `proxy_on`, `proxy_status`, `with_proxy` or hooks,
starts/stops services, or adopts/replaces existing Mihomo cores. Defaults are user scope and process
backend, with the control plane at `~/.local/share/mihomoctl/install`. Set ports later using explicit
`mihomoctl init --port PORT` and named listener profiles. For 0.x migration, inspect
`mihomoctl migrate --dry-run` before explicitly choosing `--apply`. Use explicit `mihomoctl exec`,
`env` or `integration` for proxy access. Do not start services, refresh subscriptions or send model
requests without authorization. Missing external acceptance is `UNVERIFIED`; report actual versions,
paths, provenance, backups/rollback and test results under the [delivery contract](deployment-contract.md).

## Maintainer preparation

Only prepare dependencies in a matching networked build environment; never download on the offline host:

```bash
python3 scripts/build_release.py --output dist
python3 -m pip download --only-binary=:all: --require-hashes \
  -r requirements-lock.txt -d /absolute/path/to/wheelhouse
python3 scripts/build_offline_bundle.py --artifacts dist \
  --wheelhouse /absolute/path/to/wheelhouse \
  --target ubuntu22.04-x86_64-py310 --output dist
```

Use the other target for Ubuntu 24.04. The builder consumes local material only, checks locked hashes
and refuses overwrites. Both target kits and sidecars must be supplied to `scripts/verify_release.py`
using `--offline-artifacts DIR` (defaults to the normal artifacts directory). Publication requires
both platforms' actual network-isolated kit install/update/rollback reports plus existing release
gates. Development `--worktree` kits cannot be published; never mark unexecuted checks PASS.
