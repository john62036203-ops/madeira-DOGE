/* Host check of x64fast_ios.h against the real PE files: map each like the
 * loader does, run x64f_patch_image, then follow every patched entry. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/mman.h>
typedef uintptr_t UINT_PTR; typedef size_t SIZE_T;
static const UINT_PTR host_page_mask = 0x3fff;
#define ROUND_SIZE(addr,size,mask) (((SIZE_T)(size) + ((UINT_PTR)(addr) & (mask)) + (mask)) & ~(UINT_PTR)(mask))
typedef uint64_t mach_vm_address_t, mach_vm_size_t; typedef int kern_return_t, mach_port_t, mach_msg_type_number_t, vm_address_t;
typedef struct { int protection; } vm_region_basic_info_data_64_t; typedef void *vm_region_info_t;
#define KERN_SUCCESS 0
#define VM_REGION_BASIC_INFO_64 0
#define VM_REGION_BASIC_INFO_COUNT_64 1
#define MACH_PORT_NULL 0
#define FALSE 0
#define VM_PROT_READ 1
#define VM_PROT_WRITE 2
#define VM_PROT_COPY 0x10
static int mach_task_self(void) { return 0; }
static int mach_vm_region(int t, mach_vm_address_t *a, mach_vm_size_t *s, int f, vm_region_info_t i, mach_msg_type_number_t *c, mach_port_t *o) { ((vm_region_basic_info_data_64_t *)i)->protection = 3;   /* test buffers stay read-write */ return 0; }
static int vm_protect(int t, vm_address_t a, size_t s, int m, int p) { return 1; }
static void sys_icache_invalidate(void *p, size_t n) {}

#include <stdarg.h>
static int dprintf_(int fd, const char *f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); return 0; }
#define dprintf dprintf_
static long long cfg_spin = 300;
static long long madeira_cfg_int(const char *k, long long d) { return !strcmp(k, "x64-fast") ? 1 : !strcmp(k, "x64-fast-spin") ? cfg_spin : d; }
#include "../../../build/ntdll-unix/x64fast_ios.h"

