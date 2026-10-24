"""Pinned upgrade provenance and decimal-byte budgets for the complete bundle."""
import hashlib
import os
from pathlib import Path
import threading

BASELINE = {
    'version': '1.4.0',
    'commit': 'c4f35010e709cf1c3b3c48696f65034ee4e50a6e',
    'name': 'mihomoctl-1.4.0-portable-linux-x86_64.tar.gz',
    'sha256': '29ab4e86ef03f3c3fc8bb1ed5475973050a2ce22a480ada25e796cf5cf1f6bd6',
    'bundle_bytes': 91743996,
    'expanded_bytes': 225181008,
    'installed_bytes': 287836142,
}
MAX_DOWNLOAD = 65_000_000
MAX_EXPANDED = 160_000_000
MAX_INSTALLED = 225_000_000


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def usage(root):
    """Count files once by inode; never follow directory or file symlinks."""
    logical = allocated = 0
    seen = set()
    for directory, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(directory) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                info = path.stat()
            except FileNotFoundError:  # transient runtime state during sampling
                continue
            key = (info.st_dev, info.st_ino)
            if key not in seen:
                seen.add(key)
                logical += info.st_size
                allocated += getattr(info, 'st_blocks', 0) * 512
    return {'logical_bytes': logical, 'allocated_bytes': allocated}


class PeakUsage:
    """Observed per-home high-water marks, sampled at 50ms (not an exact bound)."""
    def __init__(self, root):
        self.root = root
        self.stop = threading.Event()
        self.peak = {'logical_bytes': 0, 'allocated_bytes': 0}
        self.thread = threading.Thread(target=self._run, daemon=True)

    def sample(self):
        for key, value in usage(self.root).items():
            self.peak[key] = max(self.peak[key], value)

    def _run(self):
        while not self.stop.wait(.05):
            self.sample()

    def __enter__(self):
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *ignored):
        self.stop.set()
        self.thread.join()
        self.sample()
