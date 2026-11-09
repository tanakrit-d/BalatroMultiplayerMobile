# Migration and validation baseline

## Source equivalence

Initial official release pins:

- API v1.0.5: `958607d55c93375f859f2993423950af42ec85d3`
- PvP v1.0.5: `a5aac88ed508848f061a3d3e552b6f8920fb0a33`

Both tag-to-commit mappings were checked against the upstream GitHub API on 2026-11-09. Source archive SHA-256 values are in `sources.lock.json`.

The migration audit reconstructs official sources and compares every historical tracked file except maintenance workflows, README and mobile maintenance documentation. It compares 232 API files and 584 PvP files against the mobile commits recorded in PATCHES.md. API's OpenSSL loader is compared against the historical builder adapter applied to that source. All compared files match byte-for-byte.

To repeat with the historical repositories available locally:

```sh
uv run --locked python scripts/check_baseline.py /path/to/repositories
```

This audit is a migration check, not a build dependency. Normal builds download only official pinned sources and use this repository's patches.

## Builder cutover

The existing IPA builder and old fork workflows have not been changed. Complete these steps before retiring them:

1. Publish this repository and establish a reviewed, tested patch-repository commit.
2. Have the IPA builder pin that commit and consume the verified source bundle (or invoke this pipeline from that checkout). Do not resolve mutable fork branches.
3. Replace only the builder's OpenSSL Lua injection. Retain native compilation, exported symbols, CA packaging, runtime environment variables and desktop DLL/dylib filtering.
4. Embed the source bundle's provenance in the IPA manifest alongside the builder/runtime pins. Assign a new immutable mobile build revision without changing the upstream marketing version.
5. Verify the actual IPA contents and complete two-device login/gameplay/reconnect/account-persistence testing.
6. After a validated cutover, disable the two old scheduled sync workflows. Preserve their branches/tags as historical references.

The source artifacts here do not contain game assets, native iOS runtime binaries or an IPA. Source release publication is available through the manual publish workflow. Stable IPA publication remains an explicit later stage. TLS verification changes are separate from this behavior-preserving migration.

## Local validation, 2026-11-09

- Seven Python pipeline tests passed: archive safety/checksums, strict patch preimages, API compatibility, moved release tags, annotated-tag resolution with atomic pair updates, and deterministic bundles.
- 53 Lua test files were invoked under each runtime: Lua 5.1.5 and LuaJIT 2.1. Lua 5.1 explicitly skips `nemesis_deck_test` because it requires `goto`; LuaJIT covers it. These totals include the additional static OpenSSL loader regression test.
- Both workflow files parse as YAML; their shell blocks pass `bash -n`. Hosted Actions execution is pending repository publication.
- The live release updater resolved both latest official releases to the existing v1.0.5 pins without changing the lock.
- Source equivalence passed for the 816 historical files described above. Device gameplay and IPA validation remain pending.

The Lua runtimes used for local validation were built in the ignored `.cache/` directory, without modifying system installations. CI installs Lua 5.1 and LuaJIT from the runner's package manager.
