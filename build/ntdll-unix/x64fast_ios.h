/* x64fast_ios.h -- madeira-doge: x64 fast paths for hot Win32 imports.
 * Included by virtual_ios.c (image mapping, next to the usd-patch).
 *
 * Sekiro (2026-10-14, build 190): the game thread spent ~40% of its samples
 * in x64 -> ARM64EC calls to tiny functions: Enter/Leave/TryEnter-
 * CriticalSection (~900k/s each), TlsGetValue, FlsGetValue, Get/SetLastError.
 * MH Rise (2026-10-15, build 199, 2.6 M x64->EC calls/s): ucrtbase memmove/
 * memcpy/memset and SRW shared acquire/release. Copies and fills up to 128
 * bytes are done in x64 (all loads before any store, so memmove overlap is
 * safe); larger ones run the native code. SRW: shared acquire/release and
 * exclusive acquire when nobody waits; exclusive release always goes to Wine
 * (it cannot tell whether shared waiters need a wake).
 * MH Rise (2026-10-19, build 247, x64-fast on, still 1.6 M x64->EC calls/s):
 * the top target was RtlQueryPerformanceCounter (0.78 M/s), already user-mode
 * on the EC side (ml1117), so the whole cost was the crossing. Its x64 stub
 * does the same arithmetic on the same statics with FEX's rdtsc (CNTVCT <<
 * TSCScale) and leaves every resync to Wine's code. kernel32's
 * QueryPerformanceCounter is a `jmp [rip+slot]` into ntdll; import slots that
 * hold it are pointed at ntdll's stub. The x64 calls no longer reach the
 * ml1131 per-thread gap census ([xp-api-qpc]).
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
static const unsigned char x64f_srw_as[20] = {
    0x8b, 0x01, 0x66, 0x85, 0xc0, 0x75, 0x0d, 0x8d, 0x90, 0x00, 0x00, 0x01,
    0x00, 0xf0, 0x0f, 0xb1, 0x11, 0x75, 0xef, 0xc3
};
static const unsigned char x64f_srw_rs[27] = {
    0x8b, 0x01, 0x66, 0x85, 0xc0, 0x75, 0x14, 0x3d, 0x00, 0x00, 0x01, 0x00,
    0x72, 0x0d, 0x8d, 0x90, 0x00, 0x00, 0xff, 0xff, 0xf0, 0x0f, 0xb1, 0x11,
    0x75, 0xe8, 0xc3
};
static const unsigned char x64f_srw_ax[14] = {
    0x31, 0xc0, 0xba, 0x01, 0x00, 0x01, 0x00, 0xf0, 0x0f, 0xb1, 0x11, 0x75,
    0x01, 0xc3
};
static const unsigned char x64f_mem_copy[309] = {
    0x48, 0x89, 0xc8, 0x49, 0x83, 0xf8, 0x10, 0x0f, 0x82, 0xcd, 0x00, 0x00,
    0x00, 0x49, 0x83, 0xf8, 0x20, 0x77, 0x17, 0xf3, 0x0f, 0x6f, 0x02, 0xf3,
    0x42, 0x0f, 0x6f, 0x4c, 0x02, 0xf0, 0xf3, 0x0f, 0x7f, 0x01, 0xf3, 0x42,
    0x0f, 0x7f, 0x4c, 0x01, 0xf0, 0xc3, 0x49, 0x83, 0xf8, 0x40, 0x77, 0x2f,
    0xf3, 0x0f, 0x6f, 0x02, 0xf3, 0x0f, 0x6f, 0x4a, 0x10, 0xf3, 0x42, 0x0f,
    0x6f, 0x54, 0x02, 0xe0, 0xf3, 0x42, 0x0f, 0x6f, 0x5c, 0x02, 0xf0, 0xf3,
    0x0f, 0x7f, 0x01, 0xf3, 0x0f, 0x7f, 0x49, 0x10, 0xf3, 0x42, 0x0f, 0x7f,
    0x54, 0x01, 0xe0, 0xf3, 0x42, 0x0f, 0x7f, 0x5c, 0x01, 0xf0, 0xc3, 0x49,
    0x81, 0xf8, 0x80, 0x00, 0x00, 0x00, 0x0f, 0x87, 0xc9, 0x00, 0x00, 0x00,
    0xf3, 0x0f, 0x6f, 0x02, 0xf3, 0x0f, 0x6f, 0x4a, 0x10, 0xf3, 0x0f, 0x6f,
    0x52, 0x20, 0xf3, 0x0f, 0x6f, 0x5a, 0x30, 0xf3, 0x42, 0x0f, 0x6f, 0x64,
    0x02, 0xc0, 0xf3, 0x42, 0x0f, 0x6f, 0x6c, 0x02, 0xd0, 0x4e, 0x8b, 0x4c,
    0x02, 0xe0, 0x4e, 0x8b, 0x54, 0x02, 0xe8, 0x4e, 0x8b, 0x5c, 0x02, 0xf0,
    0x4a, 0x8b, 0x44, 0x02, 0xf8, 0xf3, 0x0f, 0x7f, 0x01, 0xf3, 0x0f, 0x7f,
    0x49, 0x10, 0xf3, 0x0f, 0x7f, 0x51, 0x20, 0xf3, 0x0f, 0x7f, 0x59, 0x30,
    0xf3, 0x42, 0x0f, 0x7f, 0x64, 0x01, 0xc0, 0xf3, 0x42, 0x0f, 0x7f, 0x6c,
    0x01, 0xd0, 0x4e, 0x89, 0x4c, 0x01, 0xe0, 0x4e, 0x89, 0x54, 0x01, 0xe8,
    0x4e, 0x89, 0x5c, 0x01, 0xf0, 0x4a, 0x89, 0x44, 0x01, 0xf8, 0x48, 0x89,
    0xc8, 0xc3, 0x49, 0x83, 0xf8, 0x08, 0x72, 0x11, 0x4c, 0x8b, 0x0a, 0x4e,
    0x8b, 0x54, 0x02, 0xf8, 0x4c, 0x89, 0x09, 0x4e, 0x89, 0x54, 0x01, 0xf8,
    0xc3, 0x49, 0x83, 0xf8, 0x04, 0x72, 0x11, 0x44, 0x8b, 0x0a, 0x46, 0x8b,
    0x54, 0x02, 0xfc, 0x44, 0x89, 0x09, 0x46, 0x89, 0x54, 0x01, 0xfc, 0xc3,
    0x4d, 0x85, 0xc0, 0x74, 0x27, 0x44, 0x0f, 0xb6, 0x0a, 0x46, 0x0f, 0xb6,
    0x54, 0x02, 0xff, 0x4d, 0x89, 0xc3, 0x49, 0xd1, 0xeb, 0x46, 0x0f, 0xb6,
    0x1c, 0x1a, 0x4c, 0x89, 0xc2, 0x48, 0xd1, 0xea, 0x44, 0x88, 0x09, 0x46,
    0x88, 0x54, 0x01, 0xff, 0x44, 0x88, 0x1c, 0x11, 0xc3
};
static const unsigned char x64f_mem_set[196] = {
    0x49, 0x81, 0xf8, 0x80, 0x00, 0x00, 0x00, 0x0f, 0x87, 0xb7, 0x00, 0x00,
    0x00, 0x0f, 0xb6, 0xd2, 0x49, 0xb9, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
    0x01, 0x01, 0x49, 0x0f, 0xaf, 0xd1, 0x48, 0x89, 0xc8, 0x49, 0x83, 0xf8,
    0x10, 0x72, 0x69, 0x66, 0x48, 0x0f, 0x6e, 0xc2, 0x66, 0x0f, 0x6c, 0xc0,
    0x49, 0x83, 0xf8, 0x20, 0x77, 0x0c, 0xf3, 0x0f, 0x7f, 0x01, 0xf3, 0x42,
    0x0f, 0x7f, 0x44, 0x01, 0xf0, 0xc3, 0x49, 0x83, 0xf8, 0x40, 0x77, 0x18,
    0xf3, 0x0f, 0x7f, 0x01, 0xf3, 0x0f, 0x7f, 0x41, 0x10, 0xf3, 0x42, 0x0f,
    0x7f, 0x44, 0x01, 0xe0, 0xf3, 0x42, 0x0f, 0x7f, 0x44, 0x01, 0xf0, 0xc3,
    0xf3, 0x0f, 0x7f, 0x01, 0xf3, 0x0f, 0x7f, 0x41, 0x10, 0xf3, 0x0f, 0x7f,
    0x41, 0x20, 0xf3, 0x0f, 0x7f, 0x41, 0x30, 0xf3, 0x42, 0x0f, 0x7f, 0x44,
    0x01, 0xc0, 0xf3, 0x42, 0x0f, 0x7f, 0x44, 0x01, 0xd0, 0xf3, 0x42, 0x0f,
    0x7f, 0x44, 0x01, 0xe0, 0xf3, 0x42, 0x0f, 0x7f, 0x44, 0x01, 0xf0, 0xc3,
    0x49, 0x83, 0xf8, 0x08, 0x72, 0x09, 0x48, 0x89, 0x11, 0x4a, 0x89, 0x54,
    0x01, 0xf8, 0xc3, 0x49, 0x83, 0xf8, 0x04, 0x72, 0x08, 0x89, 0x11, 0x42,
    0x89, 0x54, 0x01, 0xfc, 0xc3, 0x4d, 0x85, 0xc0, 0x74, 0x11, 0x4d, 0x89,
    0xc1, 0x49, 0xd1, 0xe9, 0x88, 0x11, 0x42, 0x88, 0x54, 0x01, 0xff, 0x42,
    0x88, 0x14, 0x09, 0xc3
};
#define X64F_SPIN_AT 57   /* offset of the spin count imm32 in x64f_cs_enter */
static const unsigned char x64f_qpc[103] = {
    0x80, 0x3d, 0x60, 0x00, 0x00, 0x00, 0x00, 0x75, 0x5e, 0x4c, 0x8b, 0x05, 0x58, 0x00, 0x00, 0x00,
    0x4d, 0x85, 0xc0, 0x74, 0x52, 0x4c, 0x8b, 0x0d, 0x54, 0x00, 0x00, 0x00, 0x4d, 0x85, 0xc9, 0x74,
    0x46, 0x0f, 0x31, 0x48, 0xc1, 0xe2, 0x20, 0x48, 0x09, 0xd0, 0x48, 0xc1, 0xe8, 0x06, 0x49, 0x89,
    0xc3, 0x4c, 0x29, 0xc8, 0x4c, 0x39, 0xc0, 0x73, 0x2e, 0x4c, 0x89, 0xd8, 0x31, 0xd2, 0x49, 0xf7,
    0xf0, 0x4c, 0x69, 0xd8, 0x80, 0x96, 0x98, 0x00, 0x48, 0x69, 0xc2, 0x80, 0x96, 0x98, 0x00, 0x31,
    0xd2, 0x49, 0xf7, 0xf0, 0x4c, 0x01, 0xd8, 0x48, 0x03, 0x05, 0x1a, 0x00, 0x00, 0x00, 0x48, 0x89,
    0x01, 0xb8, 0x01, 0x00, 0x00, 0x00, 0xc3
};

