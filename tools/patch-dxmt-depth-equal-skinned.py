#!/usr/bin/env python3
"""Tolerant depth-equal test for skinned draws only (God of War: blocks around foliage against the sky).

tools/patch-dxmt-depth-equal-remap.py turns the game's one depth EQUAL state into GREATER_EQUAL plus a depth bias,
which removes the one-pixel holes on characters (pre-pass and main pass disagree in the last bits of depth). The owner
found (2026-11-26, build 714) that with it on, trees against the sky get blocks of wrong colour, and with it off the
blocks go and the dots on characters return. Alpha-tested foliage is cut out in the depth pre-pass only; the main pass
relies on EQUAL to reject the cut-out pixels, and GREATER_EQUAL lets them through (they are nearer than the sky).

env.MADEIRA_DEPTH_EQUAL_SKINNED = 1 (with MADEIRA_DEPTH_EQUAL_FUNC and _BIAS as before): the remapped comparison and
the bias are used only while the bound input layout has a BLENDINDICES or BLENDWEIGHT element (skinned meshes); every
other draw gets the game's own EQUAL. Whether God of War's characters use such layouts is not known: the log says.

  [deq] layout #n skinned <0|1>: <semantic names>      first 64 input layouts created
  [deq] equal-state binds: tolerant <a> strict <b>     every 20000 binds of the EQUAL state

Applied by tools/build-d3d11-dll.sh AFTER tools/patch-dxmt-depth-equal-remap.py (argument: that d3d11 directory).
Source-built d3d11 only (env.MADEIRA_D3D11_SRC = 1). Idempotent; fails by name if an anchor moved.
"""
import pathlib
import sys

DIR = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11")
HDR = DIR / "madeira_deq.hpp"
SO = DIR / "d3d11_state_object.cpp"
IMPL = DIR / "d3d11_context_impl.cpp"
DEV = DIR / "d3d11_device.cpp"
MARKER = "madeira-doge: depth equal skinned"

HEADER = """#pragma once
/* madeira-doge: depth equal skinned (tools/patch-dxmt-depth-equal-skinned.py) */
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include "util_env.hpp"

namespace madeira_deq {

inline bool skinned_only() {
  static const bool on = ::dxmt::env::getEnvVar("MADEIRA_DEPTH_EQUAL_SKINNED") == "1";
  return on;
}

inline std::atomic<const void *> g_layouts[256];
inline std::atomic<uint32_t> g_layout_count{0};
inline std::mutex g_layout_mutex;

inline void add_skinned_layout(const void *layout) {
  std::lock_guard<std::mutex> lock(g_layout_mutex);
  const uint32_t n = g_layout_count.load(std::memory_order_relaxed);
  for (uint32_t i = 0; i < n; i++)
    if (g_layouts[i].load(std::memory_order_relaxed) == layout)
      return;
  if (n < 256) {
    g_layouts[n].store(layout, std::memory_order_relaxed);
    g_layout_count.store(n + 1, std::memory_order_release);
  }
}

inline bool is_skinned_layout(const void *layout) {
  if (!layout)
    return false;
  const uint32_t n = g_layout_count.load(std::memory_order_acquire);
  for (uint32_t i = 0; i < n; i++)
    if (g_layouts[i].load(std::memory_order_relaxed) == layout)
      return true;
  return false;
}

/* case-insensitive: does `s` start with `prefix` (upper-case ASCII)? */
inline bool has_prefix(const char *s, const char *prefix) {
  for (; *prefix; s++, prefix++) {
    char c = *s;
    if (c >= 'a' && c <= 'z')
      c = char(c - 'a' + 'A');
    if (c != *prefix)
      return false;
  }
  return true;
}

inline std::atomic<uint32_t> g_binds_tolerant{0};
inline std::atomic<uint32_t> g_binds_strict{0};

} // namespace madeira_deq
"""

# --- d3d11_state_object.cpp -------------------------------------------------------------------------------------
SO_INC_OLD = '#include "log/log.hpp"\n'
SO_INC_NEW = '#include "log/log.hpp"\n#include "madeira_deq.hpp" /* madeira-doge: depth equal skinned */\n'

SO_GET_OLD = """  virtual WMT::DepthStencilState GetDepthStencilState(uint32_t planar_flags) {
    switch (planar_flags) {
"""
SO_GET_NEW = """  /* madeira-doge: depth equal skinned -- the game's own comparison, asked for with bit 0x100 */
  void MadeiraSetStrict(WMT::DepthStencilState strict_default, WMT::DepthStencilState strict_nostencil) {
    madeira_strict_default_ = strict_default;
    madeira_strict_nostencil_ = strict_nostencil;
    madeira_has_strict_ = true;
  }

  virtual WMT::DepthStencilState GetDepthStencilState(uint32_t planar_flags) {
    if (planar_flags & 0x100u) {
      planar_flags &= 0xffu;
      if (madeira_has_strict_) {
        if (planar_flags == 1)
          return madeira_strict_nostencil_;
        if (planar_flags >= 2)
          return madeira_strict_default_;
      }
    }
    switch (planar_flags) {
"""

