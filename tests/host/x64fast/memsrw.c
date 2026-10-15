/* Native x86-64 check of the memcpy/memmove/memset and SRW lock stubs in
 * tests/host/x64fast/stubs.asm (run by tests/host/check-x64fast.py).
 * mem: every size 0..200 at many offsets, overlapping both ways, against
 * libc memmove/memset; the >128 cases must reach the fallback.
 * SRW: Wine's C code (dlls/ntdll/sync.c, waits as futexes) is the fallback;
 * threads mix stub and C paths on one lock and check mutual exclusion. */
#define _GNU_SOURCE
#include <linux/futex.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

extern unsigned char mem_copy[], mem_copy_end[], mem_set[], mem_set_end[];
extern unsigned char srw_as[], srw_as_end[], srw_rs[], srw_rs_end[], srw_ax[], srw_ax_end[];

static unsigned char *code; static size_t used;
static void *install(unsigned char *s, unsigned char *e, void *fallback)
{
    size_t n = e - s; unsigned char *p = code + used;
    memcpy(p, s, n);
    p[n] = 0xff; p[n + 1] = 0x25; memset(p + n + 2, 0, 4); memcpy(p + n + 6, &fallback, 8);
    used += (n + 14 + 15) & ~15;
    return p;
}

/* ---- mem ---- */
static long copy_fallbacks, set_fallbacks;
__attribute__((ms_abi)) static void *fb_copy(void *d, const void *s, size_t n) { copy_fallbacks++; return memmove(d, s, n); }
__attribute__((ms_abi)) static void *fb_set(void *d, int c, size_t n) { set_fallbacks++; return memset(d, c, n); }
typedef void *(__attribute__((ms_abi)) *copyfn)(void *, const void *, size_t);
typedef void *(__attribute__((ms_abi)) *setfn)(void *, int, size_t);

static int check_mem(copyfn C, setfn S)
{
    static unsigned char a[1024], b[1024];
    int bad = 0; long cases = 0, big = 0;
    for (size_t n = 0; n <= 200; n++)
        for (int doff = 0; doff < 40; doff += 3)
            for (int soff = 0; soff < 40; soff += 5)
            {
                /* separate buffers */
                for (int i = 0; i < 1024; i++) { a[i] = rand(); b[i] = a[i]; }
                unsigned char src[300]; for (int i = 0; i < 300; i++) src[i] = rand();
                if (C(a + 100 + doff, src + soff, n) != a + 100 + doff) bad++;
                memmove(b + 100 + doff, src + soff, n);
                if (memcmp(a, b, 1024)) bad++;
                /* overlapping, both directions */
                for (int i = 0; i < 1024; i++) { a[i] = rand(); b[i] = a[i]; }
                C(a + 200 + doff, a + 200 + soff, n); memmove(b + 200 + doff, b + 200 + soff, n);
                if (memcmp(a, b, 1024)) bad++;
                /* memset */
                for (int i = 0; i < 1024; i++) { a[i] = rand(); b[i] = a[i]; }
                int c = rand() | 0x1200;   /* only the low byte counts */
                if (S(a + 300 + doff, c, n) != a + 300 + doff) bad++;
                memset(b + 300 + doff, c, n);
                if (memcmp(a, b, 1024)) bad++;
                cases++; if (n > 128) big++;
            }
    printf("mem: %ld cases, %d mismatches; fallbacks copy=%ld set=%ld (want %ld and %ld) -> %s\n",
           cases, bad, copy_fallbacks, set_fallbacks, big * 2, big,
           !bad && copy_fallbacks == big * 2 && set_fallbacks == big ? "PASS" : "FAIL");
    return !bad && copy_fallbacks == big * 2 && set_fallbacks == big;
}

