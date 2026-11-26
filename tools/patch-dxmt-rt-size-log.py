#!/usr/bin/env python3
"""Log the sizes of the render targets and depth buffers a Direct3D 11 game creates.

God of War at 1120x630 (build 712) costs the GPU as much per frame as at 1280x720 (45 against 46 ms in scenes of
1000-2000 draws; 38 ms at 960x540), and no log line says what size the game renders at. This prints each distinct
width x height x format x bind flags of a texture created with D3D11_BIND_RENDER_TARGET or D3D11_BIND_DEPTH_STENCIL,
once, up to 64 lines: [rt-size] WxH fmt F bind B mips M samples S (bind 32 = render target, 64 = depth).

Applied by tools/build-d3d11-dll.sh to its copy of the sources (argument: that d3d11 directory). Source-built d3d11
only (env.MADEIRA_D3D11_SRC = 1). Read-only, no behaviour change. Idempotent; fails by name if the anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11") / "d3d11_device.cpp"
MARKER = "madeira-doge: rt size log"

OLD = """    BCCensusRecord(pDesc, pInitialData);   /* ml652: read-only, no behaviour change */
"""
NEW = OLD + """    /* madeira-doge: rt size log (tools/patch-dxmt-rt-size-log.py) */
    if (pDesc->BindFlags & (D3D11_BIND_RENDER_TARGET | D3D11_BIND_DEPTH_STENCIL)) {
      static std::mutex rt_log_mutex;
      static uint64_t rt_log_seen[64];
      static uint32_t rt_log_count;
      const uint64_t rt_key = ((uint64_t)(pDesc->Width & 0xffff) << 48) | ((uint64_t)(pDesc->Height & 0xffff) << 32) |
                              ((uint64_t)((uint32_t)pDesc->Format & 0xffff) << 16) |
                              (uint64_t)(pDesc->BindFlags & 0xffff);
      bool rt_new = false;
      {
        std::lock_guard<std::mutex> rt_lock(rt_log_mutex);
        uint32_t rt_i = 0;
        while (rt_i < rt_log_count && rt_log_seen[rt_i] != rt_key)
          rt_i++;
        if (rt_i == rt_log_count && rt_log_count < 64) {
          rt_log_seen[rt_log_count++] = rt_key;
          rt_new = true;
        }
      }
      if (rt_new)
        ERR("[rt-size] ", pDesc->Width, "x", pDesc->Height, " fmt ", (uint32_t)pDesc->Format, " bind ",
            (uint32_t)pDesc->BindFlags, " mips ", pDesc->MipLevels, " samples ", pDesc->SampleDesc.Count);
    }
"""


def main():
    s = PATH.read_text()
    if MARKER in s:
        print(f"{PATH}: already patched")
        return
    if s.count(OLD) != 1:
        sys.exit(f"patch-dxmt-rt-size-log: BCCensusRecord anchor found {s.count(OLD)} times in {PATH}")
    s = s.replace(OLD, NEW)
    PATH.write_text(s)
    print(f"{PATH}: rt size log added")


if __name__ == "__main__":
    main()
