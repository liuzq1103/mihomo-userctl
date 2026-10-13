"""Read-only service and port observations; lifecycle belongs to Application."""

import os
import hashlib
from pathlib import Path
import socket
import subprocess


try:
    from .controller_types import ControlError
    from . import files
except ImportError:
    from controller_types import ControlError
    import files


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
    return props


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