/* RtlQueryPerformanceCounter (MH Rise build 247: ntdll+0x71aac, the EC body,
 * was the top x64->EC target at 0.8 M calls/s). Offsets inside x64f_qpc: the
 * END of each rip-relative instruction (its displacement is the 4 bytes before
 * the end; for the cmp the imm8 comes last, so 5 before) and the shift imm8. */
#define X64F_QPC_DIS_END   7
#define X64F_QPC_FREQ_END  16
#define X64F_QPC_LAST_END  28
#define X64F_QPC_SHIFT_END 46
#define X64F_QPC_OFF_END   94


enum { X64F_ENTER, X64F_LEAVE, X64F_TRY, X64F_LESET, X64F_LEGET, X64F_TLS, X64F_FLS,
       X64F_SRW_AS, X64F_SRW_RS, X64F_SRW_AX, X64F_MEMCPY, X64F_MEMSET, X64F_QPC };

static const struct { const unsigned char *code; unsigned int len; int needs_fallback; } x64f_stub[] =
{
    { x64f_cs_enter, sizeof(x64f_cs_enter), 1 },
    { x64f_cs_leave, sizeof(x64f_cs_leave), 1 },
    { x64f_cs_try,   sizeof(x64f_cs_try),   0 },
    { x64f_le_set,   sizeof(x64f_le_set),   0 },
    { x64f_le_get,   sizeof(x64f_le_get),   0 },
    { x64f_tls_get,  sizeof(x64f_tls_get),  1 },
    { x64f_fls_get,  sizeof(x64f_fls_get),  1 },
    { x64f_srw_as,   sizeof(x64f_srw_as),   1 },
    { x64f_srw_rs,   sizeof(x64f_srw_rs),   1 },
    { x64f_srw_ax,   sizeof(x64f_srw_ax),   1 },
    { x64f_mem_copy, sizeof(x64f_mem_copy), 1 },
    { x64f_mem_set,  sizeof(x64f_mem_set),  1 },
    { x64f_qpc,      sizeof(x64f_qpc),      1 },
};

