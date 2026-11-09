#!/usr/bin/env python3
"""Create and publish immutable patched mod assets for the iOS builder."""

import argparse
import io
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

import mobile

ROOT = mobile.ROOT
REPOSITORY = "tanakrit-d/BalatroMultiplayerMobile"


def identity(sources, revision):
    if type(revision) is not int or revision < 1:
        raise ValueError("mobile_revision must be a positive integer")
    tags = [sources[key]["tag"] for key in ("api", "pvp")]
    if any(not re.fullmatch(r"v?\d+\.\d+\.\d+", tag) for tag in tags):
        raise ValueError("Unsupported upstream tag")
    base = tags[0] if tags[0] == tags[1] else f"api-{tags[0]}-pvp-{tags[1]}"
    return base if revision == 1 else f"{base}-mobile.{revision}"


def zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    return stream.getvalue()


def stage(bundle):
    config = json.loads((ROOT / "release.json").read_text())
    if config.get("schema") != 1:
        raise ValueError("Unsupported release configuration")
    head = mobile.run("git", "rev-parse", "HEAD", cwd=ROOT).decode().strip()
    if mobile.run("git", "status", "--porcelain", cwd=ROOT).strip():
        raise ValueError("Release requires a clean committed checkout")
    with zipfile.ZipFile(bundle) as archive:
        provenance = json.loads(archive.read("build-manifest.json"))
        if (
            provenance["patch_repository_dirty"]
            or provenance["patch_repository_commit"] != head
        ):
            raise ValueError("Bundle must come from this clean commit")
        if provenance["sources"] != mobile.read_lock()["sources"]:
            raise ValueError("Bundle source pins differ from checkout")
        for key, folder in [("tooling_sha256", "scripts"), ("tests_sha256", "tests")]:
            for path, checksum in provenance[key].items():
                if mobile.digest((ROOT / path).read_bytes()) != checksum:
                    raise ValueError("Bundle tooling or tests differ from checkout")
        counts = provenance["validation"]["test_files_per_runtime"]
        if any(counts.get(runtime, 0) <= 0 for runtime in ("lua5.1", "luajit")):
            raise ValueError("Both Lua 5.1 and LuaJIT validation are required")
        files = {name: archive.read(name) for name in provenance["files_sha256"]}
        for name, checksum in provenance["files_sha256"].items():
            if mobile.digest(files[name]) != checksum:
                raise ValueError("Bundle file checksum mismatch: " + name)
    revision = config["mobile_revision"]
    tag = identity(provenance["sources"], revision)
    result = {
        "schema": 1,
        "repository": REPOSITORY,
        "tag": tag,
        "mobile_revision": revision,
        "patch_repository_commit": head,
        "device_tested": False,
        "projects": {},
    }
    assets = {}
    for key, name in mobile.PROJECTS.items():
        mod = name.removeprefix("Balatro")
        source = provenance["sources"][key]
        manifest = json.loads(files[f"{mod}/{mod}.json"])
        if manifest["version"] != source["version"]:
            raise ValueError("Patched manifest changed the upstream version")
        filename = f"{mod}-{source['tag']}-mobile.{revision}.zip"
        selected = {
            path: data for path, data in files.items() if path.startswith(mod + "/")
        }
        selected[f"{mod}/mobile-build-manifest.json"] = (
            json.dumps(provenance, indent=2, sort_keys=True) + "\n"
        ).encode()
        assets[filename] = zip_bytes(selected)
        result["projects"][key] = dict(
            source,
            asset=filename,
            sha256=mobile.digest(assets[filename]),
            size=len(assets[filename]),
            root=mod,
            download_url=f"https://github.com/{REPOSITORY}/releases/download/{tag}/{filename}",
        )
    assets["release-manifest.json"] = (
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    ).encode()
    assets["SHA256SUMS"] = "".join(
        f"{mobile.digest(data)}  {name}\n" for name, data in sorted(assets.items())
    ).encode()
    destination = ROOT / "dist/releases" / tag
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in assets.items():
        path = destination / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Refusing to replace staged release bytes: " + name)
        path.write_bytes(data)
    return destination


def gh(*args):
    return mobile.run("gh", *args, cwd=ROOT)


def lookup(path):
    try:
        return json.loads(gh("api", path))
    except subprocess.CalledProcessError as error:
        if b"HTTP 404" in error.output:
            return None
        raise


def lookup_release(tag):
    release = lookup(f"repos/{REPOSITORY}/releases/tags/{tag}")
    if release is not None:
        return release
    # GitHub's by-tag endpoint does not return unpublished drafts. The
    # authenticated releases listing includes them; inspect every page.
    pages = json.loads(
        gh("api", "--paginate", "--slurp", f"repos/{REPOSITORY}/releases?per_page=100")
    )
    matches = [item for page in pages for item in page if item["tag_name"] == tag]
    if len(matches) > 1:
        raise ValueError("Multiple releases have this tag; resolve duplicate drafts")
    return matches[0] if matches else None


