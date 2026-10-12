"""Maintainer-pinned core digests (the only real trust anchor).

Provenance: digests are recorded from the official GitHub releases API
asset ``digest`` field at review time.  This is a maintainer pin, NOT an
upstream signature: official releases ship no signatures, checksums or
attestations (verified design-reference 6.1/6.2).  Never claim
"signature verified" or "reproducible build".
"""

import json
import re
from pathlib import Path
from .errors import SupplyChainError
from .trust import require_trusted_code_file

DIGESTS_FILE = Path(__file__).parent / "mihomo-digests.json"


def load_pins():
    require_trusted_code_file(DIGESTS_FILE)
    if DIGESTS_FILE.stat().st_size > 1024 * 1024:
        raise SupplyChainError("digest-table-invalid")
    try:
        data = json.loads(DIGESTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SupplyChainError("digest-table-invalid") from None
    if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("pins"), list):
        raise SupplyChainError("digest-table-invalid")
    pins = {}
    for pin in data["pins"]:
        if (not isinstance(pin, dict) or not all(isinstance(pin.get(key), str) and pin[key]
                for key in ("version", "asset", "sha256", "source", "reviewed_by", "reviewed_at"))
                or not re.fullmatch(r"v\d+\.\d+\.\d+", pin["version"])
                or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
                or not re.fullmatch(r"mihomo-linux-[a-z0-9-]+-" + re.escape(pin["version"]) + r"\.gz", pin["asset"])):
            raise SupplyChainError("digest-table-invalid")
        key = (pin["version"], pin["asset"])
        if key in pins:
            raise SupplyChainError("digest-table-duplicate")
        pins[key] = pin
    return pins


def lookup(version, asset):
    return load_pins().get((version, asset))
