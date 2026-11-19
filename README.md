# Balatro Multiplayer Mobile

Paired mobile patches for official Multiplayer API and PvP releases pinned in [sources.lock.json](sources.lock.json). Patches support Steam-free Community login, the iOS OpenSSL loader and Lua test compatibility. Upstream mod versions are preserved.

This repository produces **patched source bundles, not IPAs**. It does not write to upstream repositories.

## Build

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/), Git, Lua 5.1 (`lua5.1`) and LuaJIT (`luajit`). uv manages Python 3.15 and the locked development tools.

```sh
uv sync --locked
uv run --locked ruff check
uv run --locked ruff format --check
uv run --locked ty check
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/mobile.py build
```

The build verifies source hashes, applies patches, checks API/PvP compatibility and runs Lua tests under both runtimes. It writes `dist/mobile-sources-<manifest-hash>.zip`, a provenance manifest inside the ZIP and a companion `.sha256` file.

Use `uv run --locked python scripts/mobile.py prepare` to inspect patched sources in `work/sources/` without testing or bundling. Edit patches, not generated sources.

## Update sources

The daily **Check official releases** workflow proposes source updates as PRs and validates each candidate. Failed candidates still get a review PR, but no source artifact. Enable Actions and allow GitHub Actions to create pull requests.

To update locally:

```sh
uv run --locked python scripts/mobile.py update
uv run --locked python scripts/mobile.py build
```

Review changes to `sources.lock.json` and fix any patch conflicts. Reset `mobile_revision` in [release.json](release.json) to `1` for a new upstream pair; the daily workflow does this automatically.

## Publish

Run **Publish patched mod release** on `main` after reviewing and merging changes. It validates both mods and publishes to `tanakrit-d/BalatroMultiplayerMobile`, keeping the release in draft until uploaded assets pass download verification.

Each release contains:

- `MultiplayerAPI-<upstream-tag>-mobile.<revision>.zip`
- `MultiplayerPvP-<upstream-tag>-mobile.<revision>.zip`
- `release-manifest.json`
- `SHA256SUMS`

Release tags use the shared upstream tag, or `api-<api-tag>-pvp-<pvp-tag>` when they differ. Increment `mobile_revision` for patch-only releases of the same pair; revisions above 1 append `-mobile.<revision>` to the release tag. Published tags and assets are immutable; identical retries verify existing bytes.

The iOS builder should pin the release tag, read `release-manifest.json` and verify each mod ZIP's SHA-256. Use the uploaded mod ZIPs, not GitHub's automatic source archives, which contain this patch repository. Source tests do not establish device gameplay compatibility.

## Maintain patches

Keep focused patches in `patches/api/series` or `patches/pvp/series`. Generate them with `git diff --binary --full-index` against the pinned source plus preceding patches. Use deletion/addition for renames. Patch preimages must match exactly.

See [PATCHES.md](PATCHES.md) for patch ownership and limitations, and [MIGRATION.md](MIGRATION.md) for migration details.

## Licensing

Scripts and patches are [GPL-3.0](LICENSE). Source bundles retain upstream licenses. No Balatro game assets or credentials are included.
