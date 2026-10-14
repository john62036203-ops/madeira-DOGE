/* Native x86-64 stress test of tests/host/x64fast/stubs.asm (run by
 * tests/host/check-x64fast.py): each thread gets a fake TEB in gs, the
 * fallbacks are Wine's C critical-section code. */
#define _GNU_SOURCE
#include <asm/prctl.h>
#include <pthread.h>
#include <semaphore.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

typedef struct { void *DebugInfo; volatile int LockCount; volatile int RecursionCount;
                 void * volatile OwningThread; void *LockSemaphore; uintptr_t SpinCount; } CS;

extern unsigned char cs_enter[], cs_enter_end[], cs_leave[], cs_leave_end[], cs_try[], cs_try_end[];
extern unsigned char le_set[], le_set_end[], le_get[], le_get_end[], tls_get[], tls_get_end[], fls_get[], fls_get_end[];

static unsigned char *teb_of(void) { unsigned char *t; __asm__ volatile("mov %%gs:0x30, %0" : "=r"(t)); return t; }
static void *tid(void) { return *(void **)(teb_of() + 0x48); }

/* Wine's originals (dlls/ntdll/sync.c), with a POSIX semaphore as LockSemaphore. */
static long slow_enter_n, slow_leave_n, slow_tls_n, slow_fls_n;
__attribute__((ms_abi)) static int real_try(CS *c)
{
    if (__sync_val_compare_and_swap(&c->LockCount, -1, 0) == -1) { c->OwningThread = tid(); c->RecursionCount = 1; return 1; }
    if (c->OwningThread == tid()) { __sync_add_and_fetch(&c->LockCount, 1); c->RecursionCount++; return 1; }
    return 0;
}
__attribute__((ms_abi)) static int real_enter(CS *c)
{
    __sync_add_and_fetch(&slow_enter_n, 1);
    if (__sync_add_and_fetch(&c->LockCount, 1))
    {
        if (c->OwningThread == tid()) { c->RecursionCount++; return 0; }
        sem_wait((sem_t *)c->LockSemaphore);
    }
    c->OwningThread = tid(); c->RecursionCount = 1;
    return 0;
}
__attribute__((ms_abi)) static int real_leave(CS *c)
{
    __sync_add_and_fetch(&slow_leave_n, 1);
    if (--c->RecursionCount) { if (c->RecursionCount > 0) __sync_sub_and_fetch(&c->LockCount, 1); else { fprintf(stderr, "not acquired\n"); abort(); } }
    else { c->OwningThread = 0; if (__sync_sub_and_fetch(&c->LockCount, 1) >= 0) sem_post((sem_t *)c->LockSemaphore); }
    return 0;
}
__attribute__((ms_abi)) static void *real_tls(unsigned idx) { __sync_add_and_fetch(&slow_tls_n, 1); *(int *)(teb_of() + 0x68) = 0; return (void *)0x7777; }
__attribute__((ms_abi)) static void *real_fls(unsigned idx) { __sync_add_and_fetch(&slow_fls_n, 1); *(int *)(teb_of() + 0x68) = 0; return (void *)0x8888; }

static unsigned char *code; static size_t used;
static void *install(unsigned char *s, unsigned char *e, void *fallback, unsigned spin)
{
    size_t n = e - s; unsigned char *p = code + used;
    memcpy(p, s, n);
    if (spin != ~0u) { unsigned char *m = memmem(p, n, "\x5a\x5a\x5a\x5a", 4); if (!m) abort(); memcpy(m, &spin, 4); }
    if (fallback) { p[n] = 0xff; p[n + 1] = 0x25; memset(p + n + 2, 0, 4); memcpy(p + n + 6, &fallback, 8); n += 14; }
    used += (n + 15) & ~15;
    return p;
}

typedef int (__attribute__((ms_abi)) *csfn)(CS *);
typedef void (__attribute__((ms_abi)) *setfn)(unsigned);
typedef unsigned (__attribute__((ms_abi)) *getfn)(void);
typedef void *(__attribute__((ms_abi)) *idxfn)(unsigned);
static csfn E, L, T; static setfn SLE; static getfn GLE; static idxfn TLS, FLS;

