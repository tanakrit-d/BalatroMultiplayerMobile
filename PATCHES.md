# Patch inventory

| Patch | Purpose | Origin |
| --- | --- | --- |
| API 001 | Persist an OS-random Community credential outside the mod; preserve desktop Steam and Official login; mobile regression tests | API mobile `297389bba79b135567c6e0ebd9b984affb108a56` |
| API 002 | Load runtime-linked OpenSSL through `ffi.C` when `BMP_IOS_OPENSSL=1`; stop on initialization/symbol errors | Builder `088e9e56416d7690b226047fc617fab7616000b0` |
| PvP 001 | Use `loadstring or load`; explicitly skip the LuaJIT `goto` test on plain Lua 5.1 | PvP mobile `88976150d069db4acfaf5d3d278e763c76338c59` |

Native OpenSSL compilation, CA packaging, symbol export, environment setup, desktop-library removal, download retries and IPA packaging remain builder responsibilities. The API loader patch replaces only the builder's Lua source injection.

This migration deliberately preserves existing runtime behavior. The existing API transport disables TLS peer verification; certificate-chain and hostname verification need a separate tested change. The packaged CA bundle alone does not enable verification. Do not describe these bundles as TLS-hardened.

The Community identity file is an account credential. Keep it out of Git, logs and build artifacts; preserve it across mod updates. Official login still requires Steam.

Standalone tests do not demonstrate iOS networking or gameplay. Before stable IPA publication, test two devices, login, a complete match, background/resume, reconnect and account persistence across an update. No device-tested baseline is claimed here.
