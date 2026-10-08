"""User-level controller component; no global proxy or daemon."""
import http.client
import json
import os
import socket
import time
from pathlib import Path
try:
    from . import acceptance
except ImportError:
    import acceptance
try:
    from .controller_types import ControlError, LIMIT
except ImportError:
    from controller_types import ControlError, LIMIT

class Client:
    def __init__(self, port, token):
        self.port, self.token = port, token

    def request(self, path, method="GET", body=None, anonymous=False, stream=False, optional=False):
        # http.client ignores all proxy variables and never follows redirects.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        headers = {} if anonymous else {"Authorization": "Bearer " + self.token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, None if body is None else json.dumps(body).encode(), headers)
            response = connection.getresponse()
            if anonymous:
                if response.status != 401:
                    raise ControlError("controller-authentication-not-enforced", 1)
                return None
            if response.status == 401:
                raise ControlError("controller-authentication-failed", 1)
            if optional and response.status in (404, 405):
                raise ControlError("controller-capability-unsupported")
            if response.status not in (200, 204):
                raise ControlError("controller-request-failed", 1)
            raw = response.readline(LIMIT + 1) if stream else response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ControlError("controller-response-too-large")
            value = json.loads(raw) if raw else {}
            if not isinstance(value, dict):
                raise ControlError("controller-response-invalid")
            return value
        except (OSError, http.client.HTTPException):
            raise ControlError("controller-unreachable", 1) from None
        except (ValueError, UnicodeError):
            raise ControlError("controller-response-invalid") from None
        finally:
            connection.close()

    def verify(self):
        binding = acceptance.listener_check(self.port, 5)
        if binding.status != "PASS":
            raise ControlError("controller-" + binding.evidence, 1 if binding.status == "FAIL" else 2)
        # Check kernel socket UID before sending the bearer credential. This is
        # a snapshot, not protection against root or a same-UID adversary.
        owned = []
        try:
            lines = Path("/proc/net/tcp").read_text().splitlines()[1:]
        except OSError:
            raise ControlError("controller-listener-ownership-unverified") from None
        for line in lines:
            fields = line.split()
            if len(fields) >= 8 and fields[3] == "0A" and fields[1] == "0100007F:{:04X}".format(self.port):
                owned.append(int(fields[7]))
        if not owned or any(uid != os.getuid() for uid in owned):
            raise ControlError("controller-listener-not-owned-by-current-user")
        self.request("/version", anonymous=True)
        self.request("/version")

    def lines(self, path, cancelled, duration=30):
        """Bounded HTTP JSON-line stream, with periodic credential revalidation.

        Read timeouts bound cancellation. An idle stream is valid; malformed
        lines, authentication failures and redirects are never capabilities.
        """
        self.verify()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        deadline, buffer = time.monotonic() + duration, b""
        try:
            connection.request("GET", path, headers={"Authorization": "Bearer " + self.token})
            response = connection.getresponse()
            if response.status == 401:
                raise ControlError("controller-authentication-failed", 1)
            if response.status in (404, 405):
                raise ControlError("controller-capability-unsupported")
            if response.status != 200:
                raise ControlError("controller-request-failed", 1)
            while not cancelled.is_set() and time.monotonic() < deadline:
                chunk = response.read1(65536)
                if not chunk:
                    if buffer:
                        raise ControlError("controller-stream-incomplete")
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if len(line) > 65536:
                        raise ControlError("controller-stream-line-too-large")
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ControlError("controller-response-invalid")
                    yield value
                if len(buffer) > 65536:
                    raise ControlError("controller-stream-line-too-large")
        except socket.timeout:
            if buffer:
                raise ControlError("controller-stream-incomplete") from None
            return
        except (OSError, http.client.HTTPException):
            raise ControlError("controller-unreachable", 1) from None
        except (ValueError, UnicodeError):
            raise ControlError("controller-response-invalid") from None
        finally:
            connection.close()
