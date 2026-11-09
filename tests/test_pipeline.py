import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "mobile", Path(__file__).resolve().parents[1] / "scripts/mobile.py"
)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PipelineTests(unittest.TestCase):
    def test_rejects_traversal_and_symlinks(self):
        for name, kind in [
            ("root/../../escape", tarfile.REGTYPE),
            ("root/link", tarfile.SYMTYPE),
        ]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = "/tmp/escape"
                    archive.addfile(member)
                with self.assertRaises(ValueError):
                    m.extract(stream.getvalue(), Path(temp))

    def test_checksum_failure_does_not_cache(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(m, "ROOT", Path(temp)),
            patch.object(m, "fetch", return_value=b"wrong"),
        ):
            source = {
                "repository": "owner/repo",
                "commit": "a" * 40,
                "archive_sha256": "0" * 64,
            }
            with self.assertRaisesRegex(ValueError, "checksum"):
                m.archive(source)
            self.assertFalse((Path(temp) / ".cache").exists())

    def test_patch_rejects_drift_even_when_context_would_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            old, new = b"one\ntwo\nthree\n", b"one\nTWO\nthree\n"

            def blob(data):
                return hashlib.sha1(
                    b"blob " + str(len(data)).encode() + b"\0" + data
                ).hexdigest()

            patchfile = root / "change.patch"
            patchfile.write_text(
                f"diff --git a/file b/file\nindex {blob(old)}..{blob(new)} 100644\n--- a/file\n+++ b/file\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n"
            )
            (root / "file").write_bytes(b"prefix\n" + old)
            with self.assertRaisesRegex(ValueError, "preimage"):
                m.apply_patch(root, patchfile)
            (root / "file").write_bytes(old)
            m.apply_patch(root, patchfile)
            self.assertEqual((root / "file").read_bytes(), new)
            with self.assertRaises(ValueError):
                m.apply_patch(root, patchfile)

    def test_rejects_incompatible_pair(self):
        lock = {"sources": {"api": {"version": "1.0.5"}, "pvp": {"version": "1.0.5"}}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for key, name in m.PROJECTS.items():
                folder = root / name
                folder.mkdir()
                (folder / (name.removeprefix("Balatro") + ".json")).write_text(
                    json.dumps(
                        {
                            "version": "1.0.5",
                            "dependencies": ["MultiplayerAPI (>=1.0.6)"]
                            if key == "pvp"
                            else [],
                        }
                    )
                )
            with self.assertRaisesRegex(ValueError, "incompatible"):
                m.compatible(root, lock)

    def test_update_rejects_moved_tag_without_writing(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, "ROOT", Path(temp)):
            lock = {
                "schema": 1,
                "sources": {
                    key: {
                        "repository": "Balatro-Multiplayer/" + name,
                        "tag": "v1.0.5",
                        "version": "1.0.5",
                        "commit": "a" * 40,
                        "archive_sha256": "b" * 64,
                    }
                    for key, name in m.PROJECTS.items()
                },
            }
            path = Path(temp) / "sources.lock.json"
            path.write_text(json.dumps(lock))
            original = path.read_bytes()
            with patch.object(
                m,
                "api",
                side_effect=[
                    {"tag_name": "v1.0.5", "draft": False, "prerelease": False},
                    {"object": {"type": "commit", "sha": "c" * 40}},
                ],
            ):
                with self.assertRaisesRegex(ValueError, "tag moved"):
                    m.update()
            self.assertEqual(path.read_bytes(), original)

    def test_update_peels_annotated_tag_and_preserves_pair_on_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, "ROOT", Path(temp)):
            lock = {
                "schema": 1,
                "sources": {
                    key: {
                        "repository": "Balatro-Multiplayer/" + name,
                        "tag": "v1.0.5",
                        "version": "1.0.5",
                        "commit": "a" * 40,
                        "archive_sha256": "b" * 64,
                    }
                    for key, name in m.PROJECTS.items()
                },
            }
            path = Path(temp) / "sources.lock.json"
            path.write_text(json.dumps(lock))
            original = path.read_bytes()
            responses = [
                {"tag_name": "v1.0.6", "draft": False, "prerelease": False},
                {"object": {"type": "tag", "sha": "c" * 40}},
                {"object": {"type": "commit", "sha": "d" * 40}},
                OSError("second upstream unavailable"),
            ]
            with (
                patch.object(m, "api", side_effect=responses) as api_mock,
                patch.object(m, "fetch", return_value=b"archive"),
            ):
                with self.assertRaises(OSError):
                    m.update()
                self.assertIn("/git/tags/", api_mock.call_args_list[2].args[0])
            self.assertEqual(path.read_bytes(), original)

    def test_bundles_are_byte_reproducible(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(m, "ROOT", Path(temp)),
            patch.object(m, "run", return_value=b""),
        ):
            root = Path(temp)
            sources = root / "sources"
            for name in m.PROJECTS.values():
                (sources / name).mkdir(parents=True)
                (sources / name / "core.lua").write_text("return {}\n")
            (sources / "build-manifest.json").write_text("{}")
            (root / "sources.lock.json").write_text("{}")
            m.bundle(sources, {"lua5.1": 2, "luajit": 2})
            output = next((root / "dist").glob("*.zip"))
            first = output.read_bytes()
            m.bundle(sources, {"lua5.1": 2, "luajit": 2})
            self.assertEqual(first, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
