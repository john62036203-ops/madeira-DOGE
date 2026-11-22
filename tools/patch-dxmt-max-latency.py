#!/usr/bin/env python3
"""Fewer frames queued ahead of the display (env.MADEIRA_D3D11_MAX_LATENCY = 1 or 2; opt-in).

DXMT lets the game run up to three frames ahead of the GPU (CommandQueue::max_latency_ = 3, Direct3D's default
"maximum frame latency"): after presenting frame N the game waits only for frame N-3 to finish. When the GPU is the
limit (God of War here: 18 fps, 55 ms a frame, GPU 90-100 % busy) the picture on screen is then up to three frames,
about 0.15 s, behind the game and its sound, which plays at once (owner's report 2026-11-22: sound first, picture
after, by a constant amount).

env.MADEIRA_D3D11_MAX_LATENCY = 1 or 2 sets that limit at every Present (so a game's own SetMaximumFrameLatency does
not undo it): the game waits for frame N-1 (or N-2) before going on. The frame rate of a GPU-bound game is the same;
a CPU-bound game may lose some, as the CPU can no longer work ahead. Unset or any other value: nothing is changed,
the limit stays what DXMT or the game set. `[max-latency]` is logged once.

Applied by tools/build-d3d11-dll.sh to its copy of d3d11_swapchain.cpp (argument: that d3d11 directory). Source-built
d3d11 only (env.MADEIRA_D3D11_SRC = 1). Idempotent; fails by name if the anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11") / "d3d11_swapchain.cpp"
MARKER = "madeira-doge: max latency"

OLD = """    lock.unlock(); // since PresentBoundary() will and should only stall current thread

    cmd_queue.PresentBoundary();
"""
NEW = """    lock.unlock(); // since PresentBoundary() will and should only stall current thread

    /* madeira-doge: max latency (tools/patch-dxmt-max-latency.py) */
    {
      static const uint32_t madeira_max_latency = [] {
        const std::string v = env::getEnvVar("MADEIRA_D3D11_MAX_LATENCY");
        const uint32_t n = v == "1" ? 1u : v == "2" ? 2u : 0u;
        if (n)
          Logger::warn(str::format("[max-latency] madeira-doge: at most ", n, " frame(s) queued ahead of the GPU (MADEIRA_D3D11_MAX_LATENCY)"));
        return n;
      }();
      if (madeira_max_latency && cmd_queue.GetMaxLatency() != madeira_max_latency)
        cmd_queue.SetMaxLatency(madeira_max_latency);
    }
    cmd_queue.PresentBoundary();
"""

src = PATH.read_text()
if MARKER in src:
    print("patch-dxmt-max-latency: already patched")
    sys.exit(0)
if src.count(OLD) != 1:
    sys.exit("patch-dxmt-max-latency: PresentBoundary anchor not found once in d3d11_swapchain.cpp")
PATH.write_text(src.replace(OLD, NEW))
print("patch-dxmt-max-latency: MADEIRA_D3D11_MAX_LATENCY patched")
