"""User-service observation and fail-closed port ownership gates."""
import os
import hashlib
from pathlib import Path
import socket
import subprocess
import sys

try:
    from .controller_types import ControlError
    from . import install_support as files
except ImportError:
    from controller_types import ControlError
    import install_support as files


def command(args, timeout=5):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ControlError("runtime-observation-unavailable") from None


def service_properties(service):
    result = command(["systemctl", "--user", "show", service,
                      "--property=ActiveState,UnitFileState,MainPID,ControlGroup"])
    if result.returncode:
        raise ControlError("user-service-unavailable")
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def listeners(port, proc=Path("/proc")):
    result = []
    for filename in ("tcp", "tcp6"):
        path = proc / "net" / filename
        if not path.exists():
            raise ControlError("listener-inspection-unavailable")
        try:
            for line in path.read_text().splitlines()[1:]:
                row = line.split()
                if len(row) >= 10 and row[3] == "0A" and int(row[1].split(":")[1], 16) == port:
                    result.append({"address": row[1].split(":")[0], "uid": int(row[7]), "inode": row[9], "family": filename})
        except (OSError, ValueError, IndexError):
            raise ControlError("listener-inspection-unavailable") from None
    return result


def belongs(row, properties, proc=Path("/proc")):
    if row["uid"] != os.getuid() or row["family"] != "tcp" or row["address"] != "0100007F":
        return False
    pid = properties.get("MainPID", "0")
    if not pid.isdigit() or int(pid) <= 0:
        return False
    group = properties.get("ControlGroup", "")
    candidates = [proc / pid]
    if group:
        candidates.extend(p for p in proc.iterdir() if p.name.isdigit() and p.name != pid)
    for process in candidates:
        try:
            if process.stat().st_uid != os.getuid():
                continue
            groups = [line.split(":", 2)[-1] for line in (process / "cgroup").read_text().splitlines()]
            if process.name != pid and not any(g == group or g.startswith(group + "/") for g in groups):
                continue
            if any(fd.readlink().as_posix() == "socket:[" + row["inode"] + "]" for fd in (process / "fd").iterdir()):
                return True
        except (OSError, PermissionError):
            continue
    return False


def gate(service, ports, after=False):
    props = service_properties(service)
    for port in ports:
        rows = listeners(port)
        if rows:
            if any(row["uid"] != os.getuid() or row["address"] != "0100007F" or row["family"] != "tcp" for row in rows):
                raise ControlError("port-collision", 1)
            if not all(belongs(row, props) for row in rows):
                raise ControlError("listener-service-ownership-unverified")
        elif after:
            raise ControlError("service-listener-missing", 1)
        else:
            # Kernel decides; this probe is not a reservation.
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    raise ControlError("port-collision", 1) from None
    if after and props.get("ActiveState") != "active":
        raise ControlError("service-not-active-after-start", 1)


def summary(service, port):
    props = service_properties(service)
    rows = listeners(port)
    owned = bool(rows) and all(belongs(row, props) for row in rows)
    return {"service": props.get("ActiveState", "unknown"),
            "enabled": props.get("UnitFileState", "unknown"),
            "port": port, "listener": "PASS" if owned else "UNVERIFIED",
            "readiness": "UNVERIFIED", "authentication": "UNVERIFIED"}


def configured_ports(config, mixed):
    ports, digest = [mixed], None
    if config.is_symlink():
        raise ControlError("config-symlink-not-supported")
    if config.exists():
        try:
            from .controller_config import read_config, endpoint
        except ImportError:
            from controller_config import read_config, endpoint
        text, data, _ = read_config(config)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if "mixed-port" in data:
            matched = data["mixed-port"] == ports[0]
        else:
            entries = data.get("listeners")
            # Documented listeners-only layout: any mixed entry binds the port,
            # as an exact int; malformed shapes cannot establish a match.
            matched = isinstance(entries, list) and any(
                isinstance(entry, dict) and entry.get("type") == "mixed"
                and type(entry.get("port")) is int and entry["port"] == ports[0]
                for entry in entries)
        if not matched:
            raise ControlError("configured-port-mismatch")
        if data.get("external-controller"):
            controller_port, _ = endpoint(data)
            if controller_port in ports:
                raise ControlError("controller-port-conflicts-with-proxy-port")
            ports.append(controller_port)
    return ports, digest


def main():
    action, service, raw_port = sys.argv[1:4]
    if action not in ("start", "restart") or not raw_port.isdigit() or not 1024 <= int(raw_port) <= 65535:
        raise ControlError("invalid-runtime-action")
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "mihomo/config.yaml"
    common = Path(__file__).with_name("common.bash")
    if not common.exists():
        common = Path(__file__).resolve().parents[1] / "src/common.bash"
    files.safe_path(common)
    info = common.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ControlError("unsafe-runtime-module")
    with files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))):
        ports, digest = configured_ports(config, int(raw_port))
        gate(service, ports)
        # Run the existing Bash action/readiness implementation while retaining
        # the same-UID lock; no secrets are added to argv.
        # Fixed code and positional arguments, never an environment-variable
        # bypass or a second entry through the public command dispatcher.
        code = '''source "$1" || exit 2
_muc_load_config || exit 2
[[ $MIHOMO_SERVICE == "$3" && $MIHOMO_PORT == "$4" ]] || exit 2
systemctl --user "$2" "$MIHOMO_SERVICE" || exit 1
_muc_wait_ready
rc=$?
if (( rc )); then
  printf 'mihomoctl: service changed but authenticated readiness failed\\n' >&2
fi
exit "$rc"
'''
        result = subprocess.run(["bash", "-c", code, "mihomo-runtime", str(common), action, service, raw_port])
        if result.returncode:
            return result.returncode
        gate(service, ports, after=True)
        if configured_ports(config, int(raw_port)) != (ports, digest):
            raise ControlError("config-changed-during-runtime-action")
        if len(ports) == 2:
            try:
                from .controller_api import Client
                from .controller_config import read_config, endpoint
            except ImportError:
                from controller_api import Client
                from controller_config import read_config, endpoint
            _, data, _ = read_config(config)
            client = Client(*endpoint(data))
            if client.port != ports[1]:
                raise ControlError("configured-port-changed")
            client.verify()
        print("service=up ready=up endpoint=127.0.0.1:{} shell=unchanged".format(ports[0]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ControlError, files.InstallError, OSError, ValueError) as error:
        print("mihomoctl: " + getattr(error, "code", "runtime-unverified"), file=sys.stderr)
        sys.exit(getattr(error, "rc", 2))
