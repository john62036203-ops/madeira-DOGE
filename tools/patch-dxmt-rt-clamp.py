#!/usr/bin/env python3
"""Render passes on a large target cover only what their viewports reach.

God of War draws its shadows into a 512x512 viewport of an 8192x4096 depth atlas, load/store, twice a frame (2,100 draws,
[gpu-trace] 2026-11-20). DXMT gives Metal the whole attachment as the render target, so a tile-based GPU may load and
store all of it for a pass that touches 1 % of it. env.MADEIRA_RT_CLAMP = 1: when a render pass's target is at least
4096x2048 pixels, every attachment is loaded (none cleared or undefined) and the pass sets its viewports itself, the
render target is cut down to the bounding box of those viewports from the origin (rounded up to 64). Rasterisation never
leaves a viewport, so the picture is the same; only the area Metal handles shrinks. `[rt-clamp]` logs the first 8 passes
cut and a count every 4096.

Applied by tools/build-d3d11-dll.sh to its copy of dxmt_context.cpp (argument: that dxmt directory). Source-built d3d11
only (env.MADEIRA_D3D11_SRC = 1). Idempotent; fails by name if the anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/dxmt") / "dxmt_context.cpp"
MARKER = "madeira-doge: rt clamp"

OLD = """        render_pass_info.render_target_width = data->render_target_width;
        render_pass_info.render_target_height = data->render_target_height;
"""
NEW = OLD + """        /* madeira-doge: rt clamp (tools/patch-dxmt-rt-clamp.py) */
        {
          static const bool madeira_rt_clamp = env::getEnvVar("MADEIRA_RT_CLAMP") == "1";
          const uint32_t full_w = data->render_target_width, full_h = data->render_target_height;
          if (madeira_rt_clamp && (uint64_t)full_w * full_h >= 4096ull * 2048ull) {
            bool loaded = true;
            for (unsigned i = 0; i < data->render_target_count; i++)
              if (data->colors[i].attachment && data->colors[i].load_action != WMTLoadActionLoad)
                loaded = false;
            if (data->depth.attachment && data->depth.load_action != WMTLoadActionLoad)
              loaded = false;
            if (data->stencil.attachment && data->stencil.load_action != WMTLoadActionLoad)
              loaded = false;
            double max_x = 0, max_y = 0;
            unsigned viewports = 0;
            bool sane = true;
            auto reach = [&](const WMTViewport &v) {
              const double x1 = v.originX + v.width, y1 = v.originY + v.height;
              if (!(v.originX >= 0) || !(v.originY >= 0) || !(v.width > 0) || !(v.height > 0) || !(x1 < 65536) ||
                  !(y1 < 65536)) {
                sane = false;
                return;
              }
              if (x1 > max_x) max_x = x1;
              if (y1 > max_y) max_y = y1;
              viewports++;
            };
            if (loaded) {
              for (auto *c = (const wmtcmd_base *)data->cmd_head.next.ptr; c;
                   c = (const wmtcmd_base *)c->next.ptr) {
                if (c->type == WMTRenderCommandSetViewport) {
                  reach(((const wmtcmd_render_setviewport *)c)->viewport);
                } else if (c->type == WMTRenderCommandSetViewports) {
                  auto *m = (const wmtcmd_render_setviewports *)c;
                  auto *v = (const WMTViewport *)m->viewports.ptr;
                  if (!v || !m->viewport_count)
                    sane = false;
                  else
                    for (unsigned i = 0; i < m->viewport_count; i++)
                      reach(v[i]);
                }
              }
            }
            if (loaded && sane && viewports) {
              const uint32_t w = std::min<uint32_t>(full_w, ((uint32_t)max_x + 63u + (max_x > (uint32_t)max_x)) & ~63u);
              const uint32_t h = std::min<uint32_t>(full_h, ((uint32_t)max_y + 63u + (max_y > (uint32_t)max_y)) & ~63u);
              if (w && h && (w < full_w || h < full_h)) {
                static std::atomic<uint32_t> cut{0};
                const uint32_t n = cut.fetch_add(1, std::memory_order_relaxed);
                render_pass_info.render_target_width = w;
                render_pass_info.render_target_height = h;
                if (n < 8 || (n & 4095) == 0)
                  fprintf(stderr, "[rt-clamp] madeira-doge #%u render target %ux%u -> %ux%u (%u viewport sets)\\n", n,
                          full_w, full_h, w, h, viewports);
              }
            }
          }
        }
"""


def main():
    src = PATH.read_text()
    if MARKER in src:
        print("rt-clamp: already applied")
        return 0
    if src.count(OLD) != 1:
        print(f"rt-clamp: anchor found {src.count(OLD)} times in {PATH}", file=sys.stderr)
        return 1
    src = src.replace(OLD, NEW)
    if "#include <cstdio>" not in src:
        src = src.replace('#include "dxmt_context.hpp"\n', '#include "dxmt_context.hpp"\n#include <cstdio>\n', 1)
    PATH.write_text(src)
    print("rt-clamp: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
