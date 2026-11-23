#!/usr/bin/env python3
"""DXMT's NGX core (dxmt/src/nvngx) for this port: a trace and one conversion.

tools/build-dxmt-nvngx.sh applies this to COPIES of nvngx.cpp and
nvngx_parameter.hpp; the dxmt submodule is not modified. The DLL answers a
game's DLSS Super Resolution calls (NVSDK_NGX_D3D11_*) with the MetalFX
temporal scaler through DXMT's d3d11 (IMTLD3D11ContextExt::TemporalUpscale).

1. Every entry point logs its first calls through DXMT's Logger, which
   reaches the session log ("[ngx] NVSDK_NGX_D3D11_Init_Ext"), so a log shows
   how far a game's DLSS start-up got.
2. NVSDK_NGX_D3D11_GetScratchBufferSize answers 0 bytes instead of abort().
3. A parameter a game stored as void * can be read back as a D3D resource
   (and the reverse): without it the color / depth / motion-vector lookup
   fails and the scaler never gets the scene (3Shain/dxmt#235).

Usage: patch-dxmt-nvngx.py <copy of nvngx.cpp> <copy of nvngx_parameter.hpp>.
Idempotent; anchor-checked.
"""
import re
import sys

cpp_path, hpp_path = sys.argv[1], sys.argv[2]
MARK = "madeira-doge: NGX trace"

cpp = open(cpp_path).read()
if MARK not in cpp:
    anchor = 'Logger Logger::s_instance("nvngx.log");\n'
    if cpp.count(anchor) != 1:
        sys.exit("patch-dxmt-nvngx: logger anchor not found once")
    helper = anchor + r'''
/* ''' + MARK + r''' (tools/patch-dxmt-nvngx.py): the first calls of each entry point. */
static void
madeira_ngx_trace(const char *name) {
  static struct { const char *name; unsigned n; } seen[64];
  for (auto &s : seen) {
    if (s.name == name || !s.name) {
      s.name = name;
      if (s.n++ < 3 || (s.n % 3600) == 0) {
        char line[160];
        snprintf(line, sizeof(line), "[ngx] %s (call %u)", name, s.n);
        Logger::info(line);
      }
      return;
    }
  }
}
'''
    cpp = cpp.replace(anchor, helper)
    pat = re.compile(r'(NVNGX_API\s+\w[\w\s\*]*?\n(NVSDK_NGX_\w+)\([^{]*\)\s*\{\n)')
    names = []

    def add(m):
        names.append(m.group(2))
        return m.group(1) + '  madeira_ngx_trace("%s");\n' % m.group(2)

    cpp, n = pat.subn(add, cpp)
    if n < 12:
        sys.exit("patch-dxmt-nvngx: only %d entry points found, expected at least 12" % n)
    # 3. A game that asks for the scratch buffer size gets "none" instead of abort().
    scratch = re.compile(r'(madeira_ngx_trace\("NVSDK_NGX_D3D11_GetScratchBufferSize"\);\n)\s*IMPLEMENT_ME\n\s*return NVNGX_RESULT_FAIL;')
    cpp, ns = scratch.subn(r'\1  if (out_size)\n    *out_size = 0;\n  return NVNGX_RESULT_OK;', cpp)
    if ns != 1:
        sys.exit("patch-dxmt-nvngx: GetScratchBufferSize anchor not found once")
    if "#include <cstdio>" not in cpp:
        cpp = "#include <cstdio>\n" + cpp
    open(cpp_path, "w").write(cpp)
    print("patch-dxmt-nvngx: trace added to %d entry points" % n)
    open(cpp_path + ".exports", "w").write("\n".join(sorted(set(names))) + "\n")
else:
    print("patch-dxmt-nvngx: nvngx.cpp already patched")

hpp = open(hpp_path).read()
HMARK = "madeira-doge: void * and resources"
if HMARK not in hpp:
    anchor = "class ParametersImpl final : public NVNGXParameter {"
    if hpp.count(anchor) != 1:
        sys.exit("patch-dxmt-nvngx: ParametersImpl anchor not found once")
    if "castable(void *val, ID3D11Resource **out)" in hpp:
        print("patch-dxmt-nvngx: the resource conversion is upstream; nothing to do")
    else:
        conv = r'''/* ''' + HMARK + r''' (3Shain/dxmt#235). */
template <>
inline bool
castable(void *val, ID3D11Resource **out) {
  *out = (ID3D11Resource *)val;
  return true;
}

template <>
inline bool
castable(ID3D11Resource *val, void **out) {
  *out = (void *)val;
  return true;
}

template <>
inline bool
castable(void *val, ID3D12Resource **out) {
  *out = (ID3D12Resource *)val;
  return true;
}

template <>
inline bool
castable(ID3D12Resource *val, void **out) {
  *out = (void *)val;
  return true;
}

'''
        hpp = hpp.replace(anchor, conv + anchor)
        open(hpp_path, "w").write(hpp)
        print("patch-dxmt-nvngx: void * <-> resource conversions added")
else:
    print("patch-dxmt-nvngx: nvngx_parameter.hpp already patched")