static const struct { const char *module, *name; int kind; } x64f_targets[] =
{
    { "ntdll.dll",      "RtlEnterCriticalSection",    X64F_ENTER },
    { "ntdll.dll",      "RtlLeaveCriticalSection",    X64F_LEAVE },
    { "ntdll.dll",      "RtlTryEnterCriticalSection", X64F_TRY },
    { "ntdll.dll",      "RtlSetLastWin32Error",       X64F_LESET },
    { "ntdll.dll",      "RtlRestoreLastWin32Error",   X64F_LESET },
    { "ntdll.dll",      "RtlGetLastWin32Error",       X64F_LEGET },
    { "ntdll.dll",      "RtlAcquireSRWLockShared",    X64F_SRW_AS },
    { "ntdll.dll",      "RtlReleaseSRWLockShared",    X64F_SRW_RS },
    { "ntdll.dll",      "RtlAcquireSRWLockExclusive", X64F_SRW_AX },
    { "ntdll.dll",      "RtlQueryPerformanceCounter", X64F_QPC },
    { "kernelbase.dll", "TlsGetValue",                X64F_TLS },
    { "kernelbase.dll", "GetLastError",               X64F_LEGET },
    { "kernelbase.dll", "FlsGetValue",                X64F_FLS },
    { "kernel32.dll",   "TlsGetValue",                X64F_TLS },
    { "kernel32.dll",   "GetLastError",               X64F_LEGET },
    { "kernel32.dll",   "SetLastError",               X64F_LESET },
    { "kernel32.dll",   "FlsGetValue",                X64F_FLS },
    { "ucrtbase.dll",   "memcpy",                     X64F_MEMCPY },
    { "ucrtbase.dll",   "memmove",                    X64F_MEMCPY },
    { "ucrtbase.dll",   "memset",                     X64F_MEMSET },
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
        /* 1: x64 fast paths for critical sections, SRW locks, small memcpy/memmove/memset, TlsGetValue, FlsGetValue and Get/SetLastError (Sekiro: ~40% of the game thread was spent calling these) */
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
    /* madeira-doge: an in-pool image (img == pool_rx) has no second view and its
     * pool pages must never be mprotected -- the alias write below is the write. */
    int ok = img == pool_rx ? 1 : x64f_poke_image( img, rva, bytes, len );
    memcpy( pool_rw + rva, bytes, len );
    sys_icache_invalidate( pool_rx + rva, len );
    return ok;
}

