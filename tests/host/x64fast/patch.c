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
static int mach_vm_region(int t, mach_vm_address_t *a, mach_vm_size_t *s, int f, vm_region_info_t i, mach_msg_type_number_t *c, mach_port_t *o) { ((vm_region_basic_info_data_64_t *)i)->protection = 5; return 0; }
static int vm_protect(int t, vm_address_t a, size_t s, int m, int p) { return 1; }
static void sys_icache_invalidate(void *p, size_t n) {}
static int dprintf_(int fd, const char *f, ...);
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
int main(int argc, char **argv)
{
    int bad = 0;
    for (int a = 1; a < argc; a++) {
        size_t size; unsigned char *img = map_pe(argv[a], &size);
        unsigned char *orig = malloc(size); memcpy(orig, img, size);
        unsigned char *pool = malloc(size); memcpy(pool, img, size);
        const char *mn = strrchr(argv[a], '/') + 1;
        x64f_patch_image(img, size, pool, pool, mn);
        if (memcmp(img, pool, size)) { printf("  image and pool differ\n"); bad++; }
        for (unsigned i = 0; i < sizeof(x64f_targets) / sizeof(x64f_targets[0]); i++) {
            if (strcasecmp(mn, x64f_targets[i].module)) continue;
            unsigned e = x64f_export(orig, size, x64f_targets[i].name);
            if (!e) { printf("  %-28s forwarder/absent\n", x64f_targets[i].name); continue; }
            if (img[e] != 0xe9) { printf("  %-28s NOT patched\n", x64f_targets[i].name); bad++; continue; }
            unsigned stub = e + 5 + *(int *)(img + e + 1);
            int k = x64f_targets[i].kind; unsigned len = x64f_stub[k].len;
            if (memcmp(img + stub, x64f_stub[k].code, k == X64F_ENTER ? X64F_SPIN_AT : len)) { printf("  stub mismatch\n"); bad++; }
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
            printf("  %-28s entry 0x%x -> stub 0x%x, %s\n", x64f_targets[i].name, e, stub, res);
        }
        /* nothing else changed */
        size_t diff = 0; for (size_t j = 0; j < size; j++) if (img[j] != orig[j]) diff++;
        printf("  %zu bytes changed\n", diff);
        x64f_patch_image(img, size, pool, pool, mn);   /* second run must be a no-op */
    }
    printf(bad ? "FAIL %d\n" : "PASS\n", bad); return !!bad;
}
