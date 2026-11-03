#!/usr/bin/env python3
"""d3d11: encode a failed pipeline as a null SetPSO (opt-in), so winemetal drops its draws.

Ported from steamac (fxgl/steamac host/dxmt/patches 0007, d3d11 part). When a
pipeline fails to compile, d3d11 returned before encoding SetPSO, but the
draws and dispatches queued for it were still encoded: they ran on whatever
pipeline the encoder had bound before, with the failed one's bindings (GPU
faults, garbage). With env MADEIRA_NULL_PSO_SKIP=1 the null pipeline is
encoded (a compute one with a zero threadgroup size) and
tools/patch-winemetal-null-pso.py drops the draws after it. Unset: unchanged.

Applied by tools/build-d3d11-dll.sh to its copy (d3d11-src.dll, env.MADEIRA_D3D11_SRC = 1).

Usage: patch-d3d11src-null-pso.py <tree>/src/d3d11
"""
import os
import sys

path = os.path.join(sys.argv[1], "d3d11_context_impl.cpp")
src = open(path).read()
marker = "madeira-doge: steamac null-pso"
if marker in src:
    print("already patched")
    sys.exit(0)

g_old = "      if (!GraphicsPipeline.PipelineState)\n        return;\n"
g_new = "      if (!GraphicsPipeline.PipelineState && !MadeiraNullPsoSkip())   /* madeira-doge: steamac null-pso (0007) */\n        return;\n"
n = src.count(g_old)
if n < 3:
    sys.exit("patch-d3d11src-null-pso: graphics early returns found %d times (want >= 3)" % n)
src = src.replace(g_old, g_new)

c_old = """      if (!ComputePipeline.PipelineState)
        return;
      auto &cmd = enc.encodeComputeCommand<wmtcmd_compute_setpso>();
      cmd.type = WMTComputeCommandSetPSO;
      cmd.pso = ComputePipeline.PipelineState;
      cmd.threadgroup_size = tg_size;
"""
c_new = """      if (!ComputePipeline.PipelineState && !MadeiraNullPsoSkip())   /* madeira-doge: steamac null-pso (0007) */
        return;
      auto &cmd = enc.encodeComputeCommand<wmtcmd_compute_setpso>();
      cmd.type = WMTComputeCommandSetPSO;
      cmd.pso = ComputePipeline.PipelineState;
      cmd.threadgroup_size = ComputePipeline.PipelineState ? tg_size : WMTSize{0, 0, 0};
"""
if src.count(c_old) != 1:
    sys.exit("patch-d3d11src-null-pso: compute SetPSO block found %d times" % src.count(c_old))
src = src.replace(c_old, c_new)

inc = '#include "d3d11_context_state.hpp"\n'
if src.count(inc) != 1:
    sys.exit("patch-d3d11src-null-pso: include anchor")
helper = inc + """#include <cstdlib>
/* madeira-doge: steamac null-pso (tools/patch-d3d11src-null-pso.py): env MADEIRA_NULL_PSO_SKIP=1 */
static bool MadeiraNullPsoSkip() {
  static const bool On = [] { const char *E = getenv("MADEIRA_NULL_PSO_SKIP"); return E && E[0] == '1'; }();
  return On;
}
"""
src = src.replace(inc, helper)
open(path, "w").write(src)
print("patched " + path)
