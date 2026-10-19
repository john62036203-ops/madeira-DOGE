#!/usr/bin/env python3
"""default-buffer-swap (BCD 0.1.573, opt-in, default 0) in madeira_d3d12.c, ported
onto the fork's default-swap path (default-swap-mb/-kb): source checks plus a
host build of the switch reader.

BCD's default-buffer-swap and the fork's default-swap-mb are one mechanism: a
large committed DEFAULT buffer gets storage the runtime allocates (a fresh guest
commit the file tier backs), handed to Metal as a shared no-copy buffer, as
upload-swap (ml1154) does for UPLOAD buffers. So default-buffer-swap turns the
existing path on instead of adding a second one. Checks:
  - all keys off by default; default-buffer-swap-mb 64 by default, never below
    8; 2 adds UAV buffers; 1 keeps UAV, render-target and depth ones private;
  - default-swap-mb/-kb win when set: their threshold, every flag, as before;
    default-buffer-swap is then ignored (and says so);
  - the default-swap condition gains only the flag test and the -max-mb room
    test, both no-ops while default-buffer-swap/-max-mb are 0;
  - storage kept, counted live, wired and entered in the census only when Metal
    accepted it; the release path uncounts all of it;
  - typed views over our storage are Shared, like the buffer;
  - default-buffer-swap-wire = 1 VirtualLocks a moved buffer's storage, a
    refusal is counted and the buffer stays; -max-mb caps the LIVE moved total;
  - the report lines, the catalog entries.
"""
from pathlib import Path
import os, shutil, subprocess, sys, tempfile

root = Path(__file__).resolve().parents[2]
src = (root / "madeira-d3d12/src/pe/madeira_d3d12.c").read_text()
catalog = (root / "app/Madeira/ConfigCatalog.generated.swift").read_text()
ok = True


def check(what, cond):
    global ok
    print(("ok   " if cond else "FAIL ") + what)
    ok &= bool(cond)


def block(start, end="\n}\n"):
    i = src.index(start)
    return src[i:src.index(end, i) + len(end)]


rd = block("static UINT64 mad_default_swap_min(void) {")
check("keys read once, off by default, 64 MB floor by default",
      all(s in rd for s in ('mad_cfg_int_pe("default-swap-mb", 0)', 'mad_cfg_int_pe("default-swap-kb", 0)',
                            'mad_cfg_int_pe("default-buffer-swap", 0)', 'mad_cfg_int_pe("default-buffer-swap-mb", 64)',
                            'mad_cfg_int_pe("default-buffer-swap-wire", 0)', 'mad_cfg_int_pe("default-buffer-swap-max-mb", 0)')))
check("one copy of the mechanism: no second DEFAULT-buffer path",
      src.count("info.options = WMTResourceStorageModeShared;") == 1 and "mad_defswap_mode" not in src)

create = block("static HRESULT mad_create_resource_at(struct mad_device *d, D3D12_HEAP_TYPE heap_type,\n"
               "                                      const D3D12_RESOURCE_DESC *desc, REFIID riid, void **out,\n"
               "                                      struct mad_memheap *ph, UINT64 poff) {")
cond = ('if (!r->buffer && heap_type == D3D12_HEAP_TYPE_DEFAULT && !r->placed_heap && mad_default_swap_min()\n'
        '            && info.length >= mad_default_swap_min() && mad_defswap_flags_ok(desc->Flags)\n'
        '            && mad_defswap_room(info.length)) {')
check("default-swap condition: as before plus the flag and room tests, the room last", cond in create)
ds = create[create.index(cond):]
ds = ds[:ds.index("if (!r->buffer) r->buffer = MTLDevice_newBuffer(d->mtl_device, &info);")]
acc = ds[ds.index("if (r->buffer) {"):ds.index("} else {")]
check("accepted: counted live, wired with the switch, entered in the census",
      "r->own_mem = mem;" in acc and
      "InterlockedExchangeAdd64(&g_defswap_bytes, (LONG64)len); InterlockedIncrement(&g_defswap_n);" in acc and
      "if (g_defswap_wire) r->own_wired = mad_defswap_wire(mem, len);" in acc and
      "mad_dsw_track(mem, len, 1);" in acc and
      "info.memory.ptr = NULL;" in acc)
