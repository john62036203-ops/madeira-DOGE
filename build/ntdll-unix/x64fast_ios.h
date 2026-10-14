/* x64fast_ios.h -- madeira-doge: x64 fast paths for hot Win32 imports.
 * Included by virtual_ios.c (image mapping, next to the usd-patch).
 *
 * Sekiro (2026-10-14, build 190): the game thread spent ~40% of its samples
 * in x64 -> ARM64EC calls to tiny functions: Enter/Leave/TryEnter-
 * CriticalSection (~900k/s each), TlsGetValue, FlsGetValue, Get/SetLastError.
 * Every such call leaves the translated x64 code for native code and comes
 * back. x64 callers reach these through the module's x64 entry (.hexpthk
 * "fast-forward sequence", or a `jmp [rip+slot]` forwarder in kernel32);
 * ARM64EC callers bind through the redirection metadata and never run it.
 *
 * madeira.cfg x64-fast = 1 places x64 stubs in the unused tail of the
 * module's .hexpthk section and, when the loader restores the protection of
 * a pure x64 module's import table (the IAT sync), points that module's
 * slots for these entries at the stubs. The entries themselves are NOT
 * changed: ARM64EC code that calls them through a pointer (arm64x_check_call
 * reads the entry bytes; ucrtbase does this for FlsGetValue) must still see
 * the fast-forward sequence -- build 193 rewrote the entries and dockhost
 * died at ucrtbase+0x90fe4 calling address 0. A stub does what Wine's C code
 * does on the common path (same TEB/critical-section fields) and otherwise
 * runs the original entry (copied after the stub), so contention, waits and
 * unusual indices still go to Wine. The stubs' source and a native x86-64
 * stress test are in tests/host/x64fast/.
 * x64-fast-spin = N: an x64 enter spins up to N times on a section another
 * thread holds before taking Wine's waiting path (0 = Wine's own behaviour).
 * Nothing here runs unless x64-fast = 1. */

/* Generated from tests/host/x64fast/stubs.asm (nasm -f bin). */
static const unsigned char x64f_cs_enter[93] = {
    0x65, 0x48, 0x8b, 0x14, 0x25, 0x48, 0x00, 0x00, 0x00, 0x45, 0x31, 0xc0,
    0xb8, 0xff, 0xff, 0xff, 0xff, 0xf0, 0x44, 0x0f, 0xb1, 0x41, 0x08, 0x75,
    0x0e, 0x48, 0x89, 0x51, 0x10, 0xc7, 0x41, 0x0c, 0x01, 0x00, 0x00, 0x00,
    0x31, 0xc0, 0xc3, 0x48, 0x39, 0x51, 0x10, 0x75, 0x0a, 0xf0, 0xff, 0x41,
    0x08, 0xff, 0x41, 0x0c, 0x31, 0xc0, 0xc3, 0x41, 0xb9, 0x5a, 0x5a, 0x5a,
    0x5a, 0x45, 0x85, 0xc9, 0x74, 0x1b, 0xf3, 0x90, 0x8b, 0x41, 0x08, 0x83,
    0xf8, 0xff, 0x75, 0x08, 0xf0, 0x44, 0x0f, 0xb1, 0x41, 0x08, 0x74, 0xc5,
    0x85, 0xc0, 0x7f, 0x05, 0x41, 0xff, 0xc9, 0x75, 0xe5
};
static const unsigned char x64f_cs_leave[75] = {
    0x8b, 0x41, 0x0c, 0x83, 0xf8, 0x01, 0x75, 0x37, 0x83, 0x79, 0x08, 0x00,
    0x75, 0x3d, 0x48, 0x8b, 0x51, 0x10, 0x48, 0xc7, 0x41, 0x10, 0x00, 0x00,
    0x00, 0x00, 0xc7, 0x41, 0x0c, 0x00, 0x00, 0x00, 0x00, 0x31, 0xc0, 0x41,
    0xb8, 0xff, 0xff, 0xff, 0xff, 0xf0, 0x44, 0x0f, 0xb1, 0x41, 0x08, 0x75,
    0x01, 0xc3, 0xc7, 0x41, 0x0c, 0x01, 0x00, 0x00, 0x00, 0x48, 0x89, 0x51,
    0x10, 0xeb, 0x0c, 0x7c, 0x0a, 0xff, 0x49, 0x0c, 0xf0, 0xff, 0x49, 0x08,
    0x31, 0xc0, 0xc3
};
static const unsigned char x64f_cs_try[64] = {
    0x65, 0x48, 0x8b, 0x14, 0x25, 0x48, 0x00, 0x00, 0x00, 0x45, 0x31, 0xc0,
    0xb8, 0xff, 0xff, 0xff, 0xff, 0xf0, 0x44, 0x0f, 0xb1, 0x41, 0x08, 0x75,
    0x11, 0x48, 0x89, 0x51, 0x10, 0xc7, 0x41, 0x0c, 0x01, 0x00, 0x00, 0x00,
    0xb8, 0x01, 0x00, 0x00, 0x00, 0xc3, 0x48, 0x39, 0x51, 0x10, 0x75, 0x0d,
    0xf0, 0xff, 0x41, 0x08, 0xff, 0x41, 0x0c, 0xb8, 0x01, 0x00, 0x00, 0x00,
    0xc3, 0x31, 0xc0, 0xc3
};
static const unsigned char x64f_le_set[9] = {
    0x65, 0x89, 0x0c, 0x25, 0x68, 0x00, 0x00, 0x00, 0xc3
};
static const unsigned char x64f_le_get[9] = {
    0x65, 0x8b, 0x04, 0x25, 0x68, 0x00, 0x00, 0x00, 0xc3
};
static const unsigned char x64f_tls_get[29] = {
    0x83, 0xf9, 0x40, 0x73, 0x18, 0x89, 0xc9, 0x65, 0xc7, 0x04, 0x25, 0x68,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x65, 0x48, 0x8b, 0x04, 0xcd,
    0x80, 0x14, 0x00, 0x00, 0xc3
};
static const unsigned char x64f_fls_get[51] = {
    0x8d, 0x41, 0xff, 0x83, 0xf8, 0x0e, 0x77, 0x2b, 0x65, 0x48, 0x8b, 0x04,
    0x25, 0xc8, 0x17, 0x00, 0x00, 0x48, 0x85, 0xc0, 0x74, 0x1d, 0x48, 0x8b,
    0x40, 0x10, 0x48, 0x85, 0xc0, 0x74, 0x07, 0x89, 0xc9, 0x48, 0x8b, 0x44,
    0xc8, 0x08, 0x65, 0xc7, 0x04, 0x25, 0x68, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0xc3
};
#define X64F_SPIN_AT 57   /* offset of the spin count imm32 in x64f_cs_enter */

