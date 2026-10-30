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
 * MH Rise (2026-10-20, build 282, QPC stub on): ucrtbase memset was then the
 * top crossing, and memcpy/memmove above 128 bytes followed. Fills and copies
 * of 129 bytes .. 32 KB now run `rep stosb` / `rep movsb`, which FEX turns into
 * its own unrolled loops inside the translated code. A copy whose destination
 * lies ahead of its source within the length (dst - src < n, unsigned) and
 * anything above 32 KB still goes to the native code.
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

#include <time.h>
#ifdef __APPLE__
#include <mach/mach_time.h>
#endif

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
/* GetCurrentThreadId / GetCurrentProcessId (TEB ClientId) and the pseudo
 * handles of GetCurrentThread / GetCurrentProcess (EXVS2 2v2, build 465:
 * kernel32 GetCurrentThreadId ~40k, GetCurrentThread ~10k crossings a second). */
static const unsigned char x64f_cur_tid[9] = {
    0x65, 0x8b, 0x04, 0x25, 0x48, 0x00, 0x00, 0x00, 0xc3
};
static const unsigned char x64f_cur_pid[9] = {
    0x65, 0x8b, 0x04, 0x25, 0x40, 0x00, 0x00, 0x00, 0xc3
};
static const unsigned char x64f_cur_thr[8] = {
    0x48, 0xc7, 0xc0, 0xfe, 0xff, 0xff, 0xff, 0xc3
};
static const unsigned char x64f_cur_proc[8] = {
    0x48, 0xc7, 0xc0, 0xff, 0xff, 0xff, 0xff, 0xc3
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
static const unsigned char x64f_mem_copy[356] = {
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
    0x88, 0x54, 0x01, 0xff, 0x44, 0x88, 0x1c, 0x11, 0xc3, 0x49, 0x81, 0xf8,
    0x00, 0x80, 0x00, 0x00, 0x77, 0x26, 0x48, 0x89, 0xc8, 0x48, 0x29, 0xd0,
    0x4c, 0x39, 0xc0, 0x72, 0x1b, 0x49, 0x89, 0xf9, 0x49, 0x89, 0xf2, 0x48,
    0x89, 0xcf, 0x48, 0x89, 0xd6, 0x48, 0x89, 0xc8, 0x4c, 0x89, 0xc1, 0xf3,
    0xa4, 0x4c, 0x89, 0xcf, 0x4c, 0x89, 0xd6, 0xc3,
};
static const unsigned char x64f_mem_set[229] = {
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
    0x88, 0x14, 0x09, 0xc3, 0x49, 0x81, 0xf8, 0x00, 0x80, 0x00, 0x00, 0x77,
    0x18, 0x49, 0x89, 0xf9, 0x49, 0x89, 0xca, 0x48, 0x89, 0xcf, 0x0f, 0xb6,
    0xc2, 0x4c, 0x89, 0xc1, 0xf3, 0xaa, 0x4c, 0x89, 0xcf, 0x4c, 0x89, 0xd0,
    0xc3,
};
#define X64F_SPIN_AT 57   /* offset of the spin count imm32 in x64f_cs_enter */
static const unsigned char x64f_qpc[103] = {
    0x80, 0x3d, 0x60, 0x00, 0x00, 0x00, 0x00, 0x75, 0x5e, 0x4c, 0x8b, 0x05, 0x5e, 0x00, 0x00, 0x00,
    0x4d, 0x85, 0xc0, 0x74, 0x52, 0x4c, 0x8b, 0x0d, 0x5a, 0x00, 0x00, 0x00, 0x4d, 0x85, 0xc9, 0x74,
    0x46, 0x0f, 0x31, 0x48, 0xc1, 0xe2, 0x20, 0x48, 0x09, 0xd0, 0x48, 0xc1, 0xe8, 0x06, 0x49, 0x89,
    0xc3, 0x4c, 0x29, 0xc8, 0x4c, 0x39, 0xc0, 0x73, 0x2e, 0x4c, 0x89, 0xd8, 0x31, 0xd2, 0x49, 0xf7,
    0xf0, 0x4c, 0x69, 0xd8, 0x80, 0x96, 0x98, 0x00, 0x48, 0x69, 0xc2, 0x80, 0x96, 0x98, 0x00, 0x31,
    0xd2, 0x49, 0xf7, 0xf0, 0x4c, 0x01, 0xd8, 0x48, 0x03, 0x05, 0x20, 0x00, 0x00, 0x00, 0x48, 0x89,
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

/* qpcx (stubs.asm): QueryPerformanceCounter from the stub's own state
 * (+0 counter frequency, +8 offset in 100 ns ticks), calibrated here the way
 * Wine's RtlQueryPerformanceCounter calibrates (CNTVCT_EL0 against the unix
 * monotonic counter) and refreshed by ios_x64f_qpc_refresh (raised only, by
 * more than 1 ms, like Wine's qpc_offset). Wine's own statics live in each
 * process's JIT-pool copy of ntdll: build 465 read the image's (never written),
 * 468 one pool copy's (the launcher's), and in the game every call fell back to
 * the EC body (260k crossings/s, logs 2026-10-25 12:58 and 14:07). Offsets: END
 * of the state imm64 and of the shift imm8. */
static const unsigned char x64f_qpcx[66] = {
    0x49, 0xba, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a, 0x0f, 0x31, 0x48, 0xc1, 0xe2, 0x20,
    0x48, 0x09, 0xd0, 0x48, 0xc1, 0xe8, 0x06, 0x4d, 0x8b, 0x02, 0x31, 0xd2, 0x49, 0xf7, 0xf0, 0x4c,
    0x69, 0xd8, 0x80, 0x96, 0x98, 0x00, 0x48, 0x69, 0xc2, 0x80, 0x96, 0x98, 0x00, 0x31, 0xd2, 0x49,
    0xf7, 0xf0, 0x4c, 0x01, 0xd8, 0x49, 0x03, 0x42, 0x08, 0x48, 0x89, 0x01, 0xb8, 0x01, 0x00, 0x00,
    0x00, 0xc3
};
#define X64F_QPCX_BASE_END  0x0a
#define X64F_QPCX_SHIFT_END 0x17

/* QueryPerformanceCounter spin throttle (stubs.asm qpcw; madeira.cfg
 * qpc-spin-sleep-us). EXVS2 (log 2026-10-25 09:53, build 458): one game thread
 * called QPC 300-600k times a second, 100% of the gaps < 1 us -- a busy-wait on
 * the clock holding a P-core at 100% while the SoC sat in its 1.26 GHz thermal
 * clamp. Placed after the qpc stub and its fallback and registered instead of
 * it: the followed thread, after 256 calls each < 1 us apart, sleeps the
 * interval on every 16th call; other threads are never delayed. Offsets: the
 * END of the call to the stub, of the interval imm32, of the call to
 * NtDelayExecution (each field is the 4 bytes before), and of the imm64 that
 * holds the address of the wrapper's 24-byte state. The state lives in host
 * heap memory (calloc), never next to the code: .hexpthk is read-only on the
 * device and build 462 died at the first write (log 2026-10-25 11:48). */
static const unsigned char x64f_qpcw[173] = {
    0x53, 0x48, 0x83, 0xec, 0x30, 0x48, 0x89, 0xcb, 0xe8, 0xf3, 0xff, 0xff, 0xff, 0x49, 0xb9, 0x5a,
    0x5a, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a, 0x5a, 0x48, 0x8b, 0x0b, 0x65, 0x8b, 0x14, 0x25, 0x48, 0x00,
    0x00, 0x00, 0x41, 0x3b, 0x51, 0x08, 0x74, 0x25, 0x49, 0x89, 0xc8, 0x4d, 0x2b, 0x01, 0x49, 0x81,
    0xf8, 0x10, 0x27, 0x00, 0x00, 0x72, 0x6b, 0x41, 0x89, 0x51, 0x08, 0x41, 0xc7, 0x41, 0x0c, 0x00,
    0x00, 0x00, 0x00, 0x41, 0xc6, 0x41, 0x10, 0x00, 0x49, 0x89, 0x09, 0xeb, 0x55, 0x49, 0x89, 0xc8,
    0x4d, 0x2b, 0x01, 0x49, 0x89, 0x09, 0x41, 0x80, 0x79, 0x10, 0x00, 0x41, 0xc6, 0x41, 0x10, 0x00,
    0x75, 0x06, 0x49, 0x83, 0xf8, 0x0a, 0x73, 0x32, 0x41, 0xff, 0x41, 0x0c, 0x41, 0x8b, 0x41, 0x0c,
    0x3d, 0x00, 0x01, 0x00, 0x00, 0x72, 0x2b, 0xa9, 0x0f, 0x00, 0x00, 0x00, 0x75, 0x24, 0x41, 0xc6,
    0x41, 0x10, 0x01, 0x48, 0xc7, 0x44, 0x24, 0x28, 0x18, 0xfc, 0xff, 0xff, 0x31, 0xc9, 0x48, 0x8d,
    0x54, 0x24, 0x28, 0xe8, 0x68, 0xff, 0xff, 0xff, 0xeb, 0x08, 0x41, 0xc7, 0x41, 0x0c, 0x00, 0x00,
    0x00, 0x00, 0xb8, 0x01, 0x00, 0x00, 0x00, 0x48, 0x83, 0xc4, 0x30, 0x5b, 0xc3
};
#define X64F_QPCW_STUB_END  0x0d
#define X64F_QPCW_DATA_END  0x17   /* imm64 (8 bytes before): the writable state */
#define X64F_QPCW_IV_END    0x8c
#define X64F_QPCW_DELAY_END 0x98
/* ntdll's x64 syscall stub shape: mov r10, rcx; mov eax, imm32; test byte [0x7ffe0308], 1 */
static const unsigned char x64f_sys_head[4] = { 0x4c, 0x8b, 0xd1, 0xb8 };
static const unsigned char x64f_sys_tail[8] = { 0xf6, 0x04, 0x25, 0x08, 0x03, 0xfe, 0x7f, 0x01 };


enum { X64F_ENTER, X64F_LEAVE, X64F_TRY, X64F_LESET, X64F_LEGET, X64F_TLS, X64F_FLS,
       X64F_SRW_AS, X64F_SRW_RS, X64F_SRW_AX, X64F_MEMCPY, X64F_MEMSET, X64F_QPC,
       X64F_CUR_TID, X64F_CUR_PID, X64F_CUR_THR, X64F_CUR_PROC };

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
    { x64f_cur_tid,  sizeof(x64f_cur_tid),  0 },
    { x64f_cur_pid,  sizeof(x64f_cur_pid),  0 },
    { x64f_cur_thr,  sizeof(x64f_cur_thr),  0 },
    { x64f_cur_proc, sizeof(x64f_cur_proc), 0 },
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
    { "kernelbase.dll", "GetCurrentThreadId",         X64F_CUR_TID },
    { "kernelbase.dll", "GetCurrentProcessId",        X64F_CUR_PID },
    { "kernelbase.dll", "GetCurrentThread",           X64F_CUR_THR },
    { "kernelbase.dll", "GetCurrentProcess",          X64F_CUR_PROC },
    { "kernel32.dll",   "GetCurrentThreadId",         X64F_CUR_TID },
    { "kernel32.dll",   "GetCurrentProcessId",        X64F_CUR_PID },
    { "kernel32.dll",   "GetCurrentThread",           X64F_CUR_THR },
    { "kernel32.dll",   "GetCurrentProcess",          X64F_CUR_PROC },
};

static int x64f_mode = -1, x64f_spin;
static long long x64f_qpcw_us;

/* entry -> stub pairs of every placed module copy (each pseudo-process maps its own) */
#define X64F_MAX_PAIRS 512
static struct { uintptr_t entry, stub; } x64f_pairs[X64F_MAX_PAIRS];
static int x64f_npairs;

static int x64f_is_stub( uintptr_t a )
{
    int i, n = __atomic_load_n( &x64f_npairs, __ATOMIC_ACQUIRE );
    for (i = 0; i < n; i++) if (x64f_pairs[i].stub == a) return 1;
    return 0;
}

static uintptr_t x64f_stub_for( uintptr_t entry )
{
    int i, n = __atomic_load_n( &x64f_npairs, __ATOMIC_ACQUIRE );
    uintptr_t pe = 0;
    for (i = 0; i < n; i++) if (x64f_pairs[i].entry == entry) return x64f_pairs[i].stub;
    /* madeira-doge: a slot can hold the entry's JIT-pool copy address (where the
     * copy executes) instead of its PE address; the stub is the same */
    if (ios_jit_pool_image_pc( entry, &pe ) && pe != entry)
        for (i = 0; i < n; i++) if (x64f_pairs[i].entry == pe) return x64f_pairs[i].stub;
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
        /* x64-fast = 1 only: a thread busy-waiting on QueryPerformanceCounter (256+ calls each < 1 us apart) sleeps this many us every 16th call (EXVS2: one thread spun 300-600k calls/s); 0 = off */
        x64f_qpcw_us = madeira_cfg_int( "qpc-spin-sleep-us", 100 );
        if (x64f_qpcw_us < 0) x64f_qpcw_us = 0;
        if (x64f_qpcw_us > 2000) x64f_qpcw_us = 2000;
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

/* qpcx state: calibration (and the refresh the xprobe loop calls) */
#define X64F_MAX_QPCX 16
static uint64_t *x64f_qpcx_state[X64F_MAX_QPCX];
static int x64f_nqpcx;

static uint64_t x64f_cntvct( void )
{
#if defined(__aarch64__)
    uint64_t v;
    __asm__ __volatile__( "isb\n\tmrs %0, cntvct_el0" : "=r"(v) :: "memory" );
    return v;
#else
    unsigned int lo, hi;   /* host test: the TSC the stub reads */
    __asm__ __volatile__( "rdtsc" : "=a"(lo), "=d"(hi) );
    return (((uint64_t)hi << 32) | lo) >> 6;
#endif
}

static uint64_t x64f_cntfrq( void )
{
#if defined(__aarch64__)
    uint64_t f;
    __asm__ __volatile__( "mrs %0, cntfrq_el0" : "=r"(f) );
    return f;
#else
    return 24000000;   /* host test: tsc >> 6 counts at ~24-50 MHz; only consistency matters there */
#endif
}

/* Wine's unix monotonic_counter (dlls/ntdll/unix/sync.c), 100 ns units */
static uint64_t x64f_mono( void )
{
#ifdef __APPLE__
    static mach_timebase_info_data_t tb;
    if (!tb.denom) mach_timebase_info( &tb );
    return mach_continuous_time() * tb.numer / tb.denom / 100;
#else
    struct timespec ts;
    clock_gettime( CLOCK_MONOTONIC, &ts );
    return (uint64_t)ts.tv_sec * 10000000ull + (uint64_t)ts.tv_nsec / 100;
#endif
}

static void x64f_qpcx_calibrate( uint64_t *st, int raise_only )
{
    uint64_t f = x64f_cntfrq(), c0, c1, m, c, ticks;
    int64_t off;
    if (!f) return;
    c0 = x64f_cntvct(); m = x64f_mono(); c1 = x64f_cntvct();
    c = c0 + (c1 - c0) / 2;
    ticks = (c / f) * 10000000ull + (c % f) * 10000000ull / f;
    off = (int64_t)(m - ticks);
    if (!raise_only || off > (int64_t)st[1] + 10000) st[1] = (uint64_t)off;
    st[0] = f;
}

/* called from the xprobe loop (server_ios.c) */
void ios_x64f_qpc_refresh( void )
{
    int i, n = __atomic_load_n( &x64f_nqpcx, __ATOMIC_ACQUIRE );
    for (i = 0; i < n; i++) x64f_qpcx_calibrate( x64f_qpcx_state[i], 1 );
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
    char placed[512] = "";   /* madeira-doge: names of the placed stubs, for the log */
    unsigned int qpc_v[4] = { 0, 0, 0, 0 }, qpc_shift = 0;
    unsigned int qpcw_at = 0;
    int qpc_abs = 0;

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
        /* QPC: ntdll's ARM64EC code runs from per-process JIT-pool copies unless
         * the image IS the pool (in-pool images); then the stub keeps its own
         * calibrated state (qpcx) instead of reading Wine's statics */
        int qabs = x64f_targets[i].kind == X64F_QPC && pool_rx && pool_rx != img;
        unsigned int e = 0, stub = lo + used, fb, need;
        unsigned char fall[16];
        unsigned int fall_len = 0;
        int rel;

        if (qabs) { code = x64f_qpcx; len = sizeof(x64f_qpcx); }
        fb = stub + len;

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
        if (x64f_targets[i].kind == X64F_QPC && !qabs) x64f_qpc_link( blob + used, stub, qpc_v, qpc_shift );
        if (qabs)
        {
            uint64_t *st = calloc( 2, sizeof(uint64_t) ), base = (uint64_t)(uintptr_t)st;
            int k = __atomic_load_n( &x64f_nqpcx, __ATOMIC_ACQUIRE );
            if (!st || k >= X64F_MAX_QPCX) { free( st ); dprintf( 2, "[x64-fast] %s: no QPC state, QueryPerformanceCounter left native\n", mn ); continue; }
            x64f_qpcx_calibrate( st, 0 );
            memcpy( blob + used + X64F_QPCX_BASE_END - 8, &base, 8 );
            blob[used + X64F_QPCX_SHIFT_END - 1] = (unsigned char)qpc_shift;
            x64f_qpcx_state[k] = st;
            __atomic_store_n( &x64f_nqpcx, k + 1, __ATOMIC_RELEASE );
            qpc_abs = 1;
        }
        if (x64f_stub[x64f_targets[i].kind].needs_fallback) memcpy( blob + used + len, fall, fall_len );
        done[n].entry = e;
        done[n].stub = stub;
        if (x64f_targets[i].kind == X64F_QPC && x64f_qpcw_us > 0)
        {
            /* the spin throttle goes after the stub and is what x64 callers reach */
            unsigned int delay = x64f_export( img, size, "NtDelayExecution" ), w = lo + used + need;
            if (delay && x64f_in( size, delay, 16 ) && !memcmp( img + delay, x64f_sys_head, 4 ) &&
                !memcmp( img + delay + 8, x64f_sys_tail, 8 ) && w + sizeof(x64f_qpcw) <= hi)
            {
                unsigned char *q = blob + used + need;
                int iv = -(int)(x64f_qpcw_us * 10), r1 = (int)(stub - (w + X64F_QPCW_STUB_END)),
                    r2 = (int)(delay - (w + X64F_QPCW_DELAY_END));
                uint64_t state = (uint64_t)(uintptr_t)calloc( 1, 64 );   /* writable; lives as long as the image */
                if (!state) { dprintf( 2, "[x64-fast] %s: QPC spin throttle left out (no memory for its state)\n", mn ); goto qpcw_skip; }
                memcpy( q, x64f_qpcw, sizeof(x64f_qpcw) );
                memcpy( q + X64F_QPCW_DATA_END - 8, &state, 8 );
                memcpy( q + X64F_QPCW_STUB_END - 4, &r1, 4 );
                memcpy( q + X64F_QPCW_IV_END - 4, &iv, 4 );
                memcpy( q + X64F_QPCW_DELAY_END - 4, &r2, 4 );
                done[n].stub = w;
                need += (sizeof(x64f_qpcw) + 15) & ~15u;
                qpcw_at = w;
            }
            else dprintf( 2, "[x64-fast] %s: QPC spin throttle left out (NtDelayExecution stub not the known shape or no room)\n", mn );
        }
    qpcw_skip:
        if (strlen( placed ) + strlen( x64f_targets[i].name ) + 2 < sizeof(placed))
        { if (placed[0]) strcat( placed, "," ); strcat( placed, x64f_targets[i].name ); }
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
    dprintf( 2, "[x64-fast] %s @%p: placed %s\n", mn, img, placed );
    if (qpc_v[1])
        dprintf( 2, "[x64-fast] %s: QueryPerformanceCounter in x64 (statics +0x%x/+0x%x/+0x%x/+0x%x %s, tsc >> %u)\n",
                 mn, qpc_v[0], qpc_v[1], qpc_v[2], qpc_v[3], qpc_abs ? "not read: own calibrated state" : "in the image", qpc_shift );
    if (qpcw_at)
        dprintf( 2, "[x64-fast] %s: QPC spin throttle at +0x%x: a thread past 256 calls < 1 us apart sleeps %lld us every 16th call\n",
                 mn, qpcw_at, x64f_qpcw_us );
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
/* madeira-doge x64-fast rescan: x64 images whose import slots were looked at.
 * A protected executable can fill its import table itself after the IAT sync
 * (FF15's ffxv_s.exe: slots 0x143066448/50 held ntdll!RtlEnter/LeaveCritical-
 * Section, not the stubs, at ~1-3 M calls/s), so ios_x64f_rescan() looks again. */
#define X64F_MAX_X64IMG 96
static struct { unsigned char *img; size_t size; unsigned int scans; } x64f_x64img[X64F_MAX_X64IMG];
static int x64f_nx64img;
static int x64f_rescanning;

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
    if (!x64f_rescanning)
    {
        int k, n = __atomic_load_n( &x64f_nx64img, __ATOMIC_ACQUIRE );
        for (k = 0; k < n; k++) if (x64f_x64img[k].img == img) break;
        if (k == n && n < X64F_MAX_X64IMG)
        {
            x64f_x64img[n].img = img;
            x64f_x64img[n].size = size;
            __atomic_store_n( &x64f_nx64img, n + 1, __ATOMIC_RELEASE );
        }
    }
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

/* madeira-doge: the import descriptors' FirstThunk arrays, which a protected
 * executable can keep outside its IAT data directory (FF15's ffxv_s.exe: the
 * critical-section slots at rva 0x3066448/50 were never in it, so neither the
 * IAT sync nor a rescan of that directory reached them). Only 8-byte slots that
 * hold a placed entry change, as in x64f_redirect_iat. */
static void x64f_redirect_thunks( unsigned char *img, size_t size )
{
    unsigned int pe, imp, imp_size, d, hits = 0, fails = 0;

    if (!x64f_mode || !__atomic_load_n( &x64f_npairs, __ATOMIC_ACQUIRE )) return;
    if (size < 0x200 || img[0] != 'M' || img[1] != 'Z') return;
    pe = *(const unsigned int *)(img + 0x3c);
    if (!x64f_in( size, pe, 24 + 112 + 8 * 13 ) || memcmp( img + pe, "PE\0\0", 4 ) ||
        *(const unsigned short *)(img + pe + 4) != 0x8664 ||
        *(const unsigned short *)(img + pe + 24) != 0x20b) return;
    imp = *(const unsigned int *)(img + pe + 24 + 112 + 8 * 1);
    imp_size = *(const unsigned int *)(img + pe + 24 + 112 + 8 * 1 + 4);
    if (!imp || !x64f_in( size, imp, 20 )) return;
    for (d = imp; x64f_in( size, d, 20 ) && (!imp_size || d + 20 <= imp + imp_size); d += 20)
    {
        unsigned int name = *(const unsigned int *)(img + d + 12), ft = *(const unsigned int *)(img + d + 16), t;
        if (!name && !ft) break;
        if (!ft || (ft & 7)) continue;
        for (t = ft; x64f_in( size, t, 8 ) && t < ft + 0x10000; t += 8)
        {
            uintptr_t v = *(const uintptr_t *)(img + t), stub;
            if (!v) break;
            if (!(stub = x64f_stub_for( v ))) stub = x64f_stub_through_forwarder( v );
            if (!stub)
            {   /* madeira-doge: a slot into a stubbed module that has no stub (shown once each, 16 at most) */
                static int shown;
                int mi, nm = __atomic_load_n( &x64f_nmods, __ATOMIC_ACQUIRE );
                uintptr_t pe = v;
                ios_jit_pool_image_pc( v, &pe );
                for (mi = 0; mi < nm; mi++)
                    if (pe >= x64f_mods[mi].base && pe - x64f_mods[mi].base < x64f_mods[mi].size) break;
                if (mi < nm && shown < 16 && !x64f_is_stub( v ))
                {
                    shown++;
                    dprintf( 2, "[x64-fast] x64 image %p slot rva 0x%x holds %#lx (module %#lx +0x%lx): no stub for it\n",
                             img, t, (unsigned long)v, (unsigned long)x64f_mods[mi].base, (unsigned long)(pe - x64f_mods[mi].base) );
                }
                continue;
            }
            if (x64f_poke_image( img, t, (const unsigned char *)&stub, 8 )) hits++;
            else fails++;
        }
    }
    if (hits || fails)
        dprintf( 2, "[x64-fast] x64 image %p: %u import-descriptor slot(s) now call x64 stubs%s\n", img, hits,
                 fails ? " (some image writes FAILED)" : "" );
}

/* madeira-doge: a protected executable can keep the pointers it calls through
 * in neither its IAT directory nor its import descriptors (FF15's ffxv_s.exe:
 * rva 0x3066448/50, `call [rip+...]`, holding ntdll!RtlLeave/EnterCritical-
 * Section). Its non-executable sections are searched for 8-byte words equal to
 * a placed entry; only such exact values change. Run a few times per image
 * (see ios_x64f_rescan), never on images with a .hexpthk (hybrid). */
static void x64f_redirect_data( unsigned char *img, size_t size )
{
    unsigned int pe, sec, i, hits = 0, fails = 0;
    unsigned short nsec, opt;
    int mi, nm = __atomic_load_n( &x64f_nmods, __ATOMIC_ACQUIRE );

    if (!x64f_mode || !__atomic_load_n( &x64f_npairs, __ATOMIC_ACQUIRE ) || !nm) return;
    if (size < 0x200 || img[0] != 'M' || img[1] != 'Z') return;
    pe = *(const unsigned int *)(img + 0x3c);
    if (!x64f_in( size, pe, 24 + 112 + 8 * 13 ) || memcmp( img + pe, "PE\0\0", 4 ) ||
        *(const unsigned short *)(img + pe + 4) != 0x8664) return;
    nsec = *(const unsigned short *)(img + pe + 6);
    opt = *(const unsigned short *)(img + pe + 20);
    sec = pe + 24 + opt;
    if (!x64f_in( size, sec, nsec * 40u )) return;
    for (i = 0; i < nsec; i++)
        if (!memcmp( img + sec + 40 * i, ".hexpthk", 8 )) return;
    for (i = 0; i < nsec; i++)
    {
        const unsigned char *h = img + sec + 40 * i;
        unsigned int vsize = *(const unsigned int *)(h + 8), va = *(const unsigned int *)(h + 12);
        unsigned int chars = *(const unsigned int *)(h + 36), t, end;
        if (chars & 0x20000000) continue;            /* IMAGE_SCN_MEM_EXECUTE */
        if (!(chars & 0x40000000)) continue;         /* not readable */
        if (!vsize || !x64f_in( size, va, vsize )) continue;
        end = (va + vsize) & ~7u;
        for (t = (va + 7) & ~7u; t + 8 <= end; t += 8)
        {
            uintptr_t v = *(const uintptr_t *)(img + t), stub;
            /* cheap filter: only values inside a module that got stubs */
            for (mi = 0; mi < nm; mi++)
                if (v - x64f_mods[mi].base < x64f_mods[mi].size) break;
            if (mi == nm) continue;
            if (!(stub = x64f_stub_for( v ))) continue;
            if (x64f_poke_image( img, t, (const unsigned char *)&stub, 8 )) hits++;
            else fails++;
        }
    }
    if (hits || fails)
        dprintf( 2, "[x64-fast] x64 image %p: %u data pointer(s) to placed entries now call x64 stubs%s\n", img, hits,
                 fails ? " (some image writes FAILED)" : "" );
}

/* madeira-doge x64-fast rescan (see x64f_x64img): every x64 image's whole import
 * table again, at most every 3 s. A slot that already holds a stub is left as
 * it is, so this only changes slots the program filled in after the IAT sync.
 * env.MADEIRA_X64F_RESCAN = 0 turns it off. */
void ios_x64f_rescan( void )
{
    static int enabled = -1;
    static uint64_t last;
    uint64_t now = mach_absolute_time();
    int k, n;

    if (enabled < 0) { const char *e = getenv( "MADEIRA_X64F_RESCAN" ); enabled = !(e && e[0] == '0'); }
    if (!enabled || x64f_mode != 1) return;
    if (last && now - last < 3ull * 24000000ull) return;   /* 24 MHz timebase on Apple silicon */
    last = now;
    n = __atomic_load_n( &x64f_nx64img, __ATOMIC_ACQUIRE );
    x64f_rescanning = 1;
    for (k = 0; k < n; k++)
    {
        unsigned char hdr[2];
        mach_vm_size_t got = 0;
        unsigned char *img = x64f_x64img[k].img;
        /* an image that was unloaded since: its header no longer reads as MZ */
        if (mach_vm_read_overwrite( mach_task_self(), (mach_vm_address_t)(uintptr_t)img, 2,
                                    (mach_vm_address_t)(uintptr_t)hdr, &got ) != KERN_SUCCESS ||
            got != 2 || hdr[0] != 'M' || hdr[1] != 'Z')
            continue;
        x64f_redirect_iat( img, x64f_x64img[k].size, 0, x64f_x64img[k].size );
        x64f_redirect_thunks( img, x64f_x64img[k].size );
        {   /* the data search costs a pass over the image's data: rescans 2, 5, 10, 20 and 40 only (~6 s .. 2 min) */
            unsigned int sc = ++x64f_x64img[k].scans;
            if (sc == 2 || sc == 5 || sc == 10 || sc == 20 || sc == 40) x64f_redirect_data( img, x64f_x64img[k].size );
        }
    }
    x64f_rescanning = 0;
}