SO_MEM_OLD = """  WMT::Reference<WMT::DepthStencilState> state_depthstencil_disabled_;
};
"""
SO_MEM_NEW = """  WMT::Reference<WMT::DepthStencilState> state_depthstencil_disabled_;
  WMT::Reference<WMT::DepthStencilState> madeira_strict_default_;
  WMT::Reference<WMT::DepthStencilState> madeira_strict_nostencil_;
  bool madeira_has_strict_ = false;
};
"""

SO_INFO_OLD = """  auto state_default = device->GetMTLDevice().newDepthStencilState(info);
"""
SO_INFO_NEW = """  const WMTDepthStencilInfo madeira_info0 = info; /* madeira-doge: depth equal skinned */
  auto state_default = device->GetMTLDevice().newDepthStencilState(info);
"""

SO_END_OLD = """  cache.at(*pDesc)->QueryInterface(IID_PPV_ARGS(ppDepthStencilState));
  return S_OK;
}
"""
SO_END_NEW = """  /* madeira-doge: depth equal skinned */
  if (madeira_deq::skinned_only() && pDesc->DepthEnable && pDesc->DepthFunc == D3D11_COMPARISON_EQUAL) {
    WMTDepthStencilInfo madeira_info_s = madeira_info0;
    madeira_info_s.depth_compare_function = kCompareFunctionMap[D3D11_COMPARISON_EQUAL];
    auto madeira_strict_default = device->GetMTLDevice().newDepthStencilState(madeira_info_s);
    madeira_info_s.front_stencil.enabled = false;
    madeira_info_s.back_stencil.enabled = false;
    auto madeira_strict_nostencil = device->GetMTLDevice().newDepthStencilState(madeira_info_s);
    static_cast<MTLD3D11DepthStencilState *>(cache.at(*pDesc).get())
        ->MadeiraSetStrict(madeira_strict_default, madeira_strict_nostencil);
  }
  cache.at(*pDesc)->QueryInterface(IID_PPV_ARGS(ppDepthStencilState));
  return S_OK;
}
"""

# --- d3d11_context_impl.cpp -------------------------------------------------------------------------------------
IMPL_INC_OLD = '#include "dxmt_staging.hpp"\n'
IMPL_INC_NEW = '#include "dxmt_staging.hpp"\n#include "madeira_deq.hpp" /* madeira-doge: depth equal skinned */\n'

IMPL_IL_OLD = """      state_.InputAssembler.InputLayout = nullptr;
    }
    InvalidateRenderPipeline();
"""
IMPL_IL_NEW = IMPL_IL_OLD + """    if (madeira_deq::skinned_only()) /* madeira-doge: depth equal skinned */
      dirty_state.set(DirtyState::DepthStencilState);
"""

IMPL_DSS_OLD = """      EmitST([state, stencil_ref = state_.OutputMerger.StencilRef](ArgumentEncodingContext& enc) {
        auto encoder = enc.currentRenderEncoder();
        auto &cmd = enc.encodeRenderCommand<wmtcmd_render_setdsso>();
        cmd.type = WMTRenderCommandSetDSSO;
        cmd.dsso = state->GetDepthStencilState(encoder->dsv_planar_flags);
"""
IMPL_DSS_NEW = """      /* madeira-doge: depth equal skinned */
      uint32_t madeira_strict = 0;
      if (madeira_deq::skinned_only()) {
        D3D11_DEPTH_STENCIL_DESC madeira_desc;
        state->GetDesc(&madeira_desc);
        if (madeira_desc.DepthEnable && madeira_desc.DepthFunc == D3D11_COMPARISON_EQUAL) {
          const bool madeira_skinned = madeira_deq::is_skinned_layout(state_.InputAssembler.InputLayout.ptr());
          madeira_strict = madeira_skinned ? 0u : 0x100u;
          const uint32_t madeira_a = madeira_skinned ? ++madeira_deq::g_binds_tolerant : madeira_deq::g_binds_tolerant.load();
          const uint32_t madeira_b = madeira_skinned ? madeira_deq::g_binds_strict.load() : ++madeira_deq::g_binds_strict;
          if (((madeira_a + madeira_b) % 20000u) == 0)
            ERR("[deq] equal-state binds: tolerant ", madeira_a, " strict ", madeira_b);
        }
      }
      EmitST([state, madeira_strict, stencil_ref = state_.OutputMerger.StencilRef](ArgumentEncodingContext& enc) {
        auto encoder = enc.currentRenderEncoder();
        auto &cmd = enc.encodeRenderCommand<wmtcmd_render_setdsso>();
        cmd.type = WMTRenderCommandSetDSSO;
        cmd.dsso = state->GetDepthStencilState(encoder->dsv_planar_flags | madeira_strict);
"""

