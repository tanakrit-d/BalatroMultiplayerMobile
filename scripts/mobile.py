#!/usr/bin/env python3
"""Pinned upstream sources + exact preimage patches; Python standard library only."""

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {"api": "BalatroMultiplayerAPI", "pvp": "BalatroMultiplayerPvP"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT)


def fetch(url):
    headers = {"User-Agent": "BalatroMultiplayerMobile"}
    # Never forward the GitHub token to archive hosts.
    if url.startswith("https://api.github.com/") and os.getenv("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=120
    ) as response:
        return response.read()


def api(path):
    return json.loads(fetch("https://api.github.com/" + path))


def archive_url(source):
    return (
        f"https://codeload.github.com/{source['repository']}/tar.gz/{source['commit']}"
    )


def read_lock():
    lock = json.loads((ROOT / "sources.lock.json").read_text())
    if lock.get("schema") != 1 or set(lock["sources"]) != set(PROJECTS):
        raise ValueError("Unsupported source lock")
    for key, source in lock["sources"].items():
        if source["repository"] != "Balatro-Multiplayer/" + PROJECTS[key]:
            raise ValueError("Unexpected upstream repository")
        if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
            raise ValueError("Expected full commit SHA")
        if not re.fullmatch(r"[0-9a-f]{64}", source["archive_sha256"]):
            raise ValueError("Expected archive SHA-256")
    return lock


def archive(source):
    cache = ROOT / ".cache" / (source["archive_sha256"] + ".tar.gz")
    data = cache.read_bytes() if cache.exists() else fetch(archive_url(source))
    if digest(data) != source["archive_sha256"]:
        raise ValueError("Source archive checksum mismatch: " + source["repository"])
    cache.parent.mkdir(exist_ok=True)
    cache.write_bytes(data)
    return data