static CS cs; static volatile long counter; static long iters = 2000000;
static void setup_teb(int i)
{
    unsigned char *teb = calloc(1, 0x2000);
    *(void **)(teb + 0x30) = teb; *(uintptr_t *)(teb + 0x48) = 0x100 + 4 * i;
    if (syscall(SYS_arch_prctl, ARCH_SET_GS, teb)) { perror("arch_prctl"); exit(1); }
}
static void *worker(void *arg)
{
    int i = (int)(intptr_t)arg; long k;
    setup_teb(i);
    for (k = 0; k < iters; k++)
    {
        int r = (k % 7 == 0) ? !T(&cs) : E(&cs);
        if (r) { if (k % 7 == 0) { k--; continue; } abort(); }
        if (cs.OwningThread != tid() || cs.RecursionCount != 1) { fprintf(stderr, "bad own\n"); abort(); }
        long v = counter; if (k % 5 == 0) { E(&cs); counter = v + 1; L(&cs); } else counter = v + 1;
        if (k % 11 == 0) { if (!T(&cs)) abort(); L(&cs); }
        L(&cs);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    if (getenv("ITERS")) iters = atol(getenv("ITERS"));
    int nthreads = argc > 1 ? atoi(argv[1]) : 6; unsigned spin = argc > 2 ? atoi(argv[2]) : 0;
    code = mmap(NULL, 1 << 16, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
    E = install(cs_enter, cs_enter_end, real_enter, spin);
    L = install(cs_leave, cs_leave_end, real_leave, ~0u);
    T = install(cs_try, cs_try_end, NULL, ~0u);
    SLE = install(le_set, le_set_end, NULL, ~0u); GLE = install(le_get, le_get_end, NULL, ~0u);
    TLS = install(tls_get, tls_get_end, real_tls, ~0u); FLS = install(fls_get, fls_get_end, real_fls, ~0u);

    /* single-thread unit checks */
    setup_teb(0);
    unsigned char *teb = teb_of();
    SLE(1234); if (*(int *)(teb + 0x68) != 1234 || GLE() != 1234) { puts("FAIL lasterror"); return 1; }
    *(void **)(teb + 0x1480 + 5 * 8) = (void *)0xabc; SLE(9);
    if (TLS(5) != (void *)0xabc || GLE() != 0) { puts("FAIL tls"); return 1; }
    if (TLS(64) != (void *)0x7777 || slow_tls_n != 1) { puts("FAIL tls slow"); return 1; }
    SLE(9); if (FLS(3) != (void *)0x8888 || slow_fls_n != 1) { puts("FAIL fls no-slots"); return 1; }
    { void **chunk = calloc(17, 8); unsigned char *fls = calloc(1, 0x60); *(void ***)(fls + 0x10) = chunk; chunk[4] = (void *)0xf1;
      *(void **)(teb + 0x17c8) = fls; SLE(9);
      if (FLS(3) != (void *)0xf1 || GLE() != 0) { puts("FAIL fls"); return 1; }
      SLE(9); if (FLS(15) != NULL || GLE() != 0) { puts("FAIL fls15"); return 1; }
      if (FLS(0) != (void *)0x8888 || FLS(16) != (void *)0x8888 || slow_fls_n != 3) { puts("FAIL fls range"); return 1; }
      *(void ***)(fls + 0x10) = NULL; SLE(9); if (FLS(2) != NULL || GLE() != 0) { puts("FAIL fls nochunk"); return 1; } }
    { CS c = { 0, -1, 0, 0, 0, 0 }; sem_t s; sem_init(&s, 0, 0); c.LockSemaphore = &s;
      E(&c); E(&c); if (c.LockCount != 1 || c.RecursionCount != 2) { puts("FAIL recurse"); return 1; }
      if (!T(&c) || c.RecursionCount != 3) { puts("FAIL try recurse"); return 1; }
      L(&c); L(&c); L(&c); if (c.LockCount != -1 || c.RecursionCount != 0 || c.OwningThread) { puts("FAIL release"); return 1; }
      if (slow_enter_n || slow_leave_n) { puts("FAIL uncontended went slow"); return 1; } }

    sem_t s; sem_init(&s, 0, 0);
    cs.LockCount = -1; cs.LockSemaphore = &s;
    pthread_t th[64]; int i;
    for (i = 0; i < nthreads; i++) pthread_create(&th[i], NULL, worker, (void *)(intptr_t)(i + 1));
    for (i = 0; i < nthreads; i++) pthread_join(th[i], NULL);
    long want = nthreads * iters;
    printf("threads=%d spin=%u counter=%ld want=%ld final lock=%d rec=%d owner=%p slow enter=%ld leave=%ld -> %s\n",
           nthreads, spin, counter, want, cs.LockCount, cs.RecursionCount, cs.OwningThread, slow_enter_n, slow_leave_n,
           counter == want && cs.LockCount == -1 && !cs.RecursionCount && !cs.OwningThread ? "PASS" : "FAIL");
    return !(counter == want && cs.LockCount == -1);
}
