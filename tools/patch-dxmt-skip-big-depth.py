#!/usr/bin/env python3
"""Measurement switch: drop the draws of depth-only passes on a large target.

God of War's shadow passes (2,100 of 5,100 draws a frame, an 8192x4096 depth atlas) cannot be switched off in the game.
env.MADEIRA_SKIP_BIG_DEPTH = 1 keeps such a render pass (no colour attachment, target of at least 4096x2048 pixels) but
encodes none of its commands, so the GPU time of that geometry can be read off [gpu-perf]. The shadows stop updating: a
measurement, not a setting to play with. `[skip-big-depth]` logs the first 4 passes and a count every 4096.

Applied by tools/build-d3d11-dll.sh to its copy of dxmt_context.cpp (argument: that dxmt directory). Source-built d3d11
only (env.MADEIRA_D3D11_SRC = 1). Idempotent; fails by name if the anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/dxmt") / "dxmt_context.cpp"
MARKER = "madeira-doge: skip big depth"

OLD = """      encoder.encodeCommands(&data->cmd_head);
      encoder.endEncoding();
      data->~RenderEncoderData();
"""
NEW = """      /* madeira-doge: skip big depth (tools/patch-dxmt-skip-big-depth.py) */
      bool madeira_skip_this_pass = false;
      {
        static const bool madeira_skip_big_depth = env::getEnvVar("MADEIRA_SKIP_BIG_DEPTH") == "1";
        if (madeira_skip_big_depth && data->depth.attachment &&
            (uint64_t)data->render_target_width * data->render_target_height >= 4096ull * 2048ull) {
          bool colour = false;
          for (unsigned i = 0; i < 8; i++)
            if (data->colors[i].attachment)
              colour = true;
          if (!colour) {
            static std::atomic<uint32_t> skipped{0};
            const uint32_t n = skipped.fetch_add(1, std::memory_order_relaxed);
            madeira_skip_this_pass = true;
            if (n < 4 || (n & 4095) == 0)
              fprintf(stderr, "[skip-big-depth] madeira-doge #%u depth-only pass on %ux%u: commands dropped\\n", n,
                      (unsigned)data->render_target_width, (unsigned)data->render_target_height);
          }
        }
      }
      if (!madeira_skip_this_pass)
        encoder.encodeCommands(&data->cmd_head);
      encoder.endEncoding();
      data->~RenderEncoderData();
"""


def main():
    src = PATH.read_text()
    if MARKER in src:
        print("skip-big-depth: already applied")
        return 0
    if src.count(OLD) != 1:
        print(f"skip-big-depth: anchor found {src.count(OLD)} times in {PATH}", file=sys.stderr)
        return 1
    src = src.replace(OLD, NEW)
    if "#include <cstdio>" not in src:
        src = src.replace('#include "dxmt_context.hpp"\n', '#include "dxmt_context.hpp"\n#include <cstdio>\n', 1)
    PATH.write_text(src)
    print("skip-big-depth: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