enum { X64F_ENTER, X64F_LEAVE, X64F_TRY, X64F_LESET, X64F_LEGET, X64F_TLS, X64F_FLS };

static const struct { const unsigned char *code; unsigned int len; int needs_fallback; } x64f_stub[] =
{
    { x64f_cs_enter, sizeof(x64f_cs_enter), 1 },
    { x64f_cs_leave, sizeof(x64f_cs_leave), 1 },
    { x64f_cs_try,   sizeof(x64f_cs_try),   0 },
    { x64f_le_set,   sizeof(x64f_le_set),   0 },
    { x64f_le_get,   sizeof(x64f_le_get),   0 },
    { x64f_tls_get,  sizeof(x64f_tls_get),  1 },
    { x64f_fls_get,  sizeof(x64f_fls_get),  1 },
};

static const struct { const char *module, *name; int kind; } x64f_targets[] =
{
    { "ntdll.dll",      "RtlEnterCriticalSection",    X64F_ENTER },
    { "ntdll.dll",      "RtlLeaveCriticalSection",    X64F_LEAVE },
    { "ntdll.dll",      "RtlTryEnterCriticalSection", X64F_TRY },
    { "ntdll.dll",      "RtlSetLastWin32Error",       X64F_LESET },
    { "ntdll.dll",      "RtlRestoreLastWin32Error",   X64F_LESET },
    { "ntdll.dll",      "RtlGetLastWin32Error",       X64F_LEGET },
    { "kernelbase.dll", "TlsGetValue",                X64F_TLS },
    { "kernelbase.dll", "GetLastError",               X64F_LEGET },
    { "kernelbase.dll", "FlsGetValue",                X64F_FLS },
    { "kernel32.dll",   "TlsGetValue",                X64F_TLS },
    { "kernel32.dll",   "GetLastError",               X64F_LEGET },
    { "kernel32.dll",   "SetLastError",               X64F_LESET },
    { "kernel32.dll",   "FlsGetValue",                X64F_FLS },
};

static int x64f_mode = -1, x64f_spin;

