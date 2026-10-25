/* Native x86-64 check of the RtlQueryPerformanceCounter stub (stubs.asm qpc,
 * run by tests/host/check-x64fast.py). The host's rdtsc stands in for FEX's
 * (CNTVCT << TSCScale); the statics sit next to the code as ntdll's do. Every
 * path that must run Wine's code (disabled, no frequency, no sync yet, resync
 * due, counter behind the last sync) has to reach the fallback with the
 * caller's pointer, and the fast path must equal Wine's C formula (ml1117)
 * for the counter read during the call. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <x86intrin.h>
#include <asm/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

extern unsigned char qpcw[], qpcw_end[], qpcw_e_stub[], qpcw_e_data[], qpcw_e_iv[], qpcw_e_delay[];
static unsigned char qpcw_state[64];
extern unsigned char qpcx[], qpcx_end[], qpcx_e_base[], qpcx_e_shift[];
extern unsigned char qpc[], qpc_end[], qpc_e_dis[], qpc_e_freq[], qpc_e_last[], qpc_e_shift[], qpc_e_off[];
static long fallbacks; static void *fb_arg;
__attribute__((ms_abi)) static int fb(int64_t *c) { fallbacks++; fb_arg = c; *c = -7; return 1; }
typedef int (__attribute__((ms_abi)) *qpcfn)(int64_t *);

/* qpcw (the spin throttle): a fake clock and a fake NtDelayExecution */
static int64_t fake_now; static long delays, bad_delay;
__attribute__((ms_abi)) static int fake_qpc(int64_t *c) { *c = fake_now; return 1; }
__attribute__((ms_abi)) static int fake_delay(int alertable, const int64_t *iv) { delays++; if (alertable || *iv != -1000) bad_delay++; return 0; }
static unsigned char tebs[2][0x2000];
static void set_tid(int t) { *(uint64_t *)(tebs[t] + 0x48) = 0x100 + t; syscall(SYS_arch_prctl, ARCH_SET_GS, tebs[t]); }

static int check_qpcw(void)
{
    unsigned char *page = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    size_t n = qpcw_end - qpcw; int bad = 0;
    memcpy(page, qpcw, n);
    /* trampolines after the wrapper: jmp [rip+0] -> the fakes */
    void *t1 = (void *)fake_qpc, *t2 = (void *)fake_delay; unsigned char *j1 = page + 0x800, *j2 = page + 0x810;
    j1[0] = 0xff; j1[1] = 0x25; memset(j1 + 2, 0, 4); memcpy(j1 + 6, &t1, 8);
    j2[0] = 0xff; j2[1] = 0x25; memset(j2 + 2, 0, 4); memcpy(j2 + 6, &t2, 8);
    unsigned es = qpcw_e_stub - qpcw, ed = qpcw_e_delay - qpcw;
    int r1 = (int)(0x800 - es), r2 = (int)(0x810 - ed);
    memcpy(page + es - 4, &r1, 4); memcpy(page + ed - 4, &r2, 4);
    { uint64_t st = (uint64_t)(uintptr_t)qpcw_state; memcpy(page + (qpcw_e_data - qpcw) - 8, &st, 8); }
    mprotect(page, 0x800, PROT_READ | PROT_EXEC);   /* the code page is read-only on the device: the state must not be on it */
    qpcfn W = (qpcfn)page; int64_t v;
    struct { const char *what; int calls, step, other_every; long want; } c[] = {
        { "tight spin, 1000 calls", 1000, 1, 0, (992 - 256) / 16 + 1 },
        { "calls 1 us apart", 1000, 10, 0, 0 },
        { "tight spin with another thread every 40 calls", 1000, 1, 40, -1 },
        { "short burst of 200", 200, 1, 0, 0 },
    };
    for (unsigned k = 0; k < sizeof(c) / sizeof(c[0]); k++) {
        fake_now += 1000000; delays = 0;   /* > 1 ms after any earlier case: the first call takes over */
        int mine = 0;
        for (int i = 0; i < c[k].calls + mine; i++) {
            if (c[k].other_every && i % c[k].other_every == c[k].other_every - 1) { set_tid(1); fake_now++; W(&v); set_tid(0); continue; }
            set_tid(0); fake_now += c[k].step; if (W(&v) != 1 || v != fake_now) bad++;
        }
        long want = c[k].want;
        if (want < 0) want = delays >= 30 ? delays : 30;   /* the other thread must not stop the throttle */
        int ok = delays == want && !bad_delay;
        if (!ok) bad++;
        printf("qpcw %-46s sleeps %ld (want %ld) %s\n", c[k].what, delays, want, ok ? "ok" : "WRONG");
    }
    return bad;
}

struct statics { uint8_t dis; uint8_t pad[7]; uint64_t freq, last; int64_t off; };

static uint64_t ticks(uint64_t c, uint64_t f) { return (c / f) * 10000000ull + (c % f) * 10000000ull / f; }