/* ---- RtlQueryPerformanceCounter ---- */

/* FEX's rdtsc is CNTVCT_EL0 << TSCScale: SmallTSCScale (default on) doubles
 * CNTFRQ_EL0 until it reaches 1 GHz (FEXCore Core.cpp; hw_registry_ios.h). */
static unsigned int x64f_tsc_shift( void )
{
    unsigned long long f;
    unsigned int s = 0;
#if defined(__aarch64__)
    __asm__ __volatile__( "mrs %0, cntfrq_el0" : "=r"(f) );
#else
    f = 24000000;   /* host test */
#endif
    if (f && f < 1000000000ull) while (f < 1000000000ull) { f <<= 1; s++; }
    return s;
}

static unsigned int x64f_w( const unsigned char *img, unsigned int rva ) { return *(const unsigned int *)(img + rva); }

/* adrp Xd at rva: the page RVA it forms (0 when it is not adrp Xd). */
static unsigned int x64f_adrp( const unsigned char *img, unsigned int rva, unsigned int rd )
{
    unsigned int w = x64f_w( img, rva );
    int imm;
    if ((w & 0x9f00001fu) != (0x90000000u | rd)) return 0;
    imm = (int)(((w >> 29) & 3) | ((w >> 5) & 0x7ffff) << 2);
    if (imm & 0x100000) imm -= 0x200000;
    return (rva & ~0xfffu) + (unsigned int)(imm * 4096);
}

