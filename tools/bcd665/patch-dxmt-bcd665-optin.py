#!/usr/bin/env python3
"""DXMT: three upstream changes that BCD 0.1.665 took from Madeira's dxmt fork, each opt-in.

  * DXMT_DYN_KEEP = <n> (2c3bd5f, meshoklv): a dynamic buffer keeps up to
    max(64, min(n, DXMT_DYN_KEEP_KB * 1024 / its size)) retired Metal buffers
    for reuse instead of 64, so a game that renames a constant buffer on every
    draw stops creating and releasing thousands of them a frame (Dark Souls III:
    15-30 thousand a second). DXMT_DYN_KEEP_KB defaults to 4096. Unset or 0:
    unchanged (the 64-entry trim of tools/patch-dxmt-dyn-trim-switch.py and
    tools/patch-dxmt-dyn-front-walk.py).
  * env.MADEIRA_DXMT_UPSTREAM_FIXES = 1 (Feifan He, 7327fce and 1047544):
    a sampler's MaxAnisotropy is clamped to 1..16, and restoring a context's
    state (deferred contexts, SwapDeviceContextState) rebinds the compute
    stage's own UAVs instead of the output merger's. Unset or 0: as before.

Applied by tools/build-d3d11-dll.sh to its copies of the sources (the d3d11 tree
and dxmt_dynamic.cpp), so it is in the 64-bit d3d11-src.dll a game gets with
env.MADEIRA_D3D11_SRC = 1. The committed d3d11.dll and the i386 farm are not
touched (this lives in tools/bcd665/ so the farm's cache key does not change).
madeira-doge fork-local build patch; not a contribution to DXMT.
Usage: patch-dxmt-bcd665-optin.py <d3d11 source dir> <dxmt source dir>
Idempotent; each file is all-or-nothing (restored when its anchor moved), and
the script exits non-zero naming what did not apply.
"""
import sys
from pathlib import Path

MARK = "madeira-doge bcd665-optin"

DYN_HELPER = r'''namespace dxmt {

/* %s: DXMT_DYN_KEEP = <entries>, default unset/0 = off (willfaust/dxmt 2c3bd5f via BCD 0.1.665).
 * On, an instance keeps up to max(64, min(DXMT_DYN_KEEP, DXMT_DYN_KEEP_KB*1024/length)) retired names
 * (DXMT_DYN_KEEP_KB default 4096): a 256-byte constant buffer keeps up to DXMT_DYN_KEEP, a 64 KB buffer
 * still 64. The census walk is skipped in this mode; [trim] and "dynamic recycle" totals stay exact. */
static uint32_t
madDynKeepFor(uint64_t length) {
  static const uint32_t keep_n = [] {
    const std::string v = env::getEnvVar("DXMT_DYN_KEEP");
    long n = v.empty() ? 0 : std::strtol(v.c_str(), nullptr, 0);
    if (n < 0) n = 0;
    if (n > 65536) n = 65536;
    if (n)
      ERR("[dyn-keep] DXMT_DYN_KEEP=", n, " (retired names kept per dynamic buffer)");
    return (uint32_t)n;
  }();
  static const uint64_t budget = [] {
    const std::string v = env::getEnvVar("DXMT_DYN_KEEP_KB");
    long kb = v.empty() ? 4096 : std::strtol(v.c_str(), nullptr, 0);
    if (kb < 0) kb = 0;
    return (uint64_t)kb * 1024;
  }();
  if (!keep_n)
    return 0;
  uint64_t by_bytes = length ? budget / length : keep_n;
  uint64_t k = std::min<uint64_t>(keep_n, by_bytes);
  return (uint32_t)std::max<uint64_t>(k, 64);
}
''' % MARK

DYN_BLOCK_OLD = "   * gated. Behaviour must never depend on diagnostic capacity. */\n  {\n"
DYN_BLOCK_NEW = r'''   * gated. Behaviour must never depend on diagnostic capacity. */
  if (const uint32_t mad_keep = madDynKeepFor(buffer ? buffer->length() : 0)) {
    /* madeira-doge bcd665-optin, DXMT_DYN_KEEP: fifo is in non-decreasing will_free_at order, so dropping
     * from the front while the front is GPU-complete never touches a fenced entry; O(dropped), no walk. */
    uint64_t freed = 0, freed_n = 0;
    while (fifo.size() > mad_keep && fifo.front().will_free_at <= coherent_seq_id) {
      const QueueEntry &f = fifo.front();
      freed += f.allocation.ptr() ? f.allocation->census_bytes_ : 0;
      freed_n++;
      fifo.pop_front();
    }
    if (freed_n) {
      trimmed_last_ = true;
      g_trim_total_n.fetch_add(freed_n, std::memory_order_relaxed);
      g_trim_total_bytes.fetch_add(freed, std::memory_order_relaxed);
    }
    if (census_id_ < DYN_CENSUS_SLOTS)
      g_dyn_stats[census_id_].depth.store(fifo.size(), std::memory_order_relaxed);
  } else
  {
'''