check("refused: memory freed, GPU-private as before",
      "VirtualFree(mem, 0, MEM_RELEASE);" in ds[ds.index("} else {"):] and
      "mad_defswap_wire" not in ds[ds.index("} else {"):])
check("typed views over our storage are Shared, like the buffer",
      "ti.options = (r->cpu || r->own_mem) ? WMTResourceStorageModeShared : WMTResourceStorageModePrivate;" in src and
      "ti.options = r->cpu ? WMTResourceStorageModeShared : WMTResourceStorageModePrivate;" not in src)
rel = block("static ULONG STDMETHODCALLTYPE res_Release(ID3D12Resource *This) {")
own = rel[rel.index("if (r->own_mem) {"):]
check("release uncounts the live total, leaves the census, uncounts wired storage, frees after the GPU",
      "if (r->heap == D3D12_HEAP_TYPE_DEFAULT) {" in own and
      "InterlockedExchangeAdd64(&g_defswap_bytes, -(LONG64)((r->size + 0xffff) & ~(UINT64)0xffff)); InterlockedDecrement(&g_defswap_n);" in own and
      "mad_dsw_track(r->own_mem, 0, 0);" in own and
      "if (r->own_wired) {" in own and
      "InterlockedExchangeAdd64(&g_defswap_wired, -(LONG64)((r->size + 0xffff) & ~(UINT64)0xffff)); InterlockedDecrement(&g_defswap_nwired);" in own and
      own.index("if (r->own_wired) {") < own.index("md->mhret[md->nmhret].mem = r->own_mem;"))
rep = block("static void mad_acct_report(void) {")
check("report lines after ml1154's, the wire line after default-buffer-swap's",
      rep.index("ml1154 CPU-visible buffers on file-backed storage") <
      rep.index("default-buffer-swap: %ld DEFAULT buffers on file-backed storage") <
      rep.index("default-buffer-swap-wire: %ld of them wired"))
check("no BCD config name", "bcd.cfg" not in src)
for key, dflt in (("default-buffer-swap", "0"), ("default-buffer-swap-mb", "64"), ("default-buffer-swap-wire", "0"),
                  ("default-buffer-swap-max-mb", "0"), ("default-swap-mb", "0"), ("default-swap-kb", "0")):
    check("settings catalog: %s (default %s)" % (key, dflt),
          'ConfigOption(key: "%s", title: "", kind: .int, defaultValue: "%s", category: "Direct3D 12"' % (key, dflt) in catalog)

harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned long long UINT64; typedef unsigned UINT;
#define MemoryBarrier() __sync_synchronize()
typedef long LONG; typedef long long LONG64; typedef unsigned long DWORD; typedef int BOOL; typedef size_t SIZE_T;
#define D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET 0x1
#define D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL 0x2
#define D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS 0x4
static const char *g_keys[6] = { "default-swap-mb", "default-swap-kb", "default-buffer-swap", "default-buffer-swap-mb",
                                 "default-buffer-swap-wire", "default-buffer-swap-max-mb" };
