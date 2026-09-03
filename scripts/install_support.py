#!/usr/bin/env python3
"""Installer-owned locking, immutable generations, provenance, and rollback.

The updater invokes install.sh; it never implements a second installer.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

BEGIN = "# >>> mihomo-userctl managed loader >>>"
END = "# <<< mihomo-userctl managed loader <<<"
RUNTIME = {"src/common.bash": "common.bash", "src/shell.bash": "shell.bash",
           "src/mihomoctl": "mihomoctl", "completions/mihomoctl.bash": "completion.bash",
           "scripts/update.py": "update.py", "scripts/install_support.py": "install_support.py",
           "scripts/acceptance.py": "acceptance.py"}


class InstallError(Exception):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(value, directory=False):
    path = Path(value)
    if not path.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise InstallError("paths-must-be-absolute-without-control-characters")
    if ".." in path.parts:
        raise InstallError("parent-path-components-not-supported")
    for part in [path] + list(path.parents):
        if part.is_symlink():
            raise InstallError("symlink-path-not-supported")
        # Root-owned sticky /tmp is a valid ancestor of our private staging HOME;
        # writable non-sticky ancestors would allow replacement of owned children.
        if part.exists() and part.is_dir() and part.stat().st_mode & 0o022:
            if not (part.stat().st_uid == 0 and part.stat().st_mode & stat.S_ISVTX):
                raise InstallError("unsafe-writable-path-ancestor")
    ancestor = path if path.exists() else path.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if ancestor.stat().st_uid != os.getuid():
        raise InstallError("path-not-owned-by-current-user")
    if ancestor.stat().st_mode & 0o022:
        raise InstallError("path-is-writable-by-group-or-others")
    if directory and path.exists() and not path.is_dir():
        raise InstallError("expected-directory")
    return path


def paths():
    home = safe_path(os.environ["HOME"], True)
    config = safe_path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")), True)
    data = safe_path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share")), True)
    return home, config, data


def atomic_bytes(path, data, mode=600):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), int(str(mode), 8))
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def preflight(bashrc):
    home, config, data = paths()
    for directory in (home / ".local/bin", config / "mihomo", data / "mihomo-userctl",
                      data / "mihomo-userctl-backups"):
        safe_path(directory, True)
    for file in (home / ".local/bin/mihomoctl", config / "mihomo/mihomo-shell.conf", Path(bashrc)):
        safe_path(file)


def write_json(path, data):
    atomic_bytes(path, (json.dumps(data, sort_keys=True, indent=2) + "\n").encode())


def owned_json(path):
    path = safe_path(path)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise InstallError("metadata-must-have-mode-600")
    return json.loads(path.read_text())


@contextlib.contextmanager
def locked(data):
    directory = safe_path(Path(data) / "mihomo-userctl-lock", True)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise InstallError("unsafe-lock-directory")
    lock = directory / "operation.lock"
    inherited = os.environ.get("MIHOMO_INSTALL_LOCK_FD")
    if inherited:
        fd = int(inherited)
        if os.fstat(fd).st_ino != lock.stat().st_ino or os.fstat(fd).st_dev != lock.stat().st_dev:
            raise InstallError("invalid-inherited-lock")
        yield fd
        return
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.getuid() or stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
            raise InstallError("unsafe-operation-lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError("another-install-update-or-uninstall-is-running") from None
        yield fd
    finally:
        os.close(fd)


def current_generation(root):
    pointer = Path(root) / "current"
    if not pointer.is_symlink():
        raise InstallError("installation-metadata-missing-use-migration-guide")
    name = os.readlink(pointer)
    if not re.fullmatch(r"generations/[a-f0-9]{32}", name):
        raise InstallError("invalid-generation-pointer")
    return safe_path(Path(root) / name, True)


def metadata(root):
    root = safe_path(root, True)
    generation = current_generation(root)
    record = owned_json(generation / "installation.json")
    if (not isinstance(record, dict) or record.get("schema") != 1 or record.get("install_root") != str(root)
            or record.get("generation") != generation.name
            or record.get("home") != str(Path(os.environ["HOME"]))):
        raise InstallError("installation-metadata-does-not-match-current-account")
    for key in ("home", "config_home", "data_home", "bashrc", "bin_file"):
        safe_path(record[key])
    source = record.get("source", {})
    if (not isinstance(source, dict) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", record.get("version", ""))
            or source.get("kind") not in ("source-snapshot", "git-checkout", "github-release-source")
            or (source.get("commit") is not None and
                not re.fullmatch(r"[a-f0-9]{40}", source["commit"]))):
        raise InstallError("invalid-version-or-source-metadata")
    return record


def loader_block(path):
    text = Path(path).read_text()
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise InstallError("startup-loader-missing-or-ambiguous")
    start, end = text.index(BEGIN), text.index(END)
    if end < start:
        raise InstallError("invalid-startup-loader")
    return text[start:end + len(END)]


def verify_generation(record):
    root = Path(record["install_root"])
    generation = root / "generations" / record["generation"]
    if (set(record["runtime_hashes"]) != set(RUNTIME.values()) or
            set(record["bootstrap_hashes"]) != {"mihomoctl", "common.bash", "shell.bash", "completion.bash"}):
        raise InstallError("incomplete-installation-integrity-record")
    for name, expected in record["runtime_hashes"].items():
        if name not in RUNTIME.values() or digest(safe_path(generation / name)) != expected:
            raise InstallError("installed-code-modified-review-local-customizations")


def verify_installed(record):
    verify_generation(record)
    root = Path(record["install_root"])
    for name, expected in record["bootstrap_hashes"].items():
        target = Path(record["bin_file"]) if name == "mihomoctl" else root / name
        if digest(safe_path(target)) != expected:
            raise InstallError("installed-launcher-modified-review-local-customizations")
    block_hash = hashlib.sha256(loader_block(record["bashrc"]).encode()).hexdigest()
    if block_hash != record["loader_sha256"]:
        raise InstallError("managed-loader-modified-review-local-customizations")


def switch(root, name):
    root = Path(root)
    if name is None:
        (root / "current").unlink(missing_ok=True)
    else:
        if not re.fullmatch(r"generations/[a-f0-9]{32}", name):
            raise InstallError("invalid-generation-pointer")
        tmp = root / (".current-" + uuid.uuid4().hex)
        os.symlink(name, tmp)
        os.replace(tmp, root / "current")
    sync_dir(root)


def bootstrap(root, config, bin_file):
    # These format-1 launchers are stable across releases. Read the pointer once;
    # every module in an invocation then comes from that immutable generation.
    prefix = ("#!/usr/bin/env bash\n_muc_root=" + shlex.quote(str(root)) + "\n"
              '_muc_generation=$(readlink -- "$_muc_root/current")\n'
              'if [[ ! $_muc_generation =~ ^generations/[a-f0-9]{32}$ ]]; then\n'
              "  printf 'mihomo-userctl: no complete generation; inspect installation backup\\n' >&2\n"
              '  return 2 2>/dev/null || exit 2\nfi\n'
              '_muc_generation_dir="$_muc_root/$_muc_generation"\n'
              'MIHOMO_USERCTL_CONFIG=' + shlex.quote(str(config / "mihomo/mihomo-shell.conf")) + "\n"
              'MIHOMO_USERCTL_CREDENTIALS=' + shlex.quote(str(config / "mihomo/client.env")) + "\n"
              'MIHOMO_USERCTL_BIN=' + shlex.quote(str(bin_file)) + "\n")
    cli = (prefix + 'export MIHOMO_USERCTL_CONFIG MIHOMO_USERCTL_CREDENTIALS MIHOMO_USERCTL_BIN\n'
           'export MIHOMO_USERCTL_LIB_DIR="$_muc_generation_dir"\n'
           'export MIHOMO_USERCTL_INSTALL_ROOT="$_muc_root"\n'
           'exec bash "$_muc_generation_dir/mihomoctl" "$@"\n')
    result = {"mihomoctl": cli}
    for name in ("common.bash", "shell.bash", "completion.bash"):
        result[name] = (prefix + '# shellcheck source=/dev/null\n'
                        'source "$_muc_generation_dir/' + name + '"\n'
                        'unset _muc_root _muc_generation _muc_generation_dir\n')
    return result


def prepare(source, bashrc, backup, source_record=None):
    home, config, data = paths()
    root = data / "mihomo-userctl"
    bashrc = safe_path(bashrc)
    if home not in bashrc.parents:
        raise InstallError("startup-file-must-be-inside-HOME")
    manifest = json.loads((source / "release-manifest.json").read_text())
    release_version = manifest.get("version", "")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release_version):
        raise InstallError("invalid-release-version")
    if manifest != {"format": 1, "version": release_version, "update_protocol": 1,
                    "validation_profile": "installation-v1"}:
        raise InstallError("incompatible-installation-manifest")
    for file, pattern in (("install.sh", r"^VERSION=([^\n]+)$"),
                          ("src/common.bash", r'^MIHOMO_USERCTL_VERSION="([^"]+)"$')):
        marker = re.search(pattern, (source / file).read_text(), re.M)
        if marker is None or marker[1] != release_version:
            raise InstallError("source-version-markers-disagree")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if (root / "pending-install.json").exists():
        raise InstallError("interrupted-installation-rollback-required")
    generation_parent = safe_path(root / "generations", True)
    generation_parent.mkdir(mode=0o700, exist_ok=True)
    generation = generation_parent / uuid.uuid4().hex
    generation.mkdir(mode=0o700)
    for src, dst in RUNTIME.items():
        candidate = safe_path(source / src)
        atomic_bytes(generation / dst, candidate.read_bytes(), 755 if dst == "mihomoctl" else 644)
    provenance = {"kind": "source-snapshot", "commit": None, "verification": "unknown"}
    if source_record:
        provenance = owned_json(source_record)
    elif (source / ".git").exists():
        proc = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True)
        dirty = subprocess.run(["git", "-C", str(source), "status", "--porcelain"], capture_output=True, text=True)
        if proc.returncode == 0 and re.fullmatch(r"[a-f0-9]{40}\n?", proc.stdout):
            provenance = {"kind": "git-checkout", "commit": proc.stdout.strip(),
                          "dirty": bool(dirty.returncode or dirty.stdout), "verification": "local-git-only"}
    bin_file = home / ".local/bin/mihomoctl"
    launchers = bootstrap(root, config, bin_file)
    generated = generation / "bootstrap"
    generated.mkdir(mode=0o700)
    for name, content in launchers.items():
        atomic_bytes(generated / name, content.encode(), 755 if name == "mihomoctl" else 644)
    loader = (source / "examples/bashrc-loader.bash").read_text()
    loader = loader.replace('_muc_shell="${XDG_DATA_HOME:-$HOME/.local/share}/mihomo-userctl/shell.bash"',
                            "_muc_shell=" + shlex.quote(str(root / "shell.bash")))
    atomic_bytes(generated / "loader.bash", loader.encode(), 644)
    record = {"schema": 1, "version": release_version, "generation": generation.name,
              "install_root": str(root), "home": str(home), "config_home": str(config),
              "data_home": str(data), "bin_file": str(bin_file), "bashrc": str(bashrc),
              "source": provenance,
              "runtime_hashes": {name: digest(generation / name) for name in RUNTIME.values()},
              "bootstrap_hashes": {name: digest(generated / name) for name in launchers},
              "loader_sha256": hashlib.sha256(loader_block(generated / "loader.bash").encode()).hexdigest()}
    if (root / "current").is_symlink():
        old = metadata(root)
        verify_installed(old)
        if (old["bootstrap_hashes"] != record["bootstrap_hashes"] or
                old["loader_sha256"] != record["loader_sha256"]):
            raise InstallError("bootstrap-layout-change-requires-reviewed-migration")
    write_json(generation / "installation.json", record)
    sync_dir(generation_parent)
    previous = os.readlink(root / "current") if (root / "current").is_symlink() else None
    transaction = {"schema": 1, "install_root": str(root), "generation": generation.name,
                   "previous": previous, "backup": str(backup), "record": record}
    transaction["before_files"] = {}
    for row in (backup / "manifest.tsv").read_text().splitlines():
        kind, state, name, target = row.split("\t")
        if kind == "file":
            transaction["before_files"][target] = ({"sha256": digest(backup / name),
                "mode": stat.S_IMODE((backup / name).stat().st_mode)} if state == "present" else None)
    for file in backup.iterdir():
        sync_file(file)
    sync_dir(backup)
    write_json(backup / "transaction.json", transaction)
    # Keep the installer-owned recovery implementation with every backup.
    atomic_bytes(backup / "restore.py", Path(__file__).read_bytes(), 600)
    write_json(root / "pending-install.json", {"backup": str(backup)})
    print(generation)


def publish(backup):
    txn = owned_json(backup / "transaction.json")
    record = txn["record"]
    # Verify complete generation and stable bootstrap before one atomic switch.
    verify_installed(record)
    for name in record["bootstrap_hashes"]:
        sync_file(record["bin_file"] if name == "mihomoctl" else Path(record["install_root"]) / name)
    sync_file(record["bashrc"])
    sync_file(Path(record["config_home"]) / "mihomo/mihomo-shell.conf")
    for directory in (Path(record["bin_file"]).parent, Path(record["bashrc"]).parent,
                      Path(record["config_home"]) / "mihomo"):
        sync_dir(directory)
    switch(txn["install_root"], "generations/" + txn["generation"])
    if metadata(txn["install_root"])["version"] != record["version"]:
        raise InstallError("post-publish-version-check-failed")
    verify_installed(record)


def finish(backup):
    txn = owned_json(backup / "transaction.json")
    root = Path(txn["install_root"])
    txn["after_hashes"] = {}
    for row in (backup / "manifest.tsv").read_text().splitlines():
        kind, _, _, target = row.split("\t")
        if kind == "file":
            txn["after_hashes"][target] = digest(target)
    write_json(backup / "transaction.json", txn)
    write_json(backup / "result.json", {"files": "PASS", "generation": txn["generation"]})
    (root / "pending-install.json").unlink()
    sync_dir(root)


def rollback(backup):
    txn = owned_json(backup / "transaction.json")
    record = txn["record"]
    root = safe_path(txn["install_root"], True)
    allowed = {str(root / name) for name in ("common.bash", "shell.bash", "completion.bash")}
    allowed.update([record["bin_file"], str(Path(record["config_home"]) / "mihomo/mihomo-shell.conf"), record["bashrc"]])
    entries = [line.split("\t") for line in (backup / "manifest.tsv").read_text().splitlines()]
    dirs = {str(Path(record["bin_file"]).parent), str(root), str(Path(record["config_home"]) / "mihomo")}
    if (any(len(row) != 4 or row[0] not in ("file", "directory") or
            (row[3] not in (allowed if row[0] == "file" else dirs)) for row in entries)
            or len(entries) != len(allowed) + len(dirs)
            or {row[3] for row in entries} != allowed | dirs
            or set(txn.get("before_files", {})) != allowed):
        raise InstallError("invalid-backup-manifest")
    active = os.readlink(root / "current") if (root / "current").is_symlink() else None
    if active not in (txn["previous"], "generations/" + txn["generation"]):
        raise InstallError("stale-backup-cannot-rollback-a-later-update")
    result_file = backup / "result.json"
    if result_file.exists() and owned_json(result_file).get("files") == "ROLLED_BACK":
        if active != txn["previous"]:
            raise InstallError("rollback-record-does-not-match-active-generation")
        print("PASS\trollback\talready-restored;no-files-replaced")
        return
    # Validate ALL backup payloads before restoring any active file. A retry of
    # an interrupted rollback may already contain some original bytes.
    restore = []
    for kind, state, name, target in entries:
        path = safe_path(target)
        if kind == "directory":
            if state != "absent" and not re.fullmatch(r"present:[0-7]{3,4}", state):
                raise InstallError("invalid-backup-directory-state")
            continue
        original = txn["before_files"][target]
        if state == "present" and original is not None and Path(name).name == name:
            src = safe_path(backup / name)
            data = src.read_bytes()
            if hashlib.sha256(data).hexdigest() != original["sha256"]:
                raise InstallError("backup-payload-damaged")
            restore.append((path, data, oct(original["mode"])[2:]))
        elif state == "absent" and original is None:
            restore.append((path, None, None))
        else:
            raise InstallError("invalid-backup-state")
        if target in txn.get("after_hashes", {}):
            actual = digest(path) if path.exists() else None
            old_hash = original["sha256"] if original else None
            if actual not in (txn["after_hashes"][target], old_hash):
                raise InstallError("files-changed-after-update-review-before-rollback")
    if txn["previous"] is not None:
        previous = safe_path(root / txn["previous"], True)
        verify_generation(owned_json(previous / "installation.json"))
        switch(root, txn["previous"])
    for path, data, mode in restore:
        if data is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_bytes(path, data, mode)
        else:
            path.unlink(missing_ok=True)
    if txn["previous"] is None:
        switch(root, None)
    (root / "pending-install.json").unlink(missing_ok=True)
    for kind, state, _, target in entries:
        if kind == "directory":
            if target not in dirs:
                raise InstallError("invalid-backup-directory")
            if state.startswith("present:"):
                os.chmod(target, int(state.split(":")[1], 8))
    write_json(backup / "result.json", {"files": "ROLLED_BACK"})
    print("PASS\trollback\tprevious-active-files-restored")


def main():
    action = sys.argv[1]
    if action == "preflight":
        preflight(sys.argv[2])
        return 0
    if action == "bashrc":
        root = Path(sys.argv[2])
        if (root / "current").is_symlink():
            record = metadata(root)
            if sys.argv[4] == "1" and sys.argv[3] != record["bashrc"]:
                raise InstallError("startup-path-conflicts-with-installed-metadata")
            print(record["bashrc"])
        else:
            if (root / "common.bash").exists() and sys.argv[4] != "1":
                raise InstallError("legacy-installation-requires-explicit-bashrc")
            print(sys.argv[3])
        return 0
    if action == "locked":
        _, _, data = paths()
        with locked(data) as fd:
            env = dict(os.environ, MIHOMO_INSTALL_LOCK_FD=str(fd))
            return subprocess.call(sys.argv[2:], env=env, pass_fds=(fd,))
    if action == "prepare":
        prepare(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]),
                Path(sys.argv[5]) if len(sys.argv) > 5 else None)
    elif action == "publish":
        publish(Path(sys.argv[2]))
    elif action == "finish":
        finish(Path(sys.argv[2]))
    elif action == "rollback":
        backup = safe_path(Path(sys.argv[2]))
        txn = owned_json(backup / "transaction.json")
        with locked(txn["record"]["data_home"]):
            rollback(backup)
    elif action == "uninstall-clean":
        root = safe_path(sys.argv[2], True)
        parent = root / "generations"
        if parent.exists():
            safe_path(parent, True)
            for generation in parent.iterdir():
                if not re.fullmatch(r"[a-f0-9]{32}", generation.name):
                    raise InstallError("unknown-generation-directory")
                safe_path(generation, True)
            (root / "current").unlink(missing_ok=True)
            shutil.rmtree(parent)
    else:
        raise InstallError("unknown-installer-operation")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InstallError as error:
        print("FAIL\tinstaller-support\t" + str(error), file=sys.stderr)
        sys.exit(4 if "another-install" in str(error) else 2)
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        print("FAIL\tinstaller-support\toperation-failed-inspect-private-backup", file=sys.stderr)
        sys.exit(2)
