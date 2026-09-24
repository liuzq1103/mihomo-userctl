import gzip
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import offline_install as offline


@unittest.skipUnless(sys.platform == "linux", "Linux filesystem required")
class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "public"
        self.bundle.mkdir()
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)

    def package(self):
        archive = self.bundle / "mihomo.gz"
        archive.write_bytes(gzip.compress(b"fake local executable\n"))
        return {"name": "mihomo", "version": "1.0.0", "arch": "x86_64",
                "file": archive.name, "archive": "gzip",
                "sha256": offline.digest(archive), "commands": {"mihomo": "mihomo"}}

    def tar(self, entries):
        archive = self.bundle / "node.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            for name, data, link in entries:
                member = tarfile.TarInfo(name)
                member.mode = 0o755
                if link is not None:
                    member.type = tarfile.SYMTYPE
                    member.linkname = link
                    tf.addfile(member)
                else:
                    member.size = len(data)
                    tf.addfile(member, io.BytesIO(data))
        return archive

    def test_install_without_network_or_child_processes(self):
        p = self.package()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
                patch("subprocess.Popen", side_effect=AssertionError("no child processes")):
            receipt = offline.install(self.bundle, [p], self.home)
        link = self.home / ".local/bin/mihomo"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.read_bytes(), b"fake local executable\n")
        self.assertEqual(json.loads(receipt.read_text())["packages"][0]["sha256"], p["sha256"])
        self.assertEqual(sorted(x.name for x in self.bundle.iterdir()), [p["file"]])

    def test_digest_failure_cleans_stage(self):
        p = self.package()
        p["sha256"] = "0" * 64
        with self.assertRaises(offline.OfflineError):
            offline.install(self.bundle, [p], self.home)
        self.assertFalse((self.home / ".local/bin/mihomo").exists())
        self.assertEqual(list((self.home / ".local/share/mihomo-userctl-offline").iterdir()), [])

    def test_dangling_command_preserved(self):
        p = self.package()
        bin_dir = self.home / ".local/bin"
        bin_dir.mkdir(parents=True)
        link = bin_dir / "mihomo"
        link.symlink_to("/nonexistent/example")
        with self.assertRaisesRegex(offline.OfflineError, "existing command"):
            offline.install(self.bundle, [p], self.home)
        self.assertEqual(os.readlink(link), "/nonexistent/example")

    def test_repeated_install_preserves_first(self):
        p = self.package()
        first = offline.install(self.bundle, [p], self.home)
        with self.assertRaises(offline.OfflineError):
            offline.install(self.bundle, [p], self.home)
        self.assertTrue(first.exists())

    def test_unsafe_tar_members(self):
        for names in [("../escape",), ("/escape",), ("same", "same")]:
            with self.subTest(names=names), tempfile.TemporaryDirectory(dir=self.root) as tmp:
                archive = self.tar([(n, b"x", None) for n in names])
                with self.assertRaises(offline.OfflineError):
                    offline.extract(archive, Path(tmp) / "out", {"archive": "tar", "commands": {}})
        self.assertFalse((self.root / "escape").exists())

    def test_escaping_symlink_rejected(self):
        archive = self.tar([("bad", b"", "../../outside")])
        with self.assertRaises(offline.OfflineError):
            offline.extract(archive, self.root / "out", {"archive": "tar", "commands": {}})

    def test_node_internal_npm_links_supported(self):
        archive = self.tar([("node/bin/node", b"node", None),
                            ("node/lib/npm.js", b"npm", None),
                            ("node/bin/npm", b"", "../lib/npm.js")])
        output = self.root / "out"
        offline.extract(archive, output, {"archive": "tar", "commands":
                                        {"node": "node/bin/node", "npm": "node/bin/npm"}})
        self.assertEqual((output / "node/bin/npm").read_bytes(), b"npm")

    def test_gzip_expansion_limit(self):
        p = self.package()
        with patch.object(offline, "MAX_BYTES", 3), self.assertRaises(offline.OfflineError):
            offline.extract(self.bundle / p["file"], self.root / "out", p)

    def test_unsafe_install_parent(self):
        (self.home / ".local").symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaises(offline.OfflineError):
            offline.install(self.bundle, [self.package()], self.home)

    def test_later_missing_package_prevents_all_publication(self):
        p = self.package()
        q = dict(p, name="codex", file="missing.tar.gz")
        with self.assertRaises(offline.OfflineError):
            offline.install(self.bundle, [p, q], self.home)
        self.assertFalse((self.home / ".local/bin/mihomo").exists())

    def test_architecture_selection(self):
        path = self.root / "manifest.json"
        p = self.package()
        path.write_text(json.dumps({"format": 1, "packages": [p]}))
        self.assertEqual(offline.load_packages(path, ["mihomo"], "amd64"), [p])
        with self.assertRaises(offline.OfflineError):
            offline.load_packages(path, ["mihomo"], "aarch64")

    def test_partial_link_publication_rolls_back(self):
        p = self.package()
        archive = self.tar([(name, b"test", None) for name in ("node", "npm", "npx")])
        q = {"name": "node", "version": "1", "arch": "x86_64", "file": archive.name,
             "archive": "tar", "sha256": offline.digest(archive),
             "commands": {name: name for name in ("node", "npm", "npx")}}
        original = Path.symlink_to

        def fail_second(path, target, **kwargs):
            if path.name == "node":
                raise OSError("simulated publication failure")
            return original(path, target, **kwargs)

        with patch.object(Path, "symlink_to", fail_second), self.assertRaises(OSError):
            offline.install(self.bundle, [p, q], self.home)
        self.assertEqual(list((self.home / ".local/bin").iterdir()), [])
        self.assertEqual(list((self.home / ".local/share/mihomo-userctl-offline").iterdir()), [])

    def test_shared_package_symlink_escape_rejected(self):
        p = self.package()
        external = self.root / "external.gz"
        (self.bundle / p["file"]).rename(external)
        (self.bundle / p["file"]).symlink_to(external)
        with self.assertRaises(offline.OfflineError):
            offline.package_path(self.bundle, p)

    def test_check_is_read_only(self):
        p = self.package()
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"format": 1, "packages": [p]}))
        before = sorted(str(x) for x in self.root.rglob("*"))
        with patch.object(offline.platform, "machine", return_value="x86_64"):
            rc = offline.main(["check", "--bundle-dir", str(self.bundle),
                               "--manifest", str(path), "--packages", "mihomo"])
        self.assertEqual(rc, 0)
        self.assertEqual(before, sorted(str(x) for x in self.root.rglob("*")))

    def test_malformed_manifest_is_rejected(self):
        path = self.root / "manifest.json"
        for value in ([], {"format": 1, "packages": [None]}):
            path.write_text(json.dumps(value))
            with self.assertRaises(offline.OfflineError):
                offline.load_packages(path, ["mihomo"], "x86_64")


if __name__ == "__main__":
    unittest.main()