/* ldr Xt / ldrb Wt [Xn, #imm] at rva: its unsigned byte offset, or -1. */
static int x64f_ldr_off( const unsigned char *img, unsigned int rva, unsigned int rn, int byte )
{
    unsigned int w = x64f_w( img, rva );
    if ((w & 0xffc00000u) != (byte ? 0x39400000u : 0xf9400000u) || ((w >> 5) & 31) != rn) return -1;
    return (int)((w >> 10) & 0xfff) * (byte ? 1 : 8);
}

/* The four statics of Wine's iOS RtlQueryPerformanceCounter (dlls/ntdll/time.c
 * ml1117), read from its ARM64EC body at ec: qpc_disabled (byte), qpc_freq,
 * qpc_last_sync, qpc_offset. Only the instruction shape of the shipped
 * ntdll.dll is accepted; anything else leaves the export alone. */
static int x64f_qpc_statics( const unsigned char *img, size_t size, unsigned int ec, unsigned int v[4] )
{
    static const struct { unsigned int at, rd; int byte; } ld[4] =
        { { 0x10, 8, 1 }, { 0x28, 20, 0 }, { 0x48, 22, 0 }, { 0x6c, 9, 0 } };
    unsigned int i, ldat[4] = { 0x14, 0x2c, 0x50, 0x70 };
    if (!x64f_in( size, ec, 0x80 )) return 0;
    if (x64f_w( img, ec + 0x34 ) != 0xd53be009u ||   /* mrs x9, cntfrq_el0 */
        x64f_w( img, ec + 0x40 ) != 0xd5033fdfu ||   /* isb */
        x64f_w( img, ec + 0x44 ) != 0xd53be053u ||   /* mrs x19, cntvct_el0 */
        x64f_w( img, ec + 0x4c ) != 0x5292d015u ||   /* mov w21, #0x9680 */
        x64f_w( img, ec + 0x54 ) != 0x72a01315u)     /* movk w21, #0x98, lsl #16: TICKSPERSEC */
        return 0;
    for (i = 0; i < 4; i++)
    {
        unsigned int page = x64f_adrp( img, ec + ld[i].at, ld[i].rd );
        int off = x64f_ldr_off( img, ec + ldat[i], ld[i].rd, ld[i].byte );
        if (!page || off < 0) return 0;
        v[i] = page + (unsigned int)off;
        if (!x64f_in( size, v[i], 8 ) || (i && (v[i] & 7))) return 0;
    }
    return v[0] != v[1] && v[1] != v[2] && v[2] != v[3];
}

/* Point the copied stub at blob+at (RVA stub) to the statics. */
static void x64f_qpc_link( unsigned char *b, unsigned int stub, const unsigned int v[4], unsigned int shift )
{
    static const unsigned int end[4] = { X64F_QPC_DIS_END, X64F_QPC_FREQ_END, X64F_QPC_LAST_END, X64F_QPC_OFF_END };
    unsigned int i;
    for (i = 0; i < 4; i++)
    {
        int disp = (int)(v[i] - (stub + end[i]));
        memcpy( b + end[i] - (i ? 4 : 5), &disp, 4 );
    }
    b[X64F_QPC_SHIFT_END - 1] = (unsigned char)shift;
}

