#!/usr/bin/env python3
"""One-time migration audit against preserved mobile commits and builder adapter."""

import argparse
from pathlib import Path

import mobile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "repositories",
    type=Path,
    help="Directory containing the two old forks and iOS builder",
)
args = parser.parse_args()
sources = mobile.prepare()
heads = {
    "api": "297389bba79b135567c6e0ebd9b984affb108a56",
    "pvp": "88976150d069db4acfaf5d3d278e763c76338c59",
}
# Evaluate the immutable historical builder implementation, not its working tree.
code = mobile.run(
    "git",
    "show",
    "088e9e56416d7690b226047fc617fab7616000b0:scripts/ios_openssl.py",
    cwd=args.repositories / "balatro-ios-mod-builder",
)
namespace = {}
exec(compile(code, "<historical ios_openssl.py>", "exec"), namespace)
for key, name in mobile.PROJECTS.items():
    repo = args.repositories / name
    paths = (
        mobile.run("git", "ls-tree", "-r", "--name-only", heads[key], cwd=repo)
        .decode()
        .splitlines()
    )
    compared = 0
    for path in paths:
        if path.startswith(".github/") or path in ("MOBILE_PATCHES.md", "README.md"):
            continue
        expected = mobile.run("git", "show", heads[key] + ":" + path, cwd=repo)
        if key == "api" and path == "networking/openssl_ffi.lua":
            mods = {"MultiplayerAPI/" + path: expected}
            namespace["patch_mods"](mods)
            expected = mods["MultiplayerAPI/" + path]
        actual = (sources / name / path).read_bytes()
        if actual != expected:
            raise SystemExit("Baseline mismatch: " + name + "/" + path)
        compared += 1
    print(
        f"{name}: {compared} baseline files match (API loader includes historical builder adapter)"
    )
