"""Core supply-chain boundaries: bounded parsing and transactional activation recovery."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from mihomoctl import coreinstall, digests
from mihomoctl.errors import SupplyChainError


def elf(machine=62, elf_class=2):
    body = bytearray(64)
    body[:6] = b"\x7fELF" + bytes((elf_class, 1))
    struct.pack_into("<H", body, 18, machine)
    return bytes(body)


class SupplyChainTests(unittest.TestCase):
    def test_architecture_asset_names_and_elf_class_match(self):
        for machine, variant, number, elf_class in (("x86_64", "amd64-compatible", 62, 2),
                                                  ("aarch64", "arm64", 183, 2),
                                                  ("armv7l", "armv7", 40, 1)):
            with self.subTest(machine=machine), patch.object(coreinstall.platform, "machine", return_value=machine):
                self.assertEqual(coreinstall._asset_name("v1.19.32"),
                                 "mihomo-linux-" + variant + "-v1.19.32.gz")
                self.assertEqual(coreinstall._verify_gzip(gzip.compress(elf(number, elf_class)), "v1.19.32"),
                                 elf(number, elf_class))

    def test_gzip_expansion_limit_and_wrong_architecture_refused(self):
        with patch.object(coreinstall, "MAX_CORE_BYTES", 128):
            with self.assertRaisesRegex(SupplyChainError, "core-too-large"):
                coreinstall._verify_gzip(gzip.compress(b"x" * 10000), "v1.0.0")
        with patch.object(coreinstall.platform, "machine", return_value="x86_64"):
            with self.assertRaisesRegex(SupplyChainError, "core-arch-mismatch"):
                coreinstall._verify_gzip(gzip.compress(elf(183)), "v1.0.0")

    def test_unknown_digest_refused_before_download_and_pin_is_binding(self):
        scope = Mock()
        with patch.object(coreinstall.platform, "machine", return_value="x86_64"), \
                patch.object(digests, "lookup", return_value=None), patch.object(coreinstall, "_download") as download:
            with self.assertRaisesRegex(SupplyChainError, "digest-required"):
                coreinstall.install(scope, "v9.9.9")
            download.assert_not_called()
        with patch.object(coreinstall.platform, "machine", return_value="x86_64"), \
                patch.object(digests, "lookup", return_value={"sha256": "a" * 64}), \
                patch.object(coreinstall, "_download") as download:
            with self.assertRaisesRegex(SupplyChainError, "digest-mismatch"):
                coreinstall.install(scope, "v1.19.32", sha256="b" * 64)
            download.assert_not_called()

    def test_download_hash_mismatch_never_executes_candidate(self):
        with patch.object(coreinstall.platform, "machine", return_value="x86_64"), \
                patch.object(digests, "lookup", return_value=None), \
                patch.object(coreinstall, "_download", return_value=b"untrusted"), \
                patch.object(coreinstall, "_run_version") as execute:
            with self.assertRaisesRegex(SupplyChainError, "digest-mismatch"):
                coreinstall.install(Mock(), "v9.9.9", sha256="a" * 64)
            execute.assert_not_called()

    def test_download_rejects_nonofficial_url_and_short_content(self):
        with patch.object(coreinstall.urllib.request, "build_opener") as opener:
            with self.assertRaises(SupplyChainError):
                coreinstall._download("https://example.com/core.gz")
            opener.assert_not_called()
            response = io.BytesIO(b"xx")
            response.status = 200
            response.headers = {"Content-Length": "3"}
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(SupplyChainError, "asset-size-mismatch"):
                coreinstall._download(coreinstall.RELEASE_BASE + "/v9.9.9/core.gz")

    def test_redirect_cannot_send_request_to_other_host_or_plain_http(self):
        for url in ("http://github.com/core.gz", "https://example.com/core.gz",
                    "https://user@github.com/core.gz", "https://github.com:8443/core.gz"):
            with self.subTest(url=url), self.assertRaises(SupplyChainError):
                coreinstall._validate_download_url(url)

    def test_version_match_requires_complete_version_token(self):
        self.assertTrue(coreinstall._version_matches("Mihomo Meta v1.19.32 linux amd64", "v1.19.32"))
        self.assertFalse(coreinstall._version_matches("Mihomo v1.19.320", "v1.19.32"))

    def test_pinned_table_has_reviewed_digest_and_rejects_duplicate_entry(self):
        pin = digests.lookup("v1.19.32", "mihomo-linux-amd64-compatible-v1.19.32.gz")
        self.assertEqual(pin["sha256"], "ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pins.json"
            path.write_text(json.dumps({"format": 1, "pins": [pin, pin]}), encoding="utf-8")
            path.chmod(0o600)
            with patch.object(digests, "DIGESTS_FILE", path), self.assertRaisesRegex(SupplyChainError, "digest-table-duplicate"):
                digests.load_pins()


if __name__ == "__main__":
    unittest.main()