static unsigned char *map_pe(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb"); fseek(f, 0, SEEK_END); long n = ftell(f); rewind(f);
    unsigned char *d = malloc(n); fread(d, 1, n, f); fclose(f);
    unsigned pe = *(unsigned *)(d + 0x3c); unsigned soi = *(unsigned *)(d + pe + 24 + 56);
    unsigned short nsec = *(unsigned short *)(d + pe + 6), opt = *(unsigned short *)(d + pe + 20);
    unsigned char *img = mmap(NULL, soi, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    memcpy(img, d, *(unsigned *)(d + pe + 24 + 60));
    for (int i = 0; i < nsec; i++) {
        unsigned char *s = d + pe + 24 + opt + 40 * i;
        unsigned vs = *(unsigned *)(s + 8), va = *(unsigned *)(s + 12), rs = *(unsigned *)(s + 16), rp = *(unsigned *)(s + 20);
        unsigned map = (vs + 0xfff) & ~0xfffu; memcpy(img + va, d + rp, rs < map ? rs : map);
    }
    *size = soi; return img;
}
/* A minimal pure x64 PE (headers + one IAT) holding the given slot values. */
static unsigned char *fake_x64(uint64_t *slots, int n, size_t *size)
{
    unsigned char *img = calloc(1, 0x3000); unsigned pe = 0x80;
    img[0] = 'M'; img[1] = 'Z'; *(unsigned *)(img + 0x3c) = pe; memcpy(img + pe, "PE\0\0", 4);
    *(unsigned short *)(img + pe + 4) = 0x8664; *(unsigned short *)(img + pe + 6) = 1;
    *(unsigned short *)(img + pe + 20) = 0xf0; *(unsigned short *)(img + pe + 24) = 0x20b;
    *(unsigned *)(img + pe + 24 + 112 + 8 * 12) = 0x2000; *(unsigned *)(img + pe + 24 + 112 + 8 * 12 + 4) = n * 8;
    memcpy(img + pe + 24 + 0xf0, ".rdata\0\0", 8);
    memcpy(img + 0x2000, slots, n * 8); *size = 0x3000; return img;
}

int main(int argc, char **argv)
{
    int bad = 0; uint64_t slots[64]; int ns = 0; uintptr_t qpc_entry = 0, qpc_stub = 0; unsigned char *k32 = 0; size_t k32_size = 0;
    for (int a = 1; a < argc; a++) {
        size_t size; unsigned char *img = map_pe(argv[a], &size);
        unsigned char *orig = malloc(size); memcpy(orig, img, size);
        unsigned char *pool = malloc(size); memcpy(pool, img, size);
        const char *mn = strrchr(argv[a], '/') + 1;
        if (!strcasecmp(mn, "kernel32.dll")) { k32 = img; k32_size = size; }
        x64f_patch_image(img, size, pool, pool, mn);
        if (memcmp(img, pool, size)) { printf("  image and pool differ\n"); bad++; }
        for (unsigned i = 0; i < sizeof(x64f_targets) / sizeof(x64f_targets[0]); i++) {
            if (strcasecmp(mn, x64f_targets[i].module)) continue;
            unsigned e = x64f_export(orig, size, x64f_targets[i].name);
            if (!e) { printf("  %-28s forwarder/absent\n", x64f_targets[i].name); continue; }
            if (memcmp(img + e, orig + e, 16)) { printf("  %-28s ENTRY CHANGED\n", x64f_targets[i].name); bad++; }
            uintptr_t sa = x64f_stub_for((uintptr_t)img + e);
            if (!sa) { printf("  %-28s not registered\n", x64f_targets[i].name); bad++; continue; }
            unsigned stub = (unsigned)(sa - (uintptr_t)img);
            slots[ns++] = (uintptr_t)img + e;
            int k = x64f_targets[i].kind; unsigned len = x64f_stub[k].len;
            if (k == X64F_QPC) {
                /* qpc-spin-sleep-us (default 100): the registered entry is the spin throttle in front of the stub */
                unsigned w = stub; int r1, iv, r2; unsigned de = x64f_export(orig, size, "NtDelayExecution");
                if (memcmp(img + w, x64f_qpcw, X64F_QPCW_STUB_END - 4)) { printf("  qpc spin throttle missing\n"); bad++; }
                memcpy(&r1, img + w + X64F_QPCW_STUB_END - 4, 4); memcpy(&iv, img + w + X64F_QPCW_IV_END - 4, 4); memcpy(&r2, img + w + X64F_QPCW_DELAY_END - 4, 4);
                stub = w + X64F_QPCW_STUB_END + r1;
                unsigned dt = w + X64F_QPCW_DELAY_END + r2;
                printf("  qpc spin throttle 0x%x -> stub 0x%x, NtDelayExecution 0x%x (want 0x%x), interval %d %s\n", w, stub, dt, de, iv,
                       dt == de && iv == -1000 && stub < w ? "ok" : "WRONG");
                if (dt != de || iv != -1000 || stub >= w) bad++;
                unsigned char t[sizeof(x64f_qpcw)]; memcpy(t, img + w, sizeof t);
                memcpy(t + X64F_QPCW_STUB_END - 4, x64f_qpcw + X64F_QPCW_STUB_END - 4, 4);
                memcpy(t + X64F_QPCW_DATA_END - 8, x64f_qpcw + X64F_QPCW_DATA_END - 8, 8);
                { uint64_t st; memcpy(&st, img + w + X64F_QPCW_DATA_END - 8, 8);
                  if (!st || (st >= (uintptr_t)img && st < (uintptr_t)img + size)) { printf("  qpc spin throttle state not in separate writable memory\n"); bad++; } }
                memcpy(t + X64F_QPCW_IV_END - 4, x64f_qpcw + X64F_QPCW_IV_END - 4, 4);
                memcpy(t + X64F_QPCW_DELAY_END - 4, x64f_qpcw + X64F_QPCW_DELAY_END - 4, 4);
                if (memcmp(t, x64f_qpcw, sizeof t)) { printf("  qpc spin throttle mismatch outside the linked fields\n"); bad++; }
            }
            if (k == X64F_QPC && img[stub] == 0x49 && img[stub + 1] == 0xba) {
                /* qpca: this test's pool is a separate copy, so the statics are the pool copy's:
                 * base = pool + qpc_disabled, disp32s = distance of each static from it */
                static const unsigned endo[4] = { X64F_QPCA_DIS_END, X64F_QPCA_FREQ_END, X64F_QPCA_LAST_END, X64F_QPCA_OFF_END };
                static const unsigned want_v[4] = { 0xe2a50, 0xe2a58, 0xe2a60, 0xe2a68 };
                unsigned char tmpl[256]; uint64_t base; len = sizeof(x64f_qpca);
                memcpy(tmpl, img + stub, len); memcpy(&base, img + stub + X64F_QPCA_BASE_END - 8, 8);
                printf("  qpca base 0x%llx (want pool+0x%x) %s\n", (unsigned long long)base, want_v[0], base == (uintptr_t)pool + want_v[0] ? "ok" : "WRONG");
                if (base != (uintptr_t)pool + want_v[0]) bad++;
                memcpy(tmpl + X64F_QPCA_BASE_END - 8, x64f_qpca + X64F_QPCA_BASE_END - 8, 8);
                for (int q = 0; q < 4; q++) {
                    unsigned at = endo[q] - (q ? 4 : 5); int disp; memcpy(&disp, img + stub + at, 4);
                    printf("  qpca static %d at base%+d (want %+d) %s\n", q, disp, (int)(want_v[q] - want_v[0]), disp == (int)(want_v[q] - want_v[0]) ? "ok" : "WRONG");
                    if (disp != (int)(want_v[q] - want_v[0])) bad++;
                    memcpy(tmpl + at, x64f_qpca + at, 4);
                }
                if (img[stub + X64F_QPCA_SHIFT_END - 1] != 6) { printf("  qpca tsc shift WRONG\n"); bad++; }
                tmpl[X64F_QPCA_SHIFT_END - 1] = x64f_qpca[X64F_QPCA_SHIFT_END - 1];
                if (memcmp(tmpl, x64f_qpca, len)) { printf("  qpca stub mismatch outside the linked fields\n"); bad++; }
                qpc_entry = (uintptr_t)img + e; qpc_stub = sa;
            }
            else if (k == X64F_QPC) {
                /* the four displacements must reach ntdll's statics, the shift is FEX's 24 MHz -> 1.536 GHz */
                static const unsigned endo[4] = { X64F_QPC_DIS_END, X64F_QPC_FREQ_END, X64F_QPC_LAST_END, X64F_QPC_OFF_END };
                static const unsigned want_v[4] = { 0xe2a50, 0xe2a58, 0xe2a60, 0xe2a68 };
                unsigned char tmpl[256]; memcpy(tmpl, img + stub, len);
                for (int q = 0; q < 4; q++) {
                    unsigned at = endo[q] - (q ? 4 : 5); int disp; memcpy(&disp, img + stub + at, 4);
                    unsigned tgt = stub + endo[q] + disp;
                    printf("  qpc static %d -> 0x%x (want 0x%x) %s\n", q, tgt, want_v[q], tgt == want_v[q] ? "ok" : "WRONG");
                    if (tgt != want_v[q]) bad++;
                    memcpy(tmpl + at, x64f_qpc + at, 4);
                }
                printf("  qpc tsc shift %u %s\n", img[stub + X64F_QPC_SHIFT_END - 1], img[stub + X64F_QPC_SHIFT_END - 1] == 6 ? "ok" : "WRONG");
                if (img[stub + X64F_QPC_SHIFT_END - 1] != 6) bad++;
                tmpl[X64F_QPC_SHIFT_END - 1] = x64f_qpc[X64F_QPC_SHIFT_END - 1];
                if (memcmp(tmpl, x64f_qpc, len)) { printf("  qpc stub mismatch outside the linked fields\n"); bad++; }
                qpc_entry = (uintptr_t)img + e; qpc_stub = sa;
            }
            else if (memcmp(img + stub, x64f_stub[k].code, k == X64F_ENTER ? X64F_SPIN_AT : len)) { printf("  stub mismatch\n"); bad++; }
            if (k == X64F_ENTER && *(int *)(img + stub + X64F_SPIN_AT) != cfg_spin) { printf("  spin not set\n"); bad++; }
            const char *res = "no fallback";
            char buf[128];
            if (x64f_stub[k].needs_fallback) {
                unsigned fb = stub + len, want, got;
                if (orig[e] == 0x48) { want = e + 14 + *(int *)(orig + e + 10); got = fb + 14 + *(int *)(img + fb + 10);
                    if (memcmp(img + fb, orig + e, 10)) bad++, res = "FFS prologue differs"; }
                else { want = e + 6 + *(int *)(orig + e + 2); got = fb + 6 + *(int *)(img + fb + 2); if (img[fb] != 0xff || img[fb+1] != 0x25) bad++; }
                snprintf(buf, sizeof buf, "fallback -> 0x%x (original 0x%x) %s", got, want, got == want ? "ok" : "WRONG"); res = buf;
                if (got != want) bad++;
            }
            printf("  %-28s entry 0x%x unchanged, stub 0x%x, %s\n", x64f_targets[i].name, e, stub, res);
        }
        size_t diff = 0, outside = 0; unsigned lo, hi; x64f_slack(orig, size, &lo, &hi);
        for (size_t j = 0; j < size; j++) if (img[j] != orig[j]) { diff++; if (j < lo || j >= hi) outside++; }
        printf("  %zu bytes changed, %zu outside the .hexpthk tail\n", diff, outside);
        if (outside) bad++;
        int before = x64f_npairs;
        x64f_patch_image(img, size, pool, pool, mn);   /* second run must be a no-op */
        if (x64f_npairs != before) { printf("  second run registered again\n"); bad++; }
    }
    /* kernel32!QueryPerformanceCounter is `jmp [rip+slot]` through kernel32's own
     * import slot; bind that slot to ntdll's entry as the loader does, and the
     * redirect must chase it to ntdll's QPC stub. */
    uint64_t k32_qpc = 0;
    if (!qpc_entry || !qpc_stub) { printf("  ntdll QueryPerformanceCounter stub missing\n"); bad++; }
    else if (k32) {
        unsigned e = x64f_export(k32, k32_size, "QueryPerformanceCounter");
        if (!e || k32[e] != 0xff || k32[e + 1] != 0x25) { printf("  kernel32 QueryPerformanceCounter is not a jmp [rip+slot]\n"); bad++; }
        else { *(uintptr_t *)(k32 + e + 6 + *(int *)(k32 + e + 2)) = qpc_entry; k32_qpc = (uintptr_t)k32 + e; }
    }
    int k32_at = ns;
    if (k32_qpc) slots[ns++] = k32_qpc;
    /* a pure x64 module importing every entry, plus two unrelated slots */
    slots[ns++] = 0x1234; slots[ns++] = 0;
    size_t fsz; unsigned char *fx = fake_x64(slots, ns, &fsz);
    x64f_redirect_iat(fx, fsz, 0x2000, 0x1000);
    for (int i = 0; i < ns; i++) {
        uint64_t v = *(uint64_t *)(fx + 0x2000 + 8 * i), want = x64f_stub_for(slots[i]) ? x64f_stub_for(slots[i]) : slots[i];
        if (k32_qpc && i == k32_at) { want = qpc_stub; printf("  kernel32 QueryPerformanceCounter slot -> 0x%llx (ntdll's QPC stub 0x%llx) %s\n", (unsigned long long)v, (unsigned long long)qpc_stub, v == want ? "ok" : "WRONG"); }
        if (v != want) { printf("  slot %d = 0x%llx, want 0x%llx\n", i, (unsigned long long)v, (unsigned long long)want); bad++; }
    }
    /* a hybrid module (.hexpthk) is left alone */
    size_t hsz; unsigned char *hx = fake_x64(slots, ns, &hsz); memcpy(hx + 0x80 + 24 + 0xf0, ".hexpthk", 8);
    x64f_redirect_iat(hx, hsz, 0x2000, 0x1000);
    if (memcmp(hx + 0x2000, slots, ns * 8)) { printf("  hybrid module was redirected\n"); bad++; }
    printf(bad ? "FAIL %d\n" : "PASS\n", bad); return !!bad;
}
