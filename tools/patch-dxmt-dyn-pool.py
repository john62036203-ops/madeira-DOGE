#!/usr/bin/env python3
"""Cheaper dynamic buffer pool for small, hot buffers (source-built d3d11 only).

Sekiro (log 2026-10-15 08:03, build on plan-a 153d489): gameplay sits at 10-19
fps with the GPU 18-29 % busy. The frame waits on the five GXWorker threads
that record deferred contexts, and two things in DynamicBuffer::allocate cost
them time on every call, under the per-buffer lock all five share:

1. The ml681 SAFE TRIM keeps only 64 eligible entries per instance. The hot
   instances are 384/400-byte constant buffers that need ~1,000 allocations a
   frame, so every time the fence advances ~940 retired allocations are
   destroyed and then minted again: ~61k Metal buffers created and ~63k
   released per second, reuse 48-50 %. The keep is now
   max(64, DXMT_DYN_KEEP_KB / bytes per allocation), 1024 KB by default, so a
   small buffer keeps its working set while large buffers (the ~1 GB retained
   set ml685 trimmed) still keep 64 as before.
2. Every allocate walks the whole queue (1,050-2,200 entries) for statistics.
   The eligible count the trim needs is the front run (entries go in in
   will_free_at order), now found by binary search; the full walk that feeds
   [dyn-census] runs on every 256th allocate of a thread.

DXMT_DYN_POOL=0 restores the previous behaviour. The trim itself still stops at
the first fenced entry, so a mis-sorted queue can only change how many entries
it releases, never release one the GPU may still use.

Applied by tools/build-d3d11-dll.sh to its COPY of dxmt_dynamic.cpp after
tools/patch-dxmt-dyn-trim-switch.py, so only d3d11-src.dll
(env.MADEIRA_D3D11_SRC = 1) has it.
Usage: patch-dxmt-dyn-pool.py <tree>/src/dxmt
Idempotent; fails by name if an anchor moves.
"""
import pathlib
import sys

MARKER = "madeira-doge: dyn pool"
path = pathlib.Path(sys.argv[1]) / "dxmt_dynamic.cpp"
s = path.read_text()
if MARKER in s:
    print("dxmt_dynamic.cpp: dyn pool already patched"); sys.exit(0)
if "DXMT_DYN_TRIM" not in s:
    sys.exit("patch-dxmt-dyn-pool: run tools/patch-dxmt-dyn-trim-switch.py first")

PAIRS = [
    # Settings, read once.
    ('#include "log/log.hpp"\n',
     '#include "log/log.hpp"\n#include <algorithm>\n#include <cstdlib>\n'),
    ('namespace dxmt {\n',
     '''namespace dxmt {

/* madeira-doge: dyn pool (tools/patch-dxmt-dyn-pool.py) */
namespace {
struct MadDynPool {
  bool on;
  uint64_t keep_bytes;
};
const MadDynPool &
mad_dyn_pool() {
  static const MadDynPool cfg = [] {
    MadDynPool c{env::getEnvVar("DXMT_DYN_POOL") != "0", 1024ull << 10};
    std::string kb = env::getEnvVar("DXMT_DYN_KEEP_KB");
    if (!kb.empty()) {
      uint64_t v = strtoull(kb.c_str(), nullptr, 10);
      if (v) c.keep_bytes = v << 10;
    }
    if (c.on)
      ERR("[dyn-pool] madeira-doge: keep max(64, ", c.keep_bytes >> 10, " KB) per instance, sampled census walk");
    else
      ERR("[dyn-pool] madeira-doge: OFF (DXMT_DYN_POOL=0)");
    return c;
  }();
  return cfg;
}
thread_local uint32_t mad_walk_tick = 0;
} // namespace
'''),
    # 2. The statistics walk: binary search for the eligible count, full walk sampled.
    ('''    for (const auto &e : fifo) {
      uint64_t bytes = e.allocation.ptr() ? e.allocation->census_bytes_ : 0;''',
     '''    const bool mad_pool = mad_dyn_pool().on;
    const bool full_walk = !mad_pool || (stats && (++mad_walk_tick & 255) == 0);
    if (!full_walk)
      en = (uint64_t)(std::partition_point(fifo.begin(), fifo.end(), [&](const QueueEntry &e) {
                        return e.will_free_at <= coherent_seq_id;
                      }) - fifo.begin());
    if (full_walk) for (const auto &e : fifo) {
      uint64_t bytes = e.allocation.ptr() ? e.allocation->census_bytes_ : 0;'''),
    ('''    if (stats) {
      DynStat &st = g_dyn_stats[census_id_];
      st.depth.store''',
     '''    if (stats && full_walk) {
      DynStat &st = g_dyn_stats[census_id_];
      st.depth.store'''),
    # 1. The keep: a byte budget for small allocations, 64 for large ones.
    ('''    if (mad_trim && en > DYN_KEEP_ELIGIBLE) {
      uint64_t drop = en - DYN_KEEP_ELIGIBLE, freed = 0, freed_n = 0;''',
     '''    uint64_t mad_keep = DYN_KEEP_ELIGIBLE;
    if (mad_pool && en > DYN_KEEP_ELIGIBLE) {
      const QueueEntry &f0 = fifo.front();
      uint64_t per = f0.allocation.ptr() ? f0.allocation->census_bytes_ : 0;
      if (!per && buffer) per = buffer->length();
      if (per && mad_dyn_pool().keep_bytes / per > mad_keep)
        mad_keep = mad_dyn_pool().keep_bytes / per;
    }
    if (mad_trim && en > mad_keep) {
      uint64_t drop = en - mad_keep, freed = 0, freed_n = 0;'''),
]

for old, new in PAIRS:
    if s.count(old) != 1:
        sys.exit(f"patch-dxmt-dyn-pool: anchor found {s.count(old)} times (want 1):\n{old}")
    s = s.replace(old, new)
if MARKER not in s:
    sys.exit("patch-dxmt-dyn-pool: marker missing after editing")
path.write_text(s)
print("dxmt_dynamic.cpp: dyn pool patched")
