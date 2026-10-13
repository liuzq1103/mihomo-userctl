import io
import json
from pathlib import Path
import tempfile
import sys
import os
import unittest
from unittest.mock import patch
import zipfile
import bootstrap as b


class BootstrapTests(unittest.TestCase):
    def test_latest_resolves_to_immutable_commit(self):
        release = {"tag_name": "v0.7.0", "draft": False, "prerelease": False, "published_at": "date", "id": 1}
        with patch.object(b, "get", side_effect=[json.dumps(release), json.dumps({"object": {"type": "commit", "sha": "a"*40}})]):
            result = b.resolve()
        self.assertTrue(result["archive_url"].endswith("a"*40))
        self.assertIsNone(result["official_digest"])

    def test_invalid_tag_does_not_download(self):
        with patch.object(b, "get") as get:
            with self.assertRaises(b.BootstrapError): b.resolve("main")
            get.assert_not_called()

    def test_prerelease_rejected(self):
        with patch.object(b, "get", return_value=json.dumps({"tag_name": "v0.7.0", "prerelease": True})):
            with self.assertRaises(b.BootstrapError): b.resolve()

    def test_unsafe_archive_rejected_before_writing(self):
        for bad in ("../outside", "/absolute", "repo/../escape", "second/file"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); archive = root / "archive.zip"
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("repo/install.sh", "fixture")
                    z.writestr(bad, "bad")
                with self.assertRaises(b.BootstrapError): b.extract(archive, root / "out")
                self.assertFalse((root / "out").exists())

    def test_valid_archive_extracts_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); archive = root / "archive.zip"
            with zipfile.ZipFile(archive, "w") as z: z.writestr("repo/install.sh", "fixture")
            checkout = b.extract(archive, root / "out")
            self.assertEqual((checkout / "install.sh").read_text(), "fixture")

    @unittest.skipUnless(sys.platform == "linux", "Bash installation entry")
    def test_main_invokes_release_installer_with_port_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "arguments"
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as z:
                z.writestr("repo/release-manifest.json", json.dumps({"version": "0.7.0", "update_protocol": 1}))
                z.writestr("repo/install.sh", '#!/bin/bash\nif [[ $1 == --suggest-port ]]; then echo 25001; exit; fi\nprintf "%s\\n" "$@" > "$BOOTSTRAP_TEST_OUTPUT"\n')
            source = {"tag": "v0.7.0", "commit": "a"*40, "archive_url": "https://codeload.github.com/fixture"}
            with patch.object(b, "resolve", return_value=source), patch.object(b, "get", return_value=stream.getvalue()), patch.object(sys, "argv", ["bootstrap", "--dry-run"]), patch.dict(os.environ, {"XDG_DATA_HOME": temp, "BOOTSTRAP_TEST_OUTPUT": str(output)}):
                self.assertEqual(b.main(), 0)
            values = output.read_text().splitlines()
            self.assertIn("--source-record", values)
            self.assertEqual(values[-3:], ["--port", "25001", "--dry-run"])
            self.assertEqual(len(source["archive_sha256"]), 64)