/* variant 0: qpc (rip-relative statics); 1: qpca (absolute base + disp32) */
static int run_variant(int abs, int *pcases)
{
    unsigned char *page = mmap(NULL, 0x2000, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    unsigned char *code = qpc;
    size_t n = (size_t)(qpc_end - qpc);
    unsigned end[4] = { qpc_e_dis - qpc, qpc_e_freq - qpc, qpc_e_last - qpc, qpc_e_off - qpc };
    unsigned shift_at = (unsigned)(qpc_e_shift - qpc);
    struct statics *st = (struct statics *)(page + 0x1000);
    uintptr_t field[4] = { (uintptr_t)&st->dis, (uintptr_t)&st->freq, (uintptr_t)&st->last, (uintptr_t)&st->off };
    void *f = (void *)fb; int bad = 0, cases = 0;
    memcpy(page, code, n);
    (void)abs;
    for (int i = 0; i < 4; i++) { int d = (int)(field[i] - ((uintptr_t)page + end[i])); memcpy(page + end[i] - (i ? 4 : 5), &d, 4); }
    page[n] = 0xff; page[n + 1] = 0x25; memset(page + n + 2, 0, 4); memcpy(page + n + 6, &f, 8);
    qpcfn Q = (qpcfn)page;
    for (unsigned shift = 0; shift <= 6; shift += 6) {
        page[shift_at - 1] = (unsigned char)shift;
        uint64_t now = __rdtsc() >> shift, F = 24000000;
        struct { const char *what; uint8_t dis; uint64_t freq, last; int want_fb; } c[] = {
            { "disabled", 1, F, now, 1 }, { "no frequency", 0, 0, now, 1 }, { "no sync yet", 0, F, 0, 1 },
            { "resync due", 0, F, now - 10 * F, 1 }, { "counter behind the last sync", 0, F, now + 1000000000ull, 1 },
            { "fast path", 0, 1ull << 40, now, 0 }, { "fast path, 24 MHz", 0, F, 0, 0 },
        };
        for (unsigned k = 0; k < sizeof(c) / sizeof(c[0]); k++) {
            int64_t out = 0, offv = 123456789012ll; long before = fallbacks;
            st->dis = c[k].dis; st->freq = c[k].freq; st->off = offv;
            st->last = c[k].last ? c[k].last : (k == 6 ? (__rdtsc() >> shift) - 1000 : 0);
            uint64_t c0 = __rdtsc() >> shift; int r = Q(&out); uint64_t c1 = __rdtsc() >> shift;
            int took_fb = fallbacks != before; cases++;
            int ok = r == 1 && took_fb == c[k].want_fb;
            if (took_fb) ok = ok && fb_arg == &out && out == -7;
            else ok = ok && (uint64_t)(out - offv) >= ticks(c0, st->freq) && (uint64_t)(out - offv) <= ticks(c1, st->freq);
            if (!ok) { bad++; printf("FAIL %s shift %u %s: r=%d fallback=%d out=%lld\n", "qpc", shift, c[k].what, r, took_fb, (long long)out); }
        }
        /* monotonic over many fast calls at 24 MHz */
        st->dis = 0; st->freq = 24000000; st->last = (__rdtsc() >> shift) - 100; int64_t prev = 0; long fbs = fallbacks;
        for (int i = 0; i < 200000; i++) { int64_t v; Q(&v); if (v < prev) { bad++; break; } prev = v; }
        cases++;
        if (fallbacks - fbs > 200000 / 2) { printf("FAIL shift %u: the fast path was not taken (%ld fallbacks)\n", shift, fallbacks - fbs); bad++; }
    }
    *pcases += cases;
    return bad;
}

/* qpcx: the counter from its own state, no fallback, read-only code page */
static int run_qpcx(int *pcases)
{
    unsigned char *page = mmap(NULL, 0x1000, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    static uint64_t st[2];
    size_t n = qpcx_end - qpcx; int bad = 0;
    uint64_t base = (uint64_t)(uintptr_t)st;
    memcpy(page, qpcx, n);
    memcpy(page + (qpcx_e_base - qpcx) - 8, &base, 8);
    mprotect(page, 0x1000, PROT_READ | PROT_EXEC);
    qpcfn Q = (qpcfn)page;
    for (unsigned shift = 0; shift <= 6; shift += 6) {
        mprotect(page, 0x1000, PROT_READ | PROT_WRITE | PROT_EXEC);
        page[(qpcx_e_shift - qpcx) - 1] = (unsigned char)shift;
        mprotect(page, 0x1000, PROT_READ | PROT_EXEC);
        uint64_t F[2] = { 24000000, 1000000000 };
        for (int fi = 0; fi < 2; fi++) {
            st[0] = F[fi]; st[1] = 987654321;
            int64_t out = 0; uint64_t c0 = __rdtsc() >> shift; int r = Q(&out); uint64_t c1 = __rdtsc() >> shift;
            int ok = r == 1 && (uint64_t)(out - (int64_t)st[1]) >= ticks(c0, st[0]) && (uint64_t)(out - (int64_t)st[1]) <= ticks(c1, st[0]);
            int64_t prev = 0; for (int i = 0; i < 100000; i++) { int64_t v; Q(&v); if (v < prev) { ok = 0; break; } prev = v; }
            (*pcases)++;
            if (!ok) { bad++; printf("FAIL qpcx shift %u freq %llu: out=%lld\n", shift, (unsigned long long)F[fi], (long long)out); }
        }
    }
    return bad;
}

int main(void)
{
    int bad = 0, cases = 0;
    bad += run_variant(0, &cases);
    bad += run_qpcx(&cases);
    bad += check_qpcw(); cases += 4;
    printf("qpc: %d cases, %d bad -> %s\n", cases, bad, bad ? "FAIL" : "PASS");
    return !!bad;
}