FIXES_ON = ('[] { static const bool on = ::dxmt::env::getEnvVar("MADEIRA_DXMT_UPSTREAM_FIXES") == "1"; '
            'return on; }()')

ANISO_OLD = "    info.max_anisotroy = desc.MaxAnisotropy;\n"
ANISO_NEW = ("    /* %s: env.MADEIRA_DXMT_UPSTREAM_FIXES = 1 clamps to 1..16 (upstream 7327fce) */\n"
             "    info.max_anisotroy = %s ? std::clamp(desc.MaxAnisotropy, 1u, 16u) : desc.MaxAnisotropy;\n") % (MARK, FIXES_ON)

UAV_OLD = ("    for (const auto &[slot, entry] : state_.OutputMerger.UAVs) {\n"
           "      auto pUAV = entry.View.ptr();\n"
           "      if (auto buffer = pUAV->buffer()) {\n"
           "        EmitST([=, buffer = std::move(buffer), viewId = pUAV->viewId(), counter = pUAV->counter(),\n"
           "              slice = pUAV->bufferSlice()](ArgumentEncodingContext &enc) mutable {\n"
           "          enc.bindOutputBuffer<PipelineStage::Compute>(")
UAV_NEW = ("    /* %s: env.MADEIRA_DXMT_UPSTREAM_FIXES = 1 rebinds the compute stage's own UAVs (upstream 1047544) */\n"
           "    for (const auto &[slot, entry] : (%s ? state_.ComputeStageUAV.UAVs : state_.OutputMerger.UAVs)) {\n"
           "      auto pUAV = entry.View.ptr();\n"
           "      if (auto buffer = pUAV->buffer()) {\n"
           "        EmitST([=, buffer = std::move(buffer), viewId = pUAV->viewId(), counter = pUAV->counter(),\n"
           "              slice = pUAV->bufferSlice()](ArgumentEncodingContext &enc) mutable {\n"
           "          enc.bindOutputBuffer<PipelineStage::Compute>(") % (MARK, FIXES_ON)


def edit(path, steps):
    s = path.read_text()
    if MARK in s:
        print("%s: already patched (bcd665-optin)" % path.name)
        return True
    orig = s
    for what, old, new in steps:
        if s.count(old) != 1:
            print("patch-dxmt-bcd665-optin: %s not found once in %s (%d times)" % (what, path.name, s.count(old)), file=sys.stderr)
            path.write_text(orig)
            return False
        s = s.replace(old, new)
    path.write_text(s)
    print("%s: patched (bcd665-optin)" % path.name)
    return True


def main():
    d3d11 = Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11").resolve()
    dxmt = Path(sys.argv[2] if len(sys.argv) > 2 else "dxmt/src/dxmt").resolve()
    ok = True
    ok &= edit(dxmt / "dxmt_dynamic.cpp", [
        ("includes", '#include "dxmt_mem_census.hpp"\n',
         '#include "dxmt_mem_census.hpp"\n#include "util_env.hpp"\n#include "log/log.hpp"\n#include <algorithm>\n#include <cstdlib>\n#include <string>\n'),
        ("namespace", "namespace dxmt {\n", DYN_HELPER),
        ("trim block", DYN_BLOCK_OLD, DYN_BLOCK_NEW),
    ])
    ok &= edit(d3d11 / "d3d11_state_object.cpp", [
        ("includes", '#include "log/log.hpp"\n', '#include "log/log.hpp"\n#include "util_env.hpp"\n#include <algorithm>\n'),
        ("sampler anisotropy", ANISO_OLD, ANISO_NEW),
    ])
    ok &= edit(d3d11 / "d3d11_context_impl.cpp", [
        ("include", '#include "config/config.hpp"', '#include "util_env.hpp"\n#include "config/config.hpp"'),
        ("compute UAV restore", UAV_OLD, UAV_NEW),
    ])
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