/* Modules that got stubs, for chasing a `jmp [rip+slot]` forwarder (kernel32's
 * QueryPerformanceCounter jumps through its own import slot to ntdll's entry). */
#define X64F_MAX_MODS 64
static struct { uintptr_t base; size_t size; } x64f_mods[X64F_MAX_MODS];
static int x64f_nmods;

static void x64f_patch_image( unsigned char *img, size_t size, unsigned char *pool_rw,
                              unsigned char *pool_rx, const char *mn )
{
    unsigned char blob[0x1000];
    unsigned int lo, hi, used = 0, i, n = 0, want = 0;
    struct { unsigned int entry, stub; } done[32];
    unsigned int qpc_v[4] = { 0, 0, 0, 0 }, qpc_shift = 0;

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

        if (x64f_targets[i].kind == X64F_QPC)
        {
            /* the stub reads ntdll's own statics; only the shipped body's layout is known */
            if (fall_len != 14 || !x64f_qpc_statics( img, size, e + 14 + *(const int *)(img + e + 10), qpc_v ))
            {
                dprintf( 2, "[x64-fast] %s: %s's ARM64EC body is not the known one, left alone\n", mn, x64f_targets[i].name );
                continue;
            }
            qpc_shift = x64f_tsc_shift();
        }
        need = (len + (x64f_stub[x64f_targets[i].kind].needs_fallback ? fall_len : 0) + 15) & ~15u;
        if (lo + used + need > hi || n >= 32) break;
        memcpy( blob + used, code, len );
        if (x64f_targets[i].kind == X64F_ENTER) memcpy( blob + used + X64F_SPIN_AT, &x64f_spin, 4 );
        if (x64f_targets[i].kind == X64F_QPC) x64f_qpc_link( blob + used, stub, qpc_v, qpc_shift );
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
    {
        int k = __atomic_load_n( &x64f_nmods, __ATOMIC_ACQUIRE );
        if (k < X64F_MAX_MODS)
        {
            x64f_mods[k].base = (uintptr_t)img;
            x64f_mods[k].size = size;
            __atomic_store_n( &x64f_nmods, k + 1, __ATOMIC_RELEASE );
        }
    }
    dprintf( 2, "[x64-fast] %s @%p: %u of %u x64 stubs placed (+0x%x, %u bytes, spin %d); x64 modules' import slots are pointed at them\n",
             mn, img, n, want, lo, used, x64f_spin );
    if (qpc_v[1])
        dprintf( 2, "[x64-fast] %s: QueryPerformanceCounter in x64 (statics +0x%x/+0x%x/+0x%x/+0x%x, tsc >> %u)\n",
                 mn, qpc_v[0], qpc_v[1], qpc_v[2], qpc_v[3], qpc_shift );
}

/* entry is a `jmp [rip+slot]` forwarder inside a module that got stubs, whose
 * slot holds a placed entry: that entry's stub (calling it is the same call). */
static uintptr_t x64f_stub_through_forwarder( uintptr_t entry )
{
    int i, n = __atomic_load_n( &x64f_nmods, __ATOMIC_ACQUIRE );
    for (i = 0; i < n; i++)
    {
        uintptr_t b = x64f_mods[i].base, slot;
        size_t sz = x64f_mods[i].size;
        const unsigned char *p = (const unsigned char *)entry;
        if (entry < b || entry - b > sz - 6 || p[0] != 0xff || p[1] != 0x25) continue;
        slot = entry + 6 + *(const int *)(p + 2);
        if (slot < b || slot - b > sz - 8) return 0;
        return x64f_stub_for( *(const uintptr_t *)slot );
    }
    return 0;
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
        if (!stub) stub = x64f_stub_through_forwarder( *(const uintptr_t *)(img + a) );
        if (!stub) continue;
        if (x64f_poke_image( img, (unsigned int)a, (const unsigned char *)&stub, 8 )) hits++;
        else fails++;
    }
    if (hits || fails)
        dprintf( 2, "[x64-fast] x64 image %p: %u import slot(s) now call x64 stubs%s\n", img, hits,
                 fails ? " (some image writes FAILED)" : "" );
}
