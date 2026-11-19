#!/usr/bin/env python3
"""Log which texture God of War's exposure metering reads, and what writes that texture.

Builds 643/644 ([rb-map], [cs-cb]): the game reads two different exposure results from the same compute chain, frame by
frame, with identical constants. The chain's first dispatch (4x135 thread groups) reads a 240x135 texture from compute
SRV slot 0; its sums are the result, so the difference is in that texture. This logs, on the calling thread:

  [lum-in]  #frame res <id> WxH fmt <dxgi>      the texture the 4x135 dispatch reads (once a frame)
  [lum-src] draw rtv <i> ps <id> srv0..3 ...    a draw whose render target is that texture (first 8 a frame)
  [lum-src] cs grp XxY uav <slot> cs <id> ...   a compute dispatch that has it as an unordered access view
  [lum-src] copy from <id>                      CopyResource / CopySubresourceRegion into it

Off unless env.MADEIRA_LUM_SRC_LOG = 1 (source-built d3d11 only: env.MADEIRA_D3D11_SRC = 1). 40000 lines a session.
Applied by tools/build-d3d11-dll.sh to its copy of the sources (argument: that d3d11 directory).
Idempotent; fails by name if an anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11") / "d3d11_context_impl.cpp"
MARKER = "madeira-doge: luminance source log"

NS_OLD = "\nnamespace dxmt {\n"
NS_NEW = NS_OLD + """
/* madeira-doge: luminance source log (tools/patch-dxmt-lum-src-log.py) */
inline std::atomic<void *> madeira_lum_input{nullptr};
inline std::atomic<uint32_t> madeira_lum_frame{0};
inline std::atomic<int32_t> madeira_lum_budget{0};
inline std::atomic<uint32_t> madeira_lum_lines{0};
static inline bool
madeira_lum_on() {
  static const bool on = env::getEnvVar("MADEIRA_LUM_SRC_LOG") == "1";
  return on;
}
static inline uint64_t
madeira_lum_id(const void *p) {
  return uint64_t(uintptr_t(p)) & 0xffffff;
}
static inline void *
madeira_lum_ptr(ID3D11View *view) {
  if (!view)
    return nullptr;
  ID3D11Resource *res = nullptr;
  view->GetResource(&res);
  if (res)
    res->Release();
  return res;
}
struct MadeiraLumRes {
  void *res = nullptr;
  UINT w = 0, h = 0, fmt = 0;
};
static inline MadeiraLumRes
madeira_lum_res(ID3D11View *view) {
  MadeiraLumRes r;
  if (!view)
    return r;
  ID3D11Resource *res = nullptr;
  view->GetResource(&res);
  if (!res)
    return r;
  r.res = res;
  ID3D11Texture2D *tex = nullptr;
  if (SUCCEEDED(res->QueryInterface(__uuidof(ID3D11Texture2D), reinterpret_cast<void **>(&tex))) && tex) {
    D3D11_TEXTURE2D_DESC desc;
    tex->GetDesc(&desc);
    r.w = desc.Width;
    r.h = desc.Height;
    r.fmt = UINT(desc.Format);
    tex->Release();
  }
  res->Release();
  return r;
}
"""

DISPATCH_OLD = """  Dispatch(UINT ThreadGroupCountX, UINT ThreadGroupCountY, UINT ThreadGroupCountZ) override {
    std::lock_guard<mutex_t> lock(mutex);

    if (!PreDispatch())
      return;
"""
DISPATCH_NEW = DISPATCH_OLD + """    /* madeira-doge: luminance source log */
    if (madeira_lum_on()) {
      auto &lum_stage = state_.ShaderStages[PipelineStage::Compute];
      if (ThreadGroupCountX == 4 && ThreadGroupCountY == 135 && lum_stage.SRVs.test_bound(0)) {
        MadeiraLumRes lum_in = madeira_lum_res(lum_stage.SRVs[0].SRV.ptr());
        madeira_lum_input.store(lum_in.res);
        madeira_lum_budget.store(8);
        uint32_t lum_f = madeira_lum_frame.fetch_add(1) + 1;
        if (madeira_lum_lines.fetch_add(1) < 40000)
          ERR("[lum-in] #", lum_f, " res ", madeira_lum_id(lum_in.res), " ", lum_in.w, "x", lum_in.h, " fmt ",
              lum_in.fmt);
      } else if (void *lum_want = madeira_lum_input.load()) {
        if (madeira_lum_budget.load() > 0) {
          for (const auto &[lum_slot, lum_entry] : state_.ComputeStageUAV.UAVs) {
            if (madeira_lum_ptr(lum_entry.View.ptr()) != lum_want)
              continue;
            madeira_lum_budget.fetch_sub(1);
            MadeiraLumRes lum_s[4];
            for (unsigned lum_i = 0; lum_i < 4; lum_i++)
              if (lum_stage.SRVs.test_bound(lum_i))
                lum_s[lum_i] = madeira_lum_res(lum_stage.SRVs[lum_i].SRV.ptr());
            if (madeira_lum_lines.fetch_add(1) < 40000)
              ERR("[lum-src] cs grp ", ThreadGroupCountX, "x", ThreadGroupCountY, " uav ", lum_slot, " cs ",
                  madeira_lum_id(lum_stage.Shader.ptr()), " srv0 ", madeira_lum_id(lum_s[0].res), " ", lum_s[0].w, "x",
                  lum_s[0].h, " f", lum_s[0].fmt, " srv1 ", madeira_lum_id(lum_s[1].res), " ", lum_s[1].w, "x",
                  lum_s[1].h, " f", lum_s[1].fmt, " srv2 ", madeira_lum_id(lum_s[2].res), " ", lum_s[2].w, "x",
                  lum_s[2].h, " f", lum_s[2].fmt, " srv3 ", madeira_lum_id(lum_s[3].res), " ", lum_s[3].w, "x",
                  lum_s[3].h, " f", lum_s[3].fmt);
            break;
          }
        }
      }
    }
"""

DRAW_OLD = """    /* ml1254: draw census */
    g_perf.draws.fetch_add(1, std::memory_order_relaxed);
"""
DRAW_NEW = DRAW_OLD + """    /* madeira-doge: luminance source log */
    if (madeira_lum_on()) {
      void *lum_want = madeira_lum_input.load(std::memory_order_relaxed);
      if (lum_want && madeira_lum_budget.load(std::memory_order_relaxed) > 0) {
        for (UINT lum_r = 0; lum_r < state_.OutputMerger.NumRTVs && lum_r < 8; lum_r++) {
          if (madeira_lum_ptr(state_.OutputMerger.RTVs[lum_r].ptr()) != lum_want)
            continue;
          madeira_lum_budget.fetch_sub(1);
          auto &lum_ps = state_.ShaderStages[PipelineStage::Pixel];
          MadeiraLumRes lum_s[4];
          for (unsigned lum_i = 0; lum_i < 4; lum_i++)
            if (lum_ps.SRVs.test_bound(lum_i))
              lum_s[lum_i] = madeira_lum_res(lum_ps.SRVs[lum_i].SRV.ptr());
          if (madeira_lum_lines.fetch_add(1) < 40000)
            ERR("[lum-src] draw rtv ", lum_r, " of ", state_.OutputMerger.NumRTVs, " ps ",
                madeira_lum_id(lum_ps.Shader.ptr()), " srv0 ", madeira_lum_id(lum_s[0].res), " ", lum_s[0].w, "x",
                lum_s[0].h, " f", lum_s[0].fmt, " srv1 ", madeira_lum_id(lum_s[1].res), " ", lum_s[1].w, "x",
                lum_s[1].h, " f", lum_s[1].fmt, " srv2 ", madeira_lum_id(lum_s[2].res), " ", lum_s[2].w, "x",
                lum_s[2].h, " f", lum_s[2].fmt, " srv3 ", madeira_lum_id(lum_s[3].res), " ", lum_s[3].w, "x",
                lum_s[3].h, " f", lum_s[3].fmt);
          break;
        }
      }
    }
"""

COPY_OLD = """    std::lock_guard<mutex_t> lock(mutex);

    BlitObject Dst(device, pDstResource);
    BlitObject Src(device, pSrcResource);
"""
COPY_NEW = """    std::lock_guard<mutex_t> lock(mutex);

    /* madeira-doge: luminance source log */
    if (madeira_lum_on() && pDstResource && static_cast<void *>(pDstResource) == madeira_lum_input.load() &&
        madeira_lum_lines.fetch_add(1) < 40000)
      ERR("[lum-src] copy (CopyResource) from ", madeira_lum_id(pSrcResource));

    BlitObject Dst(device, pDstResource);
    BlitObject Src(device, pSrcResource);
"""

REGION_OLD = """    CopySubresourceRegion1(pDstResource, DstSubresource, DstX, DstY, DstZ, pSrcResource, SrcSubresource, pSrcBox, 0);
"""
REGION_NEW = """    /* madeira-doge: luminance source log */
    if (madeira_lum_on() && pDstResource && static_cast<void *>(pDstResource) == madeira_lum_input.load() &&
        madeira_lum_lines.fetch_add(1) < 40000)
      ERR("[lum-src] copy (CopySubresourceRegion) from ", madeira_lum_id(pSrcResource));
""" + REGION_OLD

INC_OLD = '#include "dxmt_staging.hpp"\n'
INC_NEW = '#include "dxmt_staging.hpp"\n#include "util_env.hpp" /* madeira-doge: luminance source log */\n#include <cstdint>\n'

PAIRS = [("namespace dxmt", NS_OLD, NS_NEW), ("Dispatch", DISPATCH_OLD, DISPATCH_NEW), ("draw census", DRAW_OLD, DRAW_NEW),
         ("CopyResource", COPY_OLD, COPY_NEW), ("CopySubresourceRegion", REGION_OLD, REGION_NEW),
         ("dxmt_staging include", INC_OLD, INC_NEW)]


def main():
    src = PATH.read_text()
    if MARKER in src:
        print("lum-src log: already applied")
        return 0
    for name, old, _ in PAIRS:
        if src.count(old) != 1:
            print(f"lum-src log: anchor '{name}' found {src.count(old)} times in {PATH}", file=sys.stderr)
            return 1
    for _, old, new in PAIRS:
        src = src.replace(old, new)
    PATH.write_text(src)
    print("lum-src log: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
