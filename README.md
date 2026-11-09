# Balatro Multiplayer Mobile

Maintain mobile patches for official Multiplayer API and PvP releases as one tested pair. No long-lived mobile forks or upstream writes are required.

The initial source pins are official **v1.0.5** for both projects. Patches preserve the existing Steam-free Community login, add the iOS static OpenSSL loader previously injected by the IPA builder, and retain the existing Lua test compatibility fixes. PvP gameplay is unchanged.

## Build patched sources

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/), Git, Lua 5.1 (`lua5.1`) and LuaJIT (`luajit`). uv manages the Python 3.15 environment and locked development tools; the build scripts have no third-party runtime dependencies.

```sh
uv sync --locked
uv run --locked ruff check
uv run --locked ruff format --check
uv run --locked ty check
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/mobile.py build
```

The command verifies source archive SHA-256 hashes, checks every patched file against its complete Git preimage, applies patches in `series` order, validates the PvP API-version requirement, and runs both projects' tests under both Lua runtimes. A failed patch or test stops the build.

`dist/mobile-sources-<manifest-hash>.zip` contains `MultiplayerAPI/`, `MultiplayerPvP/`, and a provenance manifest. A companion `.sha256` verifies the ZIP. The manifest records source commits, patch hashes, tool hashes, repository revision/dirty state, individual output file hashes and test coverage. Identical inputs produce identical ZIP bytes. These are **source bundles, not IPAs**.

For inspection only, `uv run --locked python scripts/mobile.py prepare` reconstructs sources in `work/sources/`. It does not run tests or create a distributable bundle. Generated files live in ignored `work/`, `.cache/`, and `dist/` directories. Do not edit generated sources as your source of truth.

## Python tooling

`pyproject.toml` configures uv, Ruff linting/formatting, and ty type checking for `scripts/` and `tests/`. Generated upstream sources are outside the check scope. `uv.lock` pins Ruff and ty; `.python-version` selects Python 3.15. All workflows use the same locked environment and quality checks before building or publishing.

Use `uv run --locked ruff check --fix` and `uv run --locked ruff format` when editing Python. Update tools deliberately with `uv lock --upgrade`, then run the checks above. Include `pyproject.toml` and `uv.lock` changes together. Build provenance includes the Python/tool configuration hashes.

## Upgrade releases

```sh
uv run --locked python scripts/mobile.py update
uv run --locked python scripts/mobile.py build
```

The updater queries published stable GitHub releases, resolves tags to immutable commits, and updates `sources.lock.json` atomically after both lookups succeed. It rejects downgrades and moved pinned tags. API and PvP version numbers need not match; the dependency declared by PvP must be satisfied. Unsupported API requirement syntax fails closed for review.

The daily workflow proposes an upgrade PR in `tanakrit-d/BalatroMultiplayerMobile`. It tests the proposed pair itself because PRs created with GitHub's built-in token do not trigger another workflow automatically. Failed candidates still get a review PR and a failing workflow; they do not get a source artifact. Existing proposal branches are never force-pushed. Human PR changes run ordinary validation.

To enable automation, publish this repository under that fork namespace with `main` as the default branch, enable Actions, and allow GitHub Actions to create pull requests. The separate **Publish patched mod release** workflow publishes source releases when manually dispatched on `main`. No workflow builds IPAs. No hosted repository has been provisioned by these files.

## Releases for the iOS builder

Run **Publish patched mod release** on `main` after reviewing the paired source update. It runs the pipeline tests, reconstructs and validates both mods, stages separate ZIPs, then publishes a GitHub release in `tanakrit-d/BalatroMultiplayerMobile`. Publication uses a draft until all assets have been uploaded and downloaded again for byte verification.

For the initial upstream pair, the tag is **`v1.0.5`**, with these assets:

- `MultiplayerAPI-v1.0.5-mobile.1.zip`
- `MultiplayerPvP-v1.0.5-mobile.1.zip`
- `release-manifest.json`
- `SHA256SUMS`

Both mod manifests retain version `1.0.5`. If API and PvP have different upstream tags, the paired release tag identifies both, for example `api-v1.0.6-pvp-v1.0.5`. Each project entry in the release manifest always records its exact upstream tag, version and commit.

`release.json` controls the mobile revision. Increment it for another release of the same upstream pair: revision 2 yields `v1.0.5-mobile.2` and `*-mobile.2.zip` assets. Reset it to 1 for a new upstream pair. Never move a published tag or replace its assets. An identical retry checks existing remote bytes and succeeds without replacing them; an interrupted draft may upload only missing assets. A different commit or different bytes under an existing tag stops publication.

The builder should pin the release tag, download `release-manifest.json`, then download each project's `asset`/`download_url` and verify its `sha256`. ZIPs contain one top-level `MultiplayerAPI/` or `MultiplayerPvP/` directory, respectively, including upstream licenses and `mobile-build-manifest.json`. Preserve the separate upstream versions and mobile revision in the builder lock. **Do not consume GitHub's automatic Source code archives:** those contain this patch repository, not the patched mods. These source releases do not establish device gameplay validation.

Local staging from a clean committed checkout:

```sh
uv run --locked python scripts/mobile.py build
uv run --locked python scripts/release.py stage dist/mobile-sources-<manifest-hash>.zip
# Publish only when the repository and commit are available on GitHub:
uv run --locked python scripts/release.py publish dist/releases/v1.0.5
```

Publishing requires authenticated `gh` with write access to this repository. It cannot target the original upstream projects.

## Maintain patches

Keep one focused change per patch and list it in `patches/api/series` or `patches/pvp/series`. Use `git diff --binary --full-index` against the pinned source plus preceding patches. Paths must remain unchanged; renames should be represented as deletion/addition. Preimage drift is intentional review work: there is no fuzzy application, reverse application, or silently skipped patch.

See [MIGRATION.md](MIGRATION.md) for baseline evidence and the builder cutover, and [PATCHES.md](PATCHES.md) for patch ownership and remaining limitations.

## Licensing

Upstream source bundles retain their original license files. Patches are derived from the GPL-3.0 upstream projects; this repository's scripts and patches are provided under GPL-3.0 (see [LICENSE](LICENSE)). No Balatro game assets or credentials are included.
