-- Run with the patched API directory as cwd; no native libraries required.
local real_getenv = os.getenv
local real_ffi, real_bit = package.loaded.ffi, package.loaded.bit
local calls, warnings = 0, {}
local mode = 'ok'
local symbols = {
    OPENSSL_init_ssl = function() calls = calls + 1; return mode == 'init_failure' and 0 or 1 end,
    TLS_client_method = function() return mode == 'missing_tls' and nil or {} end,
    EVP_sha256 = function() if mode == 'missing_crypto' then error('symbol absent') end return {} end,
}
-- Lua's and/or idiom cannot return nil; make that failure explicit.
symbols.TLS_client_method = function() if mode == 'missing_tls' then return nil end return {} end
package.loaded.ffi = {
    os = 'OSX', C = symbols, cdef = function() end,
    load = function() error('iOS must not load desktop dynamic libraries') end,
}
package.loaded.bit = {}
os.getenv = function(name) if name == 'BMP_IOS_OPENSSL' then return '1' end return real_getenv(name) end
MPAPI = {networking = {}, sendDebugMessage = function() end, sendWarnMessage = function(message) warnings[#warnings + 1] = message end}
local module = dofile('networking/openssl_ffi.lua')
assert(module.available())
assert(module.available() and calls == 1, 'successful initialization must be cached')
for _, failure in ipairs({'init_failure', 'missing_tls', 'missing_crypto'}) do
    mode = failure
    module = dofile('networking/openssl_ffi.lua')
    assert(not module.available(), failure .. ' must fail closed')
end
assert(#warnings == 3)
os.getenv = real_getenv
package.loaded.ffi, package.loaded.bit = real_ffi, real_bit
print('ok iOS static OpenSSL loader success, caching, initialization and symbol failures')
