#!/usr/bin/env python3
"""winemetal: drop draws and dispatches whose pipeline failed to compile.

Ported from steamac (fxgl/steamac host/dxmt/patches 0006 and the winemetal
part of 0007, Apache-2.0 / DXMT's licence): when pipeline creation fails (the
Metal compiler service dying under load, a shader Metal rejects), the encode
stream still carries the draws and dispatches queued for it.

- Compute: dispatching with the zero threadgroup size left by a missing SetPSO
  is a fatal Metal API violation that kills the process; such dispatches are
  now skipped. A SetPSO with a null pipeline zeroes the threadgroup size
  instead of passing nil to Metal.
- Render: a SetPSO with a null pipeline is not passed to Metal, and the draws
  after it are dropped until a real pipeline is set, instead of running with
  the previous pipeline and the failed one's bindings (GPU faults).

Opt-in: env.MADEIRA_NULL_PSO_SKIP = 1 (Game details toggle, together with
d3d11-src's half). Unset keeps winemetal exactly as before. Only paths that
crashed or drew with the wrong pipeline change; with valid pipelines nothing
differs. DXMT's prebuilt d3d11.dll never encodes a null
SetPSO; d3d11-src.dll does with tools/patch-d3d11src-null-pso.py.

Usage: patch-winemetal-null-pso.py dxmt/src/winemetal/unix/winemetal_unix.c
"""
import re
import sys

path = sys.argv[1]
src = open(path).read()
marker = "madeira-doge: steamac null-pso"
if marker in src:
    print("already patched")
    sys.exit(0)

def region(start_sig):
    i = src.find(start_sig)
    if i < 0:
        sys.exit("patch-winemetal-null-pso: %r not found" % start_sig)
    j = src.find("\n}\n", i)
    return i, j

helper = """
/* madeira-doge: steamac null-pso (tools/patch-winemetal-null-pso.py): env MADEIRA_NULL_PSO_SKIP=1 */
static int madeira_null_pso_skip(void) {
  static int v = -1;
  if (v < 0) { const char *e = getenv("MADEIRA_NULL_PSO_SKIP"); v = (e && e[0] == '1') ? 1 : 0; }
  return v;
}
"""
anchor = "_MTLComputeCommandEncoder_encodeCommands(void *obj) {"
k0 = src.find(anchor)
if k0 < 0:
    sys.exit("patch-winemetal-null-pso: compute function not found")
ls = src.rfind("\n", 0, src.rfind("\n", 0, k0)) + 1   # the line before (return type)
src = src[:ls] + helper.lstrip("\n") + "\n" + src[ls:]

# --- compute ---
ci, cj = region("_MTLComputeCommandEncoder_encodeCommands(void *obj) {")
comp = src[ci:cj]
n = 0
for case in ("WMTComputeCommandDispatch", "WMTComputeCommandDispatchThreads", "WMTComputeCommandDispatchIndirect"):
    pat = re.compile(r"(    case %s: \{\n(      struct [^\n]*\n))" % case)
    comp, k = pat.subn(r"\1      if (threadgroup_size.width == 0 && madeira_null_pso_skip()) break;   /* madeira-doge: steamac null-pso (0006) */\n", comp, count=1)
    n += k
if n != 3:
    sys.exit("patch-winemetal-null-pso: compute dispatch cases matched %d of 3" % n)
old = "      struct wmtcmd_compute_setpso *body = (struct wmtcmd_compute_setpso *)next;\n"
if comp.count(old) != 1:
    sys.exit("patch-winemetal-null-pso: compute SetPSO anchor")
comp = comp.replace(old, old + "      if (!body->pso && madeira_null_pso_skip()) { threadgroup_size = MTLSizeMake(0, 0, 0); break; }   /* madeira-doge: steamac null-pso (0007) */\n")
src = src[:ci] + comp + src[cj:]

# --- render ---
ri, rj = region("_MTLRenderCommandEncoder_encodeCommands(void *obj) {")
rend = src[ri:rj]
loop = "  while (next) {\n    switch ((enum WMTRenderCommandType)next->type) {\n"
if rend.count(loop) != 1:
    sys.exit("patch-winemetal-null-pso: render loop anchor found %d times" % rend.count(loop))
rend = rend.replace(loop, "  bool pso_valid = true;   /* madeira-doge: steamac null-pso (0007): cleared by a null SetPSO */\n" + loop)
old = "      struct wmtcmd_render_setpso *body = (struct wmtcmd_render_setpso *)next;\n"
if rend.count(old) != 1:
    sys.exit("patch-winemetal-null-pso: render SetPSO anchor")
rend = rend.replace(old, old + "      pso_valid = body->pso != 0 || !madeira_null_pso_skip();\n      if (!pso_valid) break;\n")
pat = re.compile(r"(    case WMTRenderCommand(?:Draw\w*|DXMT\w*Draw\w*): \{\n)")
rend, k = pat.subn(r"\1      if (!pso_valid) break;\n", rend)
if k < 10:
    sys.exit("patch-winemetal-null-pso: only %d render draw cases matched" % k)
src = src[:ri] + rend + src[rj:]

open(path, "w").write(src)
print("patched %s (%d render draw cases)" % (path, k))