/* entry -> stub pairs of every placed module copy (each pseudo-process maps its own) */
#define X64F_MAX_PAIRS 512
static struct { uintptr_t entry, stub; } x64f_pairs[X64F_MAX_PAIRS];
static int x64f_npairs;

static uintptr_t x64f_stub_for( uintptr_t entry )
{
    int i, n = __atomic_load_n( &x64f_npairs, __ATOMIC_ACQUIRE );
    for (i = 0; i < n; i++) if (x64f_pairs[i].entry == entry) return x64f_pairs[i].stub;
    return 0;
}

static int x64f_enabled( void )
{
    if (x64f_mode < 0)
    {
        /* spins of an x64 critical-section enter on a section another thread holds, before Wine's wait (x64-fast = 1 only) */
        x64f_spin = madeira_cfg_int( "x64-fast-spin", 0 );
        if (x64f_spin < 0) x64f_spin = 0;
        if (x64f_spin > 100000) x64f_spin = 100000;
        /* 1: x64 fast paths for critical sections, TlsGetValue, FlsGetValue and Get/SetLastError (Sekiro: ~40% of the game thread was spent calling these) */
        x64f_mode = madeira_cfg_int( "x64-fast", 0 ) == 1;
    }
    return x64f_mode;
}

static int x64f_in( size_t size, unsigned int rva, unsigned int len )
{
    return rva < size && len <= size - rva;
}

/* RVA of a named export; 0 when absent or a forwarder string. */
static unsigned int x64f_export( const unsigned char *img, size_t size, const char *name )
{
    unsigned int pe, dir, dir_size, nnames, funcs, names, ords, i;

    if (size < 0x40 || img[0] != 'M' || img[1] != 'Z') return 0;
    pe = *(const unsigned int *)(img + 0x3c);
    if (!x64f_in( size, pe, 24 + 112 + 8 ) || memcmp( img + pe, "PE\0\0", 4 ) ||
        *(const unsigned short *)(img + pe + 24) != 0x20b) return 0;
    dir = *(const unsigned int *)(img + pe + 24 + 112);
    dir_size = *(const unsigned int *)(img + pe + 24 + 116);
    if (!dir || !x64f_in( size, dir, 40 )) return 0;
    nnames = *(const unsigned int *)(img + dir + 24);
    funcs = *(const unsigned int *)(img + dir + 28);
    names = *(const unsigned int *)(img + dir + 32);
    ords = *(const unsigned int *)(img + dir + 36);
    if (!x64f_in( size, names, nnames * 4 ) || !x64f_in( size, ords, nnames * 2 )) return 0;
    for (i = 0; i < nnames; i++)
    {
        unsigned int n = *(const unsigned int *)(img + names + 4 * i), rva;
        unsigned short o = *(const unsigned short *)(img + ords + 2 * i);
        size_t k = strlen( name ) + 1;
        if (!x64f_in( size, n, (unsigned int)k ) || memcmp( img + n, name, k )) continue;
        if (!x64f_in( size, funcs + 4u * o, 4 )) return 0;
        rva = *(const unsigned int *)(img + funcs + 4u * o);
        if (rva >= dir && rva < dir + dir_size) return 0;   /* forwarder */
        return rva;
    }
    return 0;
}

/* The unused tail of .hexpthk inside its last 4 KB page: [*lo, *hi). */
static int x64f_slack( const unsigned char *img, size_t size, unsigned int *lo, unsigned int *hi )
{
    unsigned int pe = *(const unsigned int *)(img + 0x3c), sec, i;
    unsigned short nsec = *(const unsigned short *)(img + pe + 6);
    unsigned short opt = *(const unsigned short *)(img + pe + 20);

    sec = pe + 24 + opt;
    if (!x64f_in( size, sec, nsec * 40u )) return 0;
    for (i = 0; i < nsec; i++)
    {
        const unsigned char *s = img + sec + 40 * i;
        unsigned int vsize = *(const unsigned int *)(s + 8), va = *(const unsigned int *)(s + 12), r;
        if (memcmp( s, ".hexpthk", 8 )) continue;
        *lo = (va + vsize + 15) & ~15u;
        *hi = (va + vsize + 0xfff) & ~0xfffu;
        if (*hi > size) return 0;
        for (r = *lo; r < *hi; r++) if (img[r] != 0xcc && img[r]) return 0;
        return *hi > *lo;
    }
    return 0;
}