IMPL_BIAS_OLD = """        if (eq_desc.DepthEnable && eq_desc.DepthFunc == D3D11_COMPARISON_EQUAL)
          eq_bias = madeira_eq_bias;
"""
IMPL_BIAS_NEW = """        if (eq_desc.DepthEnable && eq_desc.DepthFunc == D3D11_COMPARISON_EQUAL &&
            (!madeira_deq::skinned_only() || /* madeira-doge: depth equal skinned */
             madeira_deq::is_skinned_layout(state_.InputAssembler.InputLayout.ptr())))
          eq_bias = madeira_eq_bias;
"""

# --- d3d11_device.cpp -------------------------------------------------------------------------------------------
DEV_INC_OLD = '#include "d3d11_resource.hpp"\n'
DEV_INC_NEW = '#include "d3d11_resource.hpp"\n#include "madeira_deq.hpp" /* madeira-doge: depth equal skinned */\n'

DEV_OLD = """    return pipeline_cache_->AddInputLayout(
        pShaderBytecodeWithInputSignature, pInputElementDescs, NumElements,
        (IMTLD3D11InputLayout **)ppInputLayout);
"""
DEV_NEW = """    /* madeira-doge: depth equal skinned (tools/patch-dxmt-depth-equal-skinned.py) */
    const HRESULT madeira_il_hr = pipeline_cache_->AddInputLayout(
        pShaderBytecodeWithInputSignature, pInputElementDescs, NumElements,
        (IMTLD3D11InputLayout **)ppInputLayout);
    if (SUCCEEDED(madeira_il_hr) && *ppInputLayout && madeira_deq::skinned_only()) {
      static std::atomic<uint32_t> madeira_il_n{0};
      bool madeira_skinned = false;
      std::string madeira_names;
      for (UINT i = 0; i < NumElements; i++) {
        const char *madeira_sem = pInputElementDescs[i].SemanticName ? pInputElementDescs[i].SemanticName : "?";
        if (madeira_deq::has_prefix(madeira_sem, "BLENDINDICES") || madeira_deq::has_prefix(madeira_sem, "BLENDWEIGHT"))
          madeira_skinned = true;
        if (madeira_names.size() < 200) {
          madeira_names += madeira_sem;
          madeira_names += std::to_string(pInputElementDescs[i].SemanticIndex);
          madeira_names += ' ';
        }
      }
      if (madeira_skinned)
        madeira_deq::add_skinned_layout(*ppInputLayout);
      if (++madeira_il_n <= 64)
        ERR("[deq] layout #", madeira_il_n.load(), " skinned ", uint32_t(madeira_skinned), ": ", madeira_names);
    }
    return madeira_il_hr;
"""

EDITS = [
    (SO, [("log include", SO_INC_OLD, SO_INC_NEW), ("GetDepthStencilState", SO_GET_OLD, SO_GET_NEW),
          ("state members", SO_MEM_OLD, SO_MEM_NEW), ("state_default", SO_INFO_OLD, SO_INFO_NEW),
          ("create end", SO_END_OLD, SO_END_NEW)]),
    (IMPL, [("dxmt_staging include", IMPL_INC_OLD, IMPL_INC_NEW), ("IASetInputLayout", IMPL_IL_OLD, IMPL_IL_NEW),
            ("set dsso", IMPL_DSS_OLD, IMPL_DSS_NEW), ("equal bias", IMPL_BIAS_OLD, IMPL_BIAS_NEW)]),
    (DEV, [("d3d11_resource include", DEV_INC_OLD, DEV_INC_NEW), ("AddInputLayout", DEV_OLD, DEV_NEW)]),
]


def main():
    texts = {}
    for path, edits in EDITS:
        src = path.read_text()
        if MARKER in src:
            print(f"depth equal skinned: {path.name} already patched")
            texts[path] = None
            continue
        for name, old, _new in edits:
            if src.count(old) != 1:
                print(f"depth equal skinned: anchor '{name}' found {src.count(old)} times in {path}", file=sys.stderr)
                return 1
        for _name, old, new in edits:
            src = src.replace(old, new)
        texts[path] = src
    for path, src in texts.items():
        if src is not None:
            path.write_text(src)
    HDR.write_text(HEADER)
    print("depth equal skinned: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