static long long g_val[6]; static int g_set[6], g_logs;
static long long mad_cfg_int_pe(const char *key, long long dflt) {
    int i;
    for (i = 0; i < 6; i++) if (!strcmp(key, g_keys[i])) return g_set[i] ? g_val[i] : dflt;
    return dflt;
}
static volatile LONG64 g_defswap_bytes, g_defswap_wired; static volatile LONG g_defswap_nwired, g_defswap_wire_fail;
static LONG InterlockedIncrement(volatile LONG *p) { return ++*p; }
static LONG64 InterlockedExchangeAdd64(volatile LONG64 *p, LONG64 v) { LONG64 o = *p; *p += v; return o; }
static int g_lock_ok = 1, g_locks;
static BOOL VirtualLock(void *p, SIZE_T n) { (void)p; (void)n; g_locks++; return g_lock_ok; }
static DWORD GetLastError(void) { return 1453; }
static UINT64 mad_tick(void) { return 0; }
static UINT64 mad_tick_freq(void) { return 24000000; }
static void d3d12_log(const char *fmt, ...) { va_list ap; va_start(ap, fmt); g_logs++; vprintf(fmt, ap); va_end(ap); }
%s
/* argv: six key values ("-" = unset), then optional scenario */
int main(int argc, char **argv) {
    UINT64 min; int i;
    for (i = 0; i < 6 && i + 1 < argc; i++) if (strcmp(argv[i + 1], "-")) { g_set[i] = 1; g_val[i] = atoll(argv[i + 1]); }
    min = mad_default_swap_min();
    if (mad_default_swap_min() != min) return 3;   /* read once */
    if (argc > 7) {   /* room/wire scenario: 256 MB buffers; every other lock refused when argv[7] is 2 */
        int moved = 0, wired = 0;
        for (i = 0; i < 10; i++) {
            if (!mad_defswap_room(256ull << 20)) break;
            g_defswap_bytes += 256ll << 20; moved++;
            if (atoll(argv[7]) == 2) g_lock_ok = i %% 2 == 0;
            if (g_defswap_wire) wired += mad_defswap_wire((void *)(size_t)(0x10000 * (i + 1)), (SIZE_T)256 << 20);
        }
        printf("RESULT moved=%%d wired=%%d locks=%%d nwired=%%ld wired_mb=%%lld fail=%%ld\n", moved, wired, g_locks,
               (long)g_defswap_nwired, (long long)(g_defswap_wired >> 20), (long)g_defswap_wire_fail);
        return 0;
    }
    printf("RESULT min_kb=%%llu mode=%%d flags=%%d%%d%%d%%d logs=%%d wire=%%d max=%%llu\n", min >> 10, g_defswap_mode,
           mad_defswap_flags_ok(0), mad_defswap_flags_ok(0x4), mad_defswap_flags_ok(0x1), mad_defswap_flags_ok(0x2),
           g_logs, g_defswap_wire, g_defswap_max >> 20);
    return 0;
}
'''
reader = src[src.index("static int g_defswap_mode;"):]
reader = reader[:reader.index("\n}\n", reader.index("static int mad_defswap_wire(void *mem, SIZE_T len) {")) + 3]
cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
if not cc:
    print("note: no host C compiler; the switch reader was not built")
else:
    with tempfile.TemporaryDirectory() as tmp:
        c = os.path.join(tmp, "t.c"); exe = os.path.join(tmp, "t")
        with open(c, "w") as f:
            f.write(harness % reader)
        r = subprocess.run([cc, "-std=c99", "-Wall", "-Werror", "-Wno-unused-function", "-o", exe, c], capture_output=True, text=True)
        check("switch reader builds on the host", r.returncode == 0)
        if r.returncode:
            print(r.stderr)
        else:
            def run(*args):
                out = subprocess.run([exe] + [str(a) for a in args], capture_output=True, text=True)
                line = [l for l in out.stdout.splitlines() if l.startswith("RESULT")]
                return out.returncode, (line[0] if line else out.stdout)
            # args: default-swap-mb, default-swap-kb, default-buffer-swap, default-buffer-swap-mb, -wire, -max-mb
            check("unset: off, one line (as before), every flag would pass",
                  run() == (0, "RESULT min_kb=0 mode=0 flags=1111 logs=1 wire=0 max=0"))
            check("default-buffer-swap 0: off, as before", run("-", "-", 0) == (0, "RESULT min_kb=0 mode=0 flags=1111 logs=1 wire=0 max=0"))
            check("wire/max without a switch: nothing", run("-", "-", "-", "-", 1, 512) == (0, "RESULT min_kb=0 mode=0 flags=1111 logs=1 wire=0 max=0"))
            check("default-swap-mb 4 alone: 4 MB, every flag, one line (as before)",
                  run(4) == (0, "RESULT min_kb=4096 mode=0 flags=1111 logs=1 wire=0 max=0"))
            check("default-swap-kb 512 wins over -mb", run(4, 512) == (0, "RESULT min_kb=512 mode=0 flags=1111 logs=1 wire=0 max=0"))
            check("default-buffer-swap 1: 64 MB, no UAV/RT/DS", run("-", "-", 1) == (0, "RESULT min_kb=65536 mode=1 flags=1000 logs=2 wire=0 max=0"))
            check("default-buffer-swap 2: UAV too, never RT/DS", run("-", "-", 2) == (0, "RESULT min_kb=65536 mode=2 flags=1100 logs=2 wire=0 max=0"))
            check("default-buffer-swap 7: treated as 2", run("-", "-", 7) == (0, "RESULT min_kb=65536 mode=2 flags=1100 logs=2 wire=0 max=0"))
            check("default-buffer-swap -1: off", run("-", "-", -1) == (0, "RESULT min_kb=0 mode=0 flags=1111 logs=1 wire=0 max=0"))
            check("default-buffer-swap-mb 128", run("-", "-", 1, 128) == (0, "RESULT min_kb=131072 mode=1 flags=1000 logs=2 wire=0 max=0"))
            check("default-buffer-swap-mb never below 8", run("-", "-", 1, 1) == (0, "RESULT min_kb=8192 mode=1 flags=1000 logs=2 wire=0 max=0"))
            check("default-swap-mb set: default-buffer-swap ignored (logged), every flag",
                  run(16, "-", 1, 128) == (0, "RESULT min_kb=16384 mode=0 flags=1111 logs=2 wire=0 max=0"))
            check("wire 1, max 512 MB read with default-buffer-swap",
                  run("-", "-", 1, 64, 1, 512) == (0, "RESULT min_kb=65536 mode=1 flags=1000 logs=2 wire=1 max=512"))
            check("wire 1, max 512 MB apply to default-swap-mb too (one extra line)",
                  run(16, "-", "-", "-", 1, 512) == (0, "RESULT min_kb=16384 mode=0 flags=1111 logs=2 wire=1 max=512"))
            check("max -3: no cap", run("-", "-", 1, 64, 0, -3) == (0, "RESULT min_kb=65536 mode=1 flags=1000 logs=2 wire=0 max=0"))
            res = run("-", "-", 1, 64, 0, 0, 1)
            check("no cap, no wire: every buffer moves, nothing locked", res[1].startswith("RESULT moved=10 wired=0 locks=0 "))
            res = run("-", "-", 1, 64, 0, 512, 1)
            check("cap 512 MB: two 256 MB buffers move, the third stays private", res[1].startswith("RESULT moved=2 "))
            res = run("-", "-", 1, 64, 0, 700, 1)
            check("cap 700 MB: two move (a third would pass it)", res[1].startswith("RESULT moved=2 "))
            res = run("-", "-", 1, 64, 1, 1024, 1)
            check("wire: each moved buffer locked and counted", res[1] == "RESULT moved=4 wired=4 locks=4 nwired=4 wired_mb=1024 fail=0")
            res = run("-", "-", 1, 64, 1, 0, 2)
            check("wire refusals counted, the buffer stays (moved 10, wired 5, failed 5)",
                  res[1] == "RESULT moved=10 wired=5 locks=10 nwired=5 wired_mb=1280 fail=5")
sys.exit(0 if ok else 1)