def extract(data, target):
    """Reject traversal, links, devices and multiple roots before extracting."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        roots = {m.name.split("/")[0] for m in members}
        if len(roots) != 1:
            raise ValueError("Expected a single archive root")
        for member in members:
            parts = Path(member.name).parts
            if Path(member.name).is_absolute() or ".." in parts or ".git" in parts:
                raise ValueError("Unsafe archive path")
            if not (member.isdir() or member.isfile()):
                raise ValueError("Unsupported archive entry")
            if len(parts) == 1:
                continue
            destination = target.joinpath(*parts[1:])
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                content = tar.extractfile(member)
                if content is None:
                    raise ValueError("Archive file has no readable content")
                with content:
                    destination.write_bytes(content.read())
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)


def apply_patch(tree, patch):
    """Require complete Git blob preimages: no offset/fuzzy/reverse fallback."""
    content = patch.read_bytes()
    blocks = re.split(rb"(?m)^diff --git ", content)[1:]
    if not blocks:
        raise ValueError("Empty patch")
    for block in blocks:
        header = block.split(b"\n", 1)[0].decode()
        match = re.fullmatch(r"a/([^ ]+) b/([^ ]+)", header)
        index = re.search(rb"(?m)^index ([0-9a-f]{40})\.\.([0-9a-f]{40})(?: |$)", block)
        if not match or not index or match[1] != match[2]:
            raise ValueError(
                "Patches must use full indexes and simple, unchanged paths"
            )
        relative = Path(match[1])
        if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
            raise ValueError("Unsafe patch path")
        path = tree / relative
        before = index[1].decode()
        if before == "0" * 40:
            if path.exists():
                raise ValueError("New patch file already exists")
        else:
            raw = path.read_bytes()
            actual = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            if before != actual:
                raise ValueError(f"Patch preimage mismatch: {relative}")
    run("git", "apply", "--check", "--whitespace=nowarn", str(patch), cwd=tree)
    run("git", "apply", "--whitespace=nowarn", str(patch), cwd=tree)


def series(key):
    folder = ROOT / "patches" / key
    names = [
        x.strip()
        for x in (folder / "series").read_text().splitlines()
        if x.strip() and not x.startswith("#")
    ]
    if len(set(names)) != len(names) or any(
        Path(n).name != n or not n.endswith(".patch") for n in names
    ):
        raise ValueError("Invalid patch series")
    return [folder / n for n in names]


def compatible(sources, lock):
    manifests = {}
    for key, name in PROJECTS.items():
        manifest = json.loads(
            (sources / name / (name.removeprefix("Balatro") + ".json")).read_text()
        )
        if manifest["version"] != lock["sources"][key]["version"]:
            raise ValueError("Manifest version differs from source lock")
        manifests[key] = manifest

    def version(v: str) -> tuple[int, ...]:
        return tuple(map(int, v.split(".")))

    for requirement in manifests["pvp"]["dependencies"]:
        if requirement.startswith("MultiplayerAPI"):
            match = re.fullmatch(r"MultiplayerAPI \(>=(\d+\.\d+\.\d+)\)", requirement)
            if not match or version(manifests["api"]["version"]) < version(match[1]):
                raise ValueError(
                    "Unsupported or incompatible API dependency: " + requirement
                )
    return manifests


def prepare():
    lock = read_lock()
    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    destination = work / "sources"
    with tempfile.TemporaryDirectory(dir=work) as temporary:
        staging = Path(temporary)
        patches = {}
        for key, name in PROJECTS.items():
            tree = staging / name
            tree.mkdir()
            extract(archive(lock["sources"][key]), tree)
            # A repository boundary keeps git apply inside the extracted project.
            run("git", "init", "--quiet", str(tree))
            patches[key] = []
            for patch in series(key):
                apply_patch(tree, patch)
                patches[key].append(
                    {
                        "file": str(patch.relative_to(ROOT)),
                        "sha256": digest(patch.read_bytes()),
                    }
                )
            shutil.rmtree(tree / ".git")
        compatible(staging, lock)
        manifest = {"schema": 1, "sources": lock["sources"], "patches": patches}
        (staging / "build-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(staging), str(destination))
    return destination


def validate(sources, runtimes):
    counts = {}
    for runtime in runtimes:
        executable = shutil.which(runtime)
        if not executable:
            raise ValueError("Required Lua runtime not found: " + runtime)
        executable = str(Path(executable).resolve())
        count = 0
        for key, name in PROJECTS.items():
            tree = sources / name
            pattern = "tests/*.lua" if key == "api" else "tests/unit/*_test.lua"
            tests = sorted(tree.glob(pattern))
            if not tests:
                raise ValueError("Upstream tests missing")
            for test in tests:
                result = run(executable, str(test.relative_to(tree)), cwd=tree)
                print(f"{runtime}: {name}/{test.relative_to(tree)} OK", flush=True)
                if b"SKIP" in result.upper():
                    print(result.decode(), flush=True)
                count += 1
        for test in sorted((ROOT / "tests/lua").glob("*_test.lua")):
            result = run(executable, str(test), cwd=sources / PROJECTS["api"])
            print(f"{runtime}: mobile/{test.name} OK", flush=True)
            count += 1
        counts[runtime] = count
    return counts


def bundle(sources, tests):
    manifest = json.loads((sources / "build-manifest.json").read_text())
    try:
        manifest["patch_repository_commit"] = (
            run("git", "rev-parse", "HEAD", cwd=ROOT).decode().strip()
        )
    except subprocess.CalledProcessError:
        manifest["patch_repository_commit"] = None
    manifest["patch_repository_dirty"] = bool(
        run("git", "status", "--porcelain", cwd=ROOT).strip()
    )
    manifest["tooling_sha256"] = {
        str(p.relative_to(ROOT)): digest(p.read_bytes())
        for p in sorted((ROOT / "scripts").glob("*.py"))
    }
    for name in ("pyproject.toml", "uv.lock", ".python-version"):
        path = ROOT / name
        if path.exists():
            manifest["tooling_sha256"][name] = digest(path.read_bytes())
    manifest["source_lock_sha256"] = digest((ROOT / "sources.lock.json").read_bytes())
    manifest["tests_sha256"] = {
        str(p.relative_to(ROOT)): digest(p.read_bytes())
        for p in sorted((ROOT / "tests").rglob("*"))
        if p.is_file() and p.suffix in (".py", ".lua")
    }
    manifest["validation"] = {"test_files_per_runtime": tests, "device_tested": False}
    files = {}
    for key, name in PROJECTS.items():
        for file in sorted((sources / name).rglob("*")):
            if file.is_file():
                files[
                    name.removeprefix("Balatro")
                    + "/"
                    + str(file.relative_to(sources / name))
                ] = file.read_bytes()
    manifest["files_sha256"] = {path: digest(data) for path, data in files.items()}
    files["build-manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    identity = digest(files["build-manifest.json"])[:16]
    target = output / f"mobile-sources-{identity}.zip"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as zipfile_:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zipfile_.writestr(info, data)
    data = stream.getvalue()
    if target.exists() and target.read_bytes() != data:
        raise ValueError("Refusing to overwrite different artifact bytes")
    target.write_bytes(data)
    target.with_suffix(".zip.sha256").write_text(
        digest(data) + "  " + target.name + "\n"
    )
    print(target)


def update():
    lock = read_lock()
    for key, source in lock["sources"].items():
        repository = source["repository"]
        release = api(f"repos/{repository}/releases/latest")
        tag = release["tag_name"]
        if (
            release["draft"]
            or release["prerelease"]
            or not re.fullmatch(r"v?\d+\.\d+\.\d+", tag)
        ):
            raise ValueError("Expected a stable official release")
        obj = api(f"repos/{repository}/git/ref/tags/{tag}")["object"]
        for _ in range(8):
            if obj["type"] == "commit":
                break
            if obj["type"] != "tag":
                raise ValueError("Release tag does not resolve to a commit")
            obj = api(f"repos/{repository}/git/tags/{obj['sha']}")["object"]
        if obj["type"] != "commit":
            raise ValueError("Release tag nesting too deep")
        version = tag.removeprefix("v")
        if tuple(map(int, version.split("."))) < tuple(
            map(int, source["version"].split("."))
        ):
            raise ValueError("Refusing a release downgrade")
        if tag == source["tag"]:
            if obj["sha"] != source["commit"]:
                raise ValueError("Previously pinned release tag moved")
            continue
        candidate = dict(source, tag=tag, commit=obj["sha"], version=version)
        candidate["archive_sha256"] = digest(fetch(archive_url(candidate)))
        lock["sources"][key] = candidate
    # Write the pair only after all lookups succeed. Preparation validates manifests.
    (ROOT / "sources.lock.json").write_text(json.dumps(lock, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "validate", "build", "update"])
    parser.add_argument("--runtimes", nargs="+", default=["lua5.1", "luajit"])
    args = parser.parse_args()
    if args.command == "update":
        update()
        return
    sources = prepare()
    if args.command == "prepare":
        print(sources)
        return
    tests = validate(sources, args.runtimes)
    if args.command == "build":
        bundle(sources, tests)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.output.decode(errors="replace"))
        raise SystemExit(str(error))