static const unsigned char x64f_ffs[10] = { 0x48, 0x8b, 0xc4, 0x48, 0x89, 0x58, 0x20, 0x55, 0x5d, 0xe9 };

/* Writes len bytes at rva into the mapped image. Returns 0 when that failed. */
static int x64f_poke_image( unsigned char *img, unsigned int rva, const unsigned char *bytes, unsigned int len )
{
    char *p = (char *)img + rva;
    char *pg = (char *)((uintptr_t)p & ~(uintptr_t)host_page_mask);
    size_t pgsz = ROUND_SIZE( p, len, host_page_mask );
    int restore = PROT_READ;
    mach_vm_address_t ra = (mach_vm_address_t)(uintptr_t)pg;
    mach_vm_size_t rs = 0;
    vm_region_basic_info_data_64_t ri;
    mach_msg_type_number_t rc = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t ro = MACH_PORT_NULL;

    if (mach_vm_region( mach_task_self(), &ra, &rs, VM_REGION_BASIC_INFO_64,
                        (vm_region_info_t)&ri, &rc, &ro ) == KERN_SUCCESS &&
        ra <= (mach_vm_address_t)(uintptr_t)pg)
        restore = ri.protection & (PROT_READ | PROT_WRITE);
    if (!mprotect( pg, pgsz, PROT_READ | PROT_WRITE ) ||
        vm_protect( mach_task_self(), (vm_address_t)pg, pgsz, FALSE,
                    VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY ) == KERN_SUCCESS)
    {
        memcpy( p, bytes, len );
        mprotect( pg, pgsz, restore );
        return 1;
    }
    return 0;
}

/* Writes len bytes at rva into the mapped image and its JIT-pool copy (the
 * same two writes as MADEIRA_PATCH_RVA). Returns 0 when the image write failed. */
static int x64f_poke( unsigned char *img, unsigned char *pool_rw, unsigned char *pool_rx,
                      unsigned int rva, const unsigned char *bytes, unsigned int len )
{
    int ok = x64f_poke_image( img, rva, bytes, len );
    memcpy( pool_rw + rva, bytes, len );
    sys_icache_invalidate( pool_rx + rva, len );
    return ok;
}

static void x64f_patch_image( unsigned char *img, size_t size, unsigned char *pool_rw,
                              unsigned char *pool_rx, const char *mn )
{
    unsigned char blob[0x1000];
    unsigned int lo, hi, used = 0, i, n = 0, want = 0;
    struct { unsigned int entry, stub; } done[16];

    if (!mn || !x64f_enabled()) return;
    for (i = 0; i < sizeof(x64f_targets) / sizeof(x64f_targets[0]); i++)
        if (!strcasecmp( mn, x64f_targets[i].module )) want++;
    if (!want) return;
    for (i = 0; i < sizeof(x64f_targets) / sizeof(x64f_targets[0]); i++)
    {
        unsigned int e;
        if (strcasecmp( mn, x64f_targets[i].module )) continue;
        e = x64f_export( img, size, x64f_targets[i].name );
        if (e && x64f_stub_for( (uintptr_t)img + e )) return;   /* this image is already done */
    }
    if (!x64f_slack( img, size, &lo, &hi ))
    {
        dprintf( 2, "[x64-fast] %s: no free tail in .hexpthk, left alone\n", mn );
        return;
    }
    memset( blob, 0xcc, sizeof(blob) );
    for (i = 0; i < sizeof(x64f_targets) / sizeof(x64f_targets[0]); i++)
    {
        const unsigned char *code = x64f_stub[x64f_targets[i].kind].code;
        unsigned int len = x64f_stub[x64f_targets[i].kind].len;
        unsigned int e = 0, stub = lo + used, fb = stub + len, need;
        unsigned char fall[16];
        unsigned int fall_len = 0;
        int rel;

        if (strcasecmp( mn, x64f_targets[i].module )) continue;
        e = x64f_export( img, size, x64f_targets[i].name );
        if (!e || !x64f_in( size, e, 16 )) continue;
        if (!memcmp( img + e, x64f_ffs, sizeof(x64f_ffs) ))
        {
            /* the fast-forward sequence, its jump re-aimed from the copy */
            unsigned int target = e + 14 + *(const int *)(img + e + 10);
            memcpy( fall, img + e, 9 );
            fall[9] = 0xe9;
            rel = (int)(target - (fb + 14));
            memcpy( fall + 10, &rel, 4 );
            fall_len = 14;
        }
        else if (img[e] == 0xff && img[e + 1] == 0x25)
        {
            /* jmp [rip+slot]: the same slot, read from the copy */
            unsigned int slot = e + 6 + *(const int *)(img + e + 2);
            fall[0] = 0xff; fall[1] = 0x25;
            rel = (int)(slot - (fb + 6));
            memcpy( fall + 2, &rel, 4 );
            fall_len = 6;
        }
        else continue;   /* not an entry this code knows (already patched, or a new build) */

        need = (len + (x64f_stub[x64f_targets[i].kind].needs_fallback ? fall_len : 0) + 15) & ~15u;
        if (lo + used + need > hi || n >= 16) break;
        memcpy( blob + used, code, len );
        if (x64f_targets[i].kind == X64F_ENTER) memcpy( blob + used + X64F_SPIN_AT, &x64f_spin, 4 );
        if (x64f_stub[x64f_targets[i].kind].needs_fallback) memcpy( blob + used + len, fall, fall_len );
        done[n].entry = e;
        done[n].stub = stub;
        n++;
        used += need;
    }
    if (!n) return;
    /* Stubs only: the entries stay as they are (see the top of this file). */
    if (!x64f_poke( img, pool_rw, pool_rx, lo, blob, used ))
    {
        dprintf( 2, "[x64-fast] %s: could not write the stubs into the image, left alone\n", mn );
        return;
    }
    for (i = 0; i < n; i++)
    {
        int k = __atomic_load_n( &x64f_npairs, __ATOMIC_ACQUIRE );
        if (k >= X64F_MAX_PAIRS) break;
        x64f_pairs[k].entry = (uintptr_t)img + done[i].entry;
        x64f_pairs[k].stub = (uintptr_t)img + done[i].stub;
        __atomic_store_n( &x64f_npairs, k + 1, __ATOMIC_RELEASE );
    }
    dprintf( 2, "[x64-fast] %s @%p: %u of %u x64 stubs placed (+0x%x, %u bytes, spin %d); x64 modules' import slots are pointed at them\n",
             mn, img, n, want, lo, used, x64f_spin );
}

