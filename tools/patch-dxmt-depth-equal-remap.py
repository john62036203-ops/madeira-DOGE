#!/usr/bin/env python3
"""Log the depth-stencil states a game creates, and optionally remap depth EQUAL to another comparison.

God of War (2026-11-20): characters have one-pixel holes that show the background; a traced frame has a 469-draw
depth-only pass followed by a 469-draw G-buffer pass on the same depth target. If the G-buffer pass tests depth EQUAL,
positions that differ in the last bit between the two passes leave such holes. MADEIRA_DEFUSE_FMA (build 653) did not
remove them, so this measures instead of guessing:

  env.MADEIRA_DSS_LOG = 1            [dss] #n depth <enable> write <mask> func <D3D11_COMPARISON 1..8> stencil <enable> remapped-to <n or 0>
                                     for the first 96 depth-stencil states created
  env.MADEIRA_DEPTH_EQUAL_FUNC = n   (1..8; also turns the log on) a state whose DepthFunc is EQUAL (3) is created
                                     with comparison n instead: 4 LESS_EQUAL, 7 GREATER_EQUAL, 8 ALWAYS

  env.MADEIRA_DEPTH_EQUAL_BIAS = b   (float, Metal depth-bias units = last-bit steps of the depth value) added to the
                                     rasterizer depth bias of every draw whose depth test is (was) EQUAL. With a
                                     reversed-Z game (God of War: its other states use GREATER) EQUAL_FUNC = 7 plus a
                                     positive bias makes the main pass accept a pixel within b steps of the pre-pass.

An experiment: ALWAYS draws hidden surfaces over nearer ones where the game relied on EQUAL, so it is for a look at
whether the holes go away, not for play. Applied by tools/build-d3d11-dll.sh to its copy of the sources (argument: that
d3d11 directory). Source-built d3d11 only (env.MADEIRA_D3D11_SRC = 1). Idempotent; fails by name if an anchor moved.
"""
import pathlib
import sys

DIR = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11")
PATH = DIR / "d3d11_state_object.cpp"
IMPL = DIR / "d3d11_context_impl.cpp"
MARKER = "madeira-doge: depth equal remap"

OLD = """    info.depth_compare_function = kCompareFunctionMap[pDesc->DepthFunc];
    info.depth_write_enabled = pDesc->DepthWriteMask == D3D11_DEPTH_WRITE_MASK_ALL;
  } 
"""
NEW = OLD + """  /* madeira-doge: depth equal remap (tools/patch-dxmt-depth-equal-remap.py) */
  {
    static const int dss_remap = [] {
      const std::string v = ::dxmt::env::getEnvVar("MADEIRA_DEPTH_EQUAL_FUNC");
      const int n = v.empty() ? 0 : atoi(v.c_str());
      return (n >= 1 && n <= 8) ? n : 0;
    }();
    static const bool dss_log = dss_remap || ::dxmt::env::getEnvVar("MADEIRA_DSS_LOG") == "1";
    static uint32_t dss_n;
    const bool dss_hit = dss_remap && pDesc->DepthEnable && pDesc->DepthFunc == D3D11_COMPARISON_EQUAL;
    if (dss_log && ++dss_n <= 96)
      ERR("[dss] #", dss_n, " depth ", uint32_t(pDesc->DepthEnable), " write ", uint32_t(pDesc->DepthWriteMask),
          " func ", uint32_t(pDesc->DepthFunc), " stencil ", uint32_t(pDesc->StencilEnable),
          " remapped-to ", dss_hit ? dss_remap : 0);
    if (dss_hit)
      info.depth_compare_function = kCompareFunctionMap[dss_remap];
  }
"""
INC_OLD = '#include "log/log.hpp"\n'
INC_NEW = '#include "log/log.hpp"\n#include "util_env.hpp" /* madeira-doge: depth equal remap */\n#include <cstdint>\n#include <cstdlib>\n#include <string>\n'


RS_OLD = """    if (dirty_state.any(DirtyState::RasterizerState)) {
      IMTLD3D11RasterizerState *state =
          state_.Rasterizer.RasterizerState ? state_.Rasterizer.RasterizerState : default_rasterizer_state;
      EmitST([state](ArgumentEncodingContext& enc) {
        auto &cmd = enc.encodeRenderCommand<wmtcmd_render_setrasterizerstate>();
        cmd.type = WMTRenderCommandSetRasterizerState;
        state->SetupRasterizerState(cmd);
      });
    }
"""
RS_NEW = """    /* madeira-doge: depth equal remap -- MADEIRA_DEPTH_EQUAL_BIAS (tools/patch-dxmt-depth-equal-remap.py) */
    static const float madeira_eq_bias = [] {
      const std::string v = ::dxmt::env::getEnvVar("MADEIRA_DEPTH_EQUAL_BIAS");
      return v.empty() ? 0.0f : float(atof(v.c_str()));
    }();
    if (dirty_state.any(DirtyState::RasterizerState) ||
        (madeira_eq_bias != 0.0f && dirty_state.any(DirtyState::DepthStencilState))) {
      IMTLD3D11RasterizerState *state =
          state_.Rasterizer.RasterizerState ? state_.Rasterizer.RasterizerState : default_rasterizer_state;
      float eq_bias = 0.0f;
      if (madeira_eq_bias != 0.0f) {
        IMTLD3D11DepthStencilState *eq_dss =
            state_.OutputMerger.DepthStencilState ? state_.OutputMerger.DepthStencilState : default_depth_stencil_state;
        D3D11_DEPTH_STENCIL_DESC eq_desc;
        eq_dss->GetDesc(&eq_desc);
        if (eq_desc.DepthEnable && eq_desc.DepthFunc == D3D11_COMPARISON_EQUAL)
          eq_bias = madeira_eq_bias;
      }
      EmitST([state, eq_bias](ArgumentEncodingContext& enc) {
        auto &cmd = enc.encodeRenderCommand<wmtcmd_render_setrasterizerstate>();
        cmd.type = WMTRenderCommandSetRasterizerState;
        state->SetupRasterizerState(cmd);
        cmd.depth_bias += eq_bias;
      });
    }
"""
IMPL_INC_OLD = '#include "dxmt_staging.hpp"\n'
IMPL_INC_NEW = '#include "dxmt_staging.hpp"\n#include "util_env.hpp" /* madeira-doge: depth equal remap */\n#include <cstdlib>\n#include <string>\n'


def impl():
    src = IMPL.read_text()
    if "MADEIRA_DEPTH_EQUAL_BIAS" in src:
        print("depth equal bias: already applied")
        return 0
    for name, old in (("rasterizer state", RS_OLD), ("dxmt_staging include", IMPL_INC_OLD)):
        if src.count(old) != 1:
            print(f"depth equal bias: anchor '{name}' found {src.count(old)} times in {IMPL}", file=sys.stderr)
            return 1
    IMPL.write_text(src.replace(RS_OLD, RS_NEW).replace(IMPL_INC_OLD, IMPL_INC_NEW))
    print("depth equal bias: applied")
    return 0


def main():
    if impl():
        return 1
    src = PATH.read_text()
    if MARKER in src:
        print("depth equal remap: already applied")
        return 0
    for name, old in (("depth compare", OLD), ("log include", INC_OLD)):
        if src.count(old) != 1:
            print(f"depth equal remap: anchor '{name}' found {src.count(old)} times in {PATH}", file=sys.stderr)
            return 1
    PATH.write_text(src.replace(OLD, NEW).replace(INC_OLD, INC_NEW))
    print("depth equal remap: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
