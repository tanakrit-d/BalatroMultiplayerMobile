import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mobile
import release


class ReleaseTests(unittest.TestCase):
    def sources(self):
        return {
            k: {
                "tag": "v1.0.5",
                "version": "1.0.5",
                "commit": "a" * 40,
                "repository": "Balatro-Multiplayer/" + name,
                "archive_sha256": "b" * 64,
            }
            for k, name in mobile.PROJECTS.items()
        }

    def test_tag_and_revision_identity(self):
        sources = self.sources()
        self.assertEqual(release.identity(sources, 1), "v1.0.5")
        self.assertEqual(release.identity(sources, 2), "v1.0.5-mobile.2")
        sources["api"]["tag"] = "v1.0.6"
        self.assertEqual(release.identity(sources, 1), "api-v1.0.6-pvp-v1.0.5")
        for revision in (0, -1, True, "1"):
            with self.assertRaises(ValueError):
                release.identity(sources, revision)

    def fixture(self, root):
        (root / "release.json").write_text('{"schema":1,"mobile_revision":1}')
        files = {
            f"{mod}/{mod}.json": json.dumps({"version": "1.0.5"}).encode()
            for mod in ("MultiplayerAPI", "MultiplayerPvP")
        }
        manifest = {
            "patch_repository_commit": "c" * 40,
            "patch_repository_dirty": False,
            "sources": self.sources(),
            "tooling_sha256": {},
            "tests_sha256": {},
            "validation": {"test_files_per_runtime": {"lua5.1": 53, "luajit": 53}},
            "files_sha256": {k: mobile.digest(v) for k, v in files.items()},
        }
        files["build-manifest.json"] = json.dumps(manifest).encode()
        bundle = root / "bundle.zip"
        bundle.write_bytes(release.zip_bytes(files))
        return bundle

    def command(self, *args, **kwargs):
        return b"c" * 40 if args[1] == "rev-parse" else b""

    def test_separate_assets_manifest_checksums_and_repeatability(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(mobile, "run", side_effect=self.command),
            patch.object(mobile, "read_lock", return_value={"sources": self.sources()}),
        ):
            root = Path(temp)
            with patch.object(release, "ROOT", root):
                bundle = self.fixture(root)
                output = release.stage(bundle)
                original = {p.name: p.read_bytes() for p in output.iterdir()}
                self.assertEqual(release.stage(bundle), output)
                self.assertEqual(
                    original, {p.name: p.read_bytes() for p in output.iterdir()}
                )
                metadata = json.loads((output / "release-manifest.json").read_text())
                for key, project in metadata["projects"].items():
                    asset = output / project["asset"]
                    self.assertEqual(
                        mobile.digest(asset.read_bytes()), project["sha256"]
                    )
                    with zipfile.ZipFile(asset) as archive:
                        self.assertTrue(
                            all(
                                n.startswith(project["root"] + "/")
                                for n in archive.namelist()
                            )
                        )
                        self.assertEqual(
                            json.loads(
                                archive.read(
                                    project["root"] + "/" + project["root"] + ".json"
                                )
                            )["version"],
                            "1.0.5",
                        )
                (output / "SHA256SUMS").write_text("changed")
                with self.assertRaisesRegex(ValueError, "replace"):
                    release.stage(bundle)

    def test_rejects_dirty_or_wrong_commit_bundle(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(release, "ROOT", Path(temp)),
            patch.object(mobile, "run", return_value=b"dirty"),
        ):
            bundle = self.fixture(Path(temp))
            with self.assertRaisesRegex(ValueError, "clean"):
                release.stage(bundle)

    def test_existing_tag_must_match_commit(self):
        with patch.object(
            release,
            "lookup",
            return_value={"object": {"type": "commit", "sha": "a" * 40}},
        ):
            with self.assertRaisesRegex(ValueError, "different source"):
                release.check_tag("v1.0.5", "b" * 40)

    def test_published_missing_asset_is_never_uploaded(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(mobile, "run", side_effect=self.command),
            patch.object(mobile, "read_lock", return_value={"sources": self.sources()}),
        ):
            root = Path(temp)
            with patch.object(release, "ROOT", root):
                output = release.stage(self.fixture(root))
                with (
                    patch.object(release, "check_tag"),
                    patch.object(
                        release, "lookup", return_value={"draft": False, "assets": []}
                    ),
                    patch.object(release, "gh") as command,
                ):
                    with self.assertRaisesRegex(ValueError, "incomplete"):
                        release.publish(output)
                    command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