/* A pure x64 image (no .hexpthk): point its import slots that hold a placed
 * entry at the stub. Called from the IAT sync with the region whose
 * protection was just restored, before the region is copied to the pool. */
static void x64f_redirect_iat( unsigned char *img, size_t size, size_t off, size_t len )
{
    unsigned int pe, iat, iat_size, sec, i, hits = 0, fails = 0;
    unsigned short nsec, opt;
    size_t a, b;

    if (!x64f_mode || !__atomic_load_n( &x64f_npairs, __ATOMIC_ACQUIRE )) return;
    if (size < 0x200 || img[0] != 'M' || img[1] != 'Z') return;
    pe = *(const unsigned int *)(img + 0x3c);
    if (!x64f_in( size, pe, 24 + 112 + 8 * 13 ) || memcmp( img + pe, "PE\0\0", 4 ) ||
        *(const unsigned short *)(img + pe + 4) != 0x8664 ||
        *(const unsigned short *)(img + pe + 24) != 0x20b) return;
    nsec = *(const unsigned short *)(img + pe + 6);
    opt = *(const unsigned short *)(img + pe + 20);
    sec = pe + 24 + opt;
    if (!x64f_in( size, sec, nsec * 40u )) return;
    for (i = 0; i < nsec; i++)
        if (!memcmp( img + sec + 40 * i, ".hexpthk", 8 )) return;   /* hybrid: EC callers bind via metadata */
    iat = *(const unsigned int *)(img + pe + 24 + 112 + 8 * 12);
    iat_size = *(const unsigned int *)(img + pe + 24 + 112 + 8 * 12 + 4);
    if (!iat || !x64f_in( size, iat, iat_size )) return;
    a = iat > off ? iat : off;
    b = (size_t)iat + iat_size < off + len ? (size_t)iat + iat_size : off + len;
    for (a = (a + 7) & ~(size_t)7; a + 8 <= b; a += 8)
    {
        uintptr_t stub = x64f_stub_for( *(const uintptr_t *)(img + a) );
        if (!stub) continue;
        if (x64f_poke_image( img, (unsigned int)a, (const unsigned char *)&stub, 8 )) hits++;
        else fails++;
    }
    if (hits || fails)
        dprintf( 2, "[x64-fast] x64 image %p: %u import slot(s) now call x64 stubs%s\n", img, hits,
                 fails ? " (some image writes FAILED)" : "" );
}
