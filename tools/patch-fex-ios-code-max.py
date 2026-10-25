#!/usr/bin/env python3
"""Cap the size of a grown FEX code buffer (opt-in, ARM64EC FEX on iOS).

On iOS a process that fills its first 16 MB code buffer goes straight to a
128 MB one (ml1052), carved from the JIT pool's tail, and the previous buffer
stays pinned until every thread has migrated: FINAL FANTASY RESONANCE
(2026-10-25, Denuvo's 300 MB VM section) held 192 MB of tail plus region C
while system DLL copies could no longer be placed (AVRT.dll -> "XAudio2.7 is
not installed"). ml437 showed 32 MB retranslates a large game forever, so the
cap is a per-game choice.

MADEIRA_FEX_CODE_MAX_MB in the environment: 32..128 (rounded down to a power
of two); unset or out of range keeps 128.

Usage: patch-fex-ios-code-max.py FEX/FEXCore/Source/Interface/Core/CPUBackend.cpp
"""
import sys

path = sys.argv[1]
src = open(path).read()
marker = "madeira-doge: MADEIRA_FEX_CODE_MAX_MB"
if marker in src:
    print("already patched")
    sys.exit(0)

anchor = "    NewCodeBufferSize = MAX_CODE_SIZE;\n"
if src.count(anchor) != 1:
    sys.exit("patch-fex-ios-code-max: StartLargerCodeBuffer anchor not found exactly once")
src = src.replace(anchor, "    NewCodeBufferSize = MadeiraCodeMax();\n")

helper_anchor = "  fextl::shared_ptr<CodeBuffer> CodeBufferManager::StartLargerCodeBuffer() {\n"
if src.count(helper_anchor) != 1:
    sys.exit("patch-fex-ios-code-max: StartLargerCodeBuffer definition not found")
helper = '''  /* madeira-doge: MADEIRA_FEX_CODE_MAX_MB (tools/patch-fex-ios-code-max.py): the size a
   * grown code buffer takes, 32..128 MB as a power of two; unset keeps MAX_CODE_SIZE. */
  static size_t MadeiraCodeMax() {
    static const size_t Max = [] () -> size_t {
      const char* E = getenv("MADEIRA_FEX_CODE_MAX_MB");
      if (!E || !E[0]) {
        return MAX_CODE_SIZE;
      }
      long Mb = strtol(E, nullptr, 10);
      if (Mb < 32 || Mb > 128) {
        return MAX_CODE_SIZE;
      }
      size_t P = 32;
      while (P * 2 <= (size_t)Mb) {
        P *= 2;
      }
      LogMan::Msg::IFmt("[code-max] MADEIRA_FEX_CODE_MAX_MB: grown code buffers are {} MB", P);
      return P * 1024 * 1024;
    }();
    return Max;
  }

'''
src = src.replace(helper_anchor, helper + helper_anchor)

inc = "#include <cstdint>\n"
if src.count(inc) < 1:
    sys.exit("patch-fex-ios-code-max: include anchor not found")
src = src.replace(inc, "#include <cstdlib>\n" + inc, 1)

open(path, "w").write(src)
print("patched " + path)