/* ---- SRW: Wine's code, RtlWaitOnAddress/Wake as futexes ---- */
struct srw { volatile short exclusive_waiters; volatile unsigned short owners; };
union u32 { struct srw s; int l; };
static void wait_on(volatile void *addr, const void *cmp, int size)
{
    /* futex on the containing aligned word, re-checked against the compare value */
    volatile int *w = (volatile int *)((uintptr_t)addr & ~3);
    int cur = *w;
    if (size == 2 ? *(volatile short *)addr != *(const short *)cmp : *(volatile int *)addr != *(const int *)cmp) return;
    syscall(SYS_futex, w, FUTEX_WAIT_PRIVATE, cur, NULL, NULL, 0);
}
static void wake_all(volatile void *addr) { syscall(SYS_futex, (int *)((uintptr_t)addr & ~3), FUTEX_WAKE_PRIVATE, 1 << 30, NULL, NULL, 0); }
static long slow_as, slow_rs, slow_ax;
__attribute__((ms_abi)) static void c_ax(struct srw *l)
{
    __sync_add_and_fetch(&slow_ax, 1);
    __sync_fetch_and_add(&l->exclusive_waiters, 2);
    for (;;) {
        union u32 o, n; int wait;
        do { o.l = *(volatile int *)l; n = o; if (!o.s.owners) { n.s.owners = 1; n.s.exclusive_waiters -= 2; n.s.exclusive_waiters |= 1; wait = 0; } else wait = 1; }
        while (__sync_val_compare_and_swap((int *)l, o.l, n.l) != o.l);
        if (!wait) return;
        wait_on(&l->owners, &n.s.owners, 2);
    }
}
__attribute__((ms_abi)) static void c_as(struct srw *l)
{
    __sync_add_and_fetch(&slow_as, 1);
    for (;;) {
        union u32 o, n; int wait;
        do { o.l = *(volatile int *)l; n = o; if (!o.s.exclusive_waiters) { n.s.owners++; wait = 0; } else wait = 1; }
        while (__sync_val_compare_and_swap((int *)l, o.l, n.l) != o.l);
        if (!wait) return;
        wait_on(l, &n.l, 4);
    }
}
static void c_rx(struct srw *l)
{
    union u32 o, n;
    do { o.l = *(volatile int *)l; n = o; if (!(o.s.exclusive_waiters & 1)) abort(); n.s.owners = 0; n.s.exclusive_waiters &= ~1; }
    while (__sync_val_compare_and_swap((int *)l, o.l, n.l) != o.l);
    wake_all(l);   /* Wine wakes one exclusive or all shared; waking all is a superset */
}
__attribute__((ms_abi)) static void c_rs(struct srw *l)
{
    union u32 o, n;
    __sync_add_and_fetch(&slow_rs, 1);
    do { o.l = *(volatile int *)l; n = o; if ((o.s.exclusive_waiters & 1) || !o.s.owners) abort(); n.s.owners--; }
    while (__sync_val_compare_and_swap((int *)l, o.l, n.l) != o.l);
    if (!n.s.owners) wake_all(l);
}
typedef void (__attribute__((ms_abi)) *srwfn)(struct srw *);
static srwfn AS, RS, AX;
static struct srw lock; static volatile int writers, readers; static volatile long total; static long iters = 300000;
static void *srw_worker(void *arg)
{
    unsigned seed = (unsigned)(uintptr_t)arg;
    for (long k = 0; k < iters; k++) {
        int r = rand_r(&seed) % 8;
        if (r == 0) {   /* exclusive */
            AX(&lock);
            if (__sync_add_and_fetch(&writers, 1) != 1 || readers) abort();
            total++;
            __sync_sub_and_fetch(&writers, 1);
            c_rx(&lock);
        } else {        /* shared, stub or C */
            if (r & 1) AS(&lock); else c_as(&lock);
            __sync_add_and_fetch(&readers, 1);
            if (writers) abort();
            __sync_sub_and_fetch(&readers, 1);
            if (r & 2) RS(&lock); else c_rs(&lock);
        }
    }
    return NULL;
}

int main(int argc, char **argv)
{
    code = mmap(NULL, 1 << 16, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    copyfn C = install(mem_copy, mem_copy_end, fb_copy);
    setfn S = install(mem_set, mem_set_end, fb_set);
    AS = install(srw_as, srw_as_end, c_as);
    RS = install(srw_rs, srw_rs_end, c_rs);
    AX = install(srw_ax, srw_ax_end, c_ax);
    int ok = check_mem(C, S);
    if (getenv("ITERS")) iters = atol(getenv("ITERS"));
    int nt = argc > 1 ? atoi(argv[1]) : 6;
    pthread_t th[32];
    for (int i = 0; i < nt; i++) pthread_create(&th[i], NULL, srw_worker, (void *)(uintptr_t)(i * 7919 + 1));
    for (int i = 0; i < nt; i++) pthread_join(th[i], NULL);
    long ex = 0; /* exclusive count is random; check the lock ended free */
    (void)ex;
    int srw_ok = *(volatile int *)&lock == 0 && !writers && !readers;
    printf("srw: threads=%d lock=%08x exclusive sections=%ld slow as/rs/ax=%ld/%ld/%ld -> %s\n",
           nt, *(volatile int *)&lock, total, slow_as, slow_rs, slow_ax, srw_ok ? "PASS" : "FAIL");
    return !(ok && srw_ok);
}
