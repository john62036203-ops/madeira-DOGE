/* madeira-doge: native memcpy / memmove / memset for d3d11-src.dll
 * (tools/build-d3d11-dll.sh links this object ahead of the UCRT import
 * library). OFF unless `env.MADEIRA_D3D11_NATIVE_MEM = 1` is in the game file.
 *
 * Wine's ARM64EC ucrtbase keeps these three as x64 assembly, so every call
 * from DXMT's ARM64EC code is an EC -> x64 crossing and runs in the JIT
 * ([xp-api] EC->x64, [rip-profile] ucrtbase memset / memmove). With the switch
 * the calls stay in ARM64EC code; without it they go to ucrtbase as before
 * (GetProcAddress, once). `[native-mem]` logs the choice once.
 *
 * Compiled with -fno-builtin so the loops below are not turned back into
 * calls to themselves. */
#include <stddef.h>
#include <stdint.h>
#include <windows.h>

typedef void *(*cpy_fn)(void *, const void *, size_t);
typedef void *(*set_fn)(void *, int, size_t);

static volatile LONG mem_mode;            /* 0 unread, 1 native, 2 ucrtbase, 3 reading */
static cpy_fn crt_memcpy, crt_memmove;
static set_fn crt_memset;

static inline uint64_t ld8(const unsigned char *p) { uint64_t v; __builtin_memcpy(&v, p, 8); return v; }
static inline void st8(unsigned char *p, uint64_t v) { __builtin_memcpy(p, &v, 8); }

static void *copy_fwd(void *dst, const void *src, size_t n)
{
    unsigned char *d = dst;
    const unsigned char *s = src;
    while (n >= 32) {
        uint64_t a = ld8(s), b = ld8(s + 8), c = ld8(s + 16), e = ld8(s + 24);
        st8(d, a); st8(d + 8, b); st8(d + 16, c); st8(d + 24, e);
        s += 32; d += 32; n -= 32;
    }
    while (n >= 8) { st8(d, ld8(s)); s += 8; d += 8; n -= 8; }
    while (n) { *d++ = *s++; n--; }
    return dst;
}

static void *copy_bwd(void *dst, const void *src, size_t n)
{
    unsigned char *d = (unsigned char *)dst + n;
    const unsigned char *s = (const unsigned char *)src + n;
    while (n >= 32) {
        uint64_t a, b, c, e;
        s -= 32; d -= 32; n -= 32;
        a = ld8(s); b = ld8(s + 8); c = ld8(s + 16); e = ld8(s + 24);
        st8(d, a); st8(d + 8, b); st8(d + 16, c); st8(d + 24, e);
    }
    while (n >= 8) { s -= 8; d -= 8; n -= 8; st8(d, ld8(s)); }
    while (n) { *--d = *--s; n--; }
    return dst;
}

static void *fill(void *dst, int c, size_t n)
{
    unsigned char *d = dst;
    uint64_t v = (unsigned char)c * 0x0101010101010101ull;
    while (n >= 32) { st8(d, v); st8(d + 8, v); st8(d + 16, v); st8(d + 24, v); d += 32; n -= 32; }
    while (n >= 8) { st8(d, v); d += 8; n -= 8; }
    while (n) { *d++ = (unsigned char)c; n--; }
    return dst;
}

static __attribute__((noinline)) LONG mem_init(void)
{
    char v[8];
    DWORD len;
    HMODULE crt;
    LONG m;
    /* While this runs (it may call back into these functions) everything is native. */
    if (InterlockedCompareExchange(&mem_mode, 3, 0) != 0) return 1;
    len = GetEnvironmentVariableA("MADEIRA_D3D11_NATIVE_MEM", v, sizeof v);
    m = (len >= 1 && len < sizeof v && v[0] == '1') ? 1 : 2;
    if (m == 2) {
        crt = GetModuleHandleA("ucrtbase.dll");
        crt_memcpy = crt ? (cpy_fn)(void *)GetProcAddress(crt, "memcpy") : 0;
        crt_memmove = crt ? (cpy_fn)(void *)GetProcAddress(crt, "memmove") : 0;
        crt_memset = crt ? (set_fn)(void *)GetProcAddress(crt, "memset") : 0;
        if (!crt_memcpy || !crt_memmove || !crt_memset) m = 1;
    }
    {
        static const char on[] = "[native-mem] madeira-doge on: d3d11-src memcpy/memmove/memset are ARM64EC code (MADEIRA_D3D11_NATIVE_MEM)\n";
        static const char off[] = "[native-mem] madeira-doge off: d3d11-src memcpy/memmove/memset go to ucrtbase\n";
        HANDLE e = GetStdHandle(STD_ERROR_HANDLE);
        DWORD w;
        if (e && e != INVALID_HANDLE_VALUE)
            WriteFile(e, m == 1 ? on : off, (DWORD)(m == 1 ? sizeof on : sizeof off) - 1, &w, 0);
    }
    InterlockedExchange(&mem_mode, m);
    return m;
}

static inline LONG mode(void)
{
    LONG m = mem_mode;
    if (__builtin_expect(m == 0, 0)) m = mem_init();
    return m;
}

void *memcpy(void *dst, const void *src, size_t n)
{
    if (mode() == 2) return crt_memcpy(dst, src, n);
    return copy_fwd(dst, src, n);
}

void *memmove(void *dst, const void *src, size_t n)
{
    if (mode() == 2) return crt_memmove(dst, src, n);
    if ((uintptr_t)dst - (uintptr_t)src >= n) return copy_fwd(dst, src, n);
    return copy_bwd(dst, src, n);
}

void *memset(void *dst, int c, size_t n)
{
    if (mode() == 2) return crt_memset(dst, c, n);
    return fill(dst, c, n);
}