def check_tag(tag, commit):
    ref = lookup(f"repos/{REPOSITORY}/git/ref/tags/{tag}")
    if ref is None:
        return
    obj = ref["object"]
    for _ in range(8):
        if obj["type"] == "commit":
            break
        if obj["type"] != "tag":
            raise ValueError("Unsupported existing tag target")
        obj = lookup(f"repos/{REPOSITORY}/git/tags/{obj['sha']}")["object"]
    if obj["type"] != "commit" or obj["sha"] != commit:
        raise ValueError(
            "Existing release tag points to different source; increment mobile_revision"
        )


def publish(directory):
    manifest = json.loads((directory / "release-manifest.json").read_text())
    tag, commit = manifest["tag"], manifest["patch_repository_commit"]
    # Reconstruct from the current checkout before trusting any release directory.
    if (
        mobile.run("git", "status", "--porcelain", cwd=ROOT).strip()
        or mobile.run("git", "rev-parse", "HEAD", cwd=ROOT).decode().strip() != commit
    ):
        raise ValueError("Publishing requires the clean release commit")
    if manifest["repository"] != REPOSITORY or tag != identity(
        mobile.read_lock()["sources"],
        json.loads((ROOT / "release.json").read_text())["mobile_revision"],
    ):
        raise ValueError("Release identity does not match checkout")
    expected = {item["asset"] for item in manifest["projects"].values()} | {
        "release-manifest.json",
        "SHA256SUMS",
    }
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError("Unexpected or missing staged assets")
    checksums = dict(
        (line.split("  ", 1)[1], line.split("  ", 1)[0])
        for line in (directory / "SHA256SUMS").read_text().splitlines()
    )
    if set(checksums) != expected - {"SHA256SUMS"}:
        raise ValueError("Invalid checksum inventory")
    for name, checksum in checksums.items():
        if mobile.digest((directory / name).read_bytes()) != checksum:
            raise ValueError("Staged checksum mismatch")
    check_tag(tag, commit)
    remote = lookup_release(tag)
    if remote is None:
        with tempfile.TemporaryDirectory() as temp:
            notes = Path(temp) / "notes.md"
            notes.write_text(
                f"Patched mobile sources: API {manifest['projects']['api']['tag']}, PvP {manifest['projects']['pvp']['tag']}. Mobile revision {manifest['mobile_revision']}.\n\nUpstream mod versions are unchanged. Consume the uploaded ZIP assets using release-manifest.json and SHA256SUMS; GitHub automatic source archives contain the patch repository only.\n\nPaired Lua validation passed. Device gameplay is not validated by this source release.\n"
            )
            gh(
                "release",
                "create",
                tag,
                "--repo",
                REPOSITORY,
                "--target",
                commit,
                "--draft",
                "--title",
                tag,
                "--notes-file",
                str(notes),
            )
        remote = lookup_release(tag)
    if remote is None:
        raise ValueError(
            "Created draft could not be found; inspect GitHub before retrying"
        )
    remote_names = {asset["name"] for asset in remote["assets"]}
    if remote_names - expected:
        raise ValueError("Existing release has unexpected assets")
    with tempfile.TemporaryDirectory() as temp:
        for name in sorted(expected):
            if name in remote_names:
                gh(
                    "release",
                    "download",
                    tag,
                    "--repo",
                    REPOSITORY,
                    "--pattern",
                    name,
                    "--dir",
                    temp,
                )
                if (Path(temp) / name).read_bytes() != (directory / name).read_bytes():
                    raise ValueError(
                        "Existing release bytes differ; increment mobile_revision"
                    )
            elif remote["draft"]:
                gh(
                    "release",
                    "upload",
                    tag,
                    str(directory / name),
                    "--repo",
                    REPOSITORY,
                )
                gh(
                    "release",
                    "download",
                    tag,
                    "--repo",
                    REPOSITORY,
                    "--pattern",
                    name,
                    "--dir",
                    temp,
                )
                if (Path(temp) / name).read_bytes() != (directory / name).read_bytes():
                    raise ValueError("Uploaded asset verification failed")
            else:
                raise ValueError("Published release is incomplete; refusing mutation")
    if remote["draft"]:
        gh(
            "release",
            "edit",
            tag,
            "--repo",
            REPOSITORY,
            "--target",
            commit,
            "--draft=false",
        )
    check_tag(tag, commit)
    print(f"https://github.com/{REPOSITORY}/releases/tag/{tag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["stage", "publish"])
    parser.add_argument(
        "path", type=Path, help="Source bundle for stage; staged directory for publish"
    )
    args = parser.parse_args()
    if args.command == "stage":
        print(stage(args.path))
    else:
        publish(args.path)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.output.decode(errors="replace"))
        raise SystemExit(str(error))
