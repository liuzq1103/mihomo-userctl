"""Bounded, renderer-independent console state and task scheduling."""
from collections import deque
from dataclasses import dataclass, field
import queue
import threading
import time


class Workers:
    """Bounded daemon readers; pending mutations are drained by the frontend.

    Blocking read-only OS probes must not hold a restored terminal at Python's
    executor shutdown hook. Workers never own UI or safety policy.
    """
    def __init__(self, count):
        self.jobs = queue.Queue(maxsize=32)
        self.stopped = threading.Event()
        for index in range(count):
            threading.Thread(target=self.run, name="console-{}".format(index), daemon=True).start()

    def submit(self, operation, *arguments):
        try:
            self.jobs.put_nowait((operation, arguments))
            return True
        except queue.Full:
            return False

    def run(self):
        while not self.stopped.is_set():
            try:
                operation, arguments = self.jobs.get(timeout=.2)
            except queue.Empty:
                continue
            if not self.stopped.is_set():
                operation(*arguments)

    def shutdown(self, wait=False):
        self.stopped.set()


@dataclass
class Snapshot:
    value: object = None
    freshness: str = "loading"
    sampled_at: float = 0
    error: str = ""
    revision: int = 0


@dataclass
class ConsoleState:
    page: str = "overview"
    group: str = ""
    node: str = ""
    query: str = ""
    snapshots: dict = field(default_factory=dict)
    operations: deque = field(default_factory=lambda: deque(maxlen=100))
    logs: deque = field(default_factory=lambda: deque(maxlen=2000))
    progress: tuple = (0, 0)


class Store:
    """One task per key; obsolete results cannot replace a newer snapshot.

    Only safe service projections belong here, never raw config or credentials.
    Worker threads never call a renderer. The renderer drains completion events.
    """
    def __init__(self, workers=4):
        self.state = ConsoleState()
        self.executor = Workers(workers)
        self.lock = threading.RLock()
        self.pending = {}
        self.events = deque(maxlen=100)
        self.closed = False
        self.streams = {}

    def submit(self, key, operation):
        with self.lock:
            if self.closed or key in self.pending:
                return False
            snap = self.state.snapshots.setdefault(key, Snapshot())
            snap.revision += 1
            revision = snap.revision
            self.pending[key] = revision
            if self.executor.submit(self._run, key, revision, operation):
                return True
            self.pending.pop(key, None)
            snap.error = "console-busy"
            snap.freshness = "stale" if snap.value is not None else "error"
            self.events.append(key)
            return False

    def _run(self, key, revision, operation):
        try:
            value, error = operation(), ""
        except Exception as exc:
            value, error = None, getattr(exc, "code", "operation-unverified")
        with self.lock:
            if self.closed or self.pending.get(key) != revision:
                return
            self.pending.pop(key, None)
            snap = self.state.snapshots[key]
            if error:
                snap.freshness = "unsupported" if error == "controller-capability-unsupported" else "stale" if snap.value is not None else "error"
                snap.error = error
            else:
                snap.value, snap.error = value, ""
                snap.sampled_at, snap.freshness = time.time(), "fresh"
            self.events.append(key)

    def invalidate(self, key):
        with self.lock:
            self.pending.pop(key, None)
            snap = self.state.snapshots.setdefault(key, Snapshot())
            snap.revision += 1
            snap.freshness = "stale" if snap.value is not None else "loading"

    def drain(self):
        with self.lock:
            result = list(self.events)
            self.events.clear()
            return result

    def progress(self, completed, total):
        with self.lock:
            self.state.progress = (completed, total)
            self.events.append("progress")

    def stream(self, key, producer):
        """A single cancellable reader per stream; no renderer in workers."""
        with self.lock:
            if self.closed or key in self.streams:
                return False
            stop = threading.Event()
            self.streams[key] = stop
        def emit(value=None, error=""):
            with self.lock:
                if self.closed or stop.is_set():
                    return
                snap = self.state.snapshots.setdefault(key, Snapshot())
                if error:
                    snap.error = error
                    snap.freshness = "unsupported" if error == "controller-capability-unsupported" else "stale" if snap.value is not None else "error"
                else:
                    snap.value, snap.error = value, ""
                    snap.sampled_at, snap.freshness = time.time(), "fresh"
                    if key == "logs" and value is not None:
                        self.state.logs.append(value)
                self.events.append(key)
        def run():
            try:
                producer(emit, stop)
            except Exception as error:
                emit(error=getattr(error, "code", "stream-unverified"))
            finally:
                with self.lock:
                    self.streams.pop(key, None)
        threading.Thread(target=run, name="console-" + key, daemon=True).start()
        return True

    def stop_stream(self, key):
        with self.lock:
            if key in self.streams:
                self.streams[key].set()

    def close(self):
        with self.lock:
            self.closed = True
            for stop in self.streams.values():
                stop.set()
        self.executor.shutdown(wait=False)
