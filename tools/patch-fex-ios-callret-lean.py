#!/usr/bin/env python3
"""FEX (ARM64EC module): no suspend check at the point a guest CALL returns to (MADEIRA_FEX_CALLRET_LEAN=1; opt-in).

madeira-doge, from BCD 0.1.659 (tools/patch-fex-ios-callret-lean.py, GPL-3.0-only, copyright 2026 thebcd69), which took it
from Porthole's patch 0143 (https://github.com/tylerkaska112/Porthole, GPL-3.0-or-later). Every entry point of the JIT's code
ends with the thread's suspend doorbell test (ldr; cbz; brk). The instruction after a guest CALL is such an entry point: the
callee's RET comes back to it. With MADEIRA_FEX_CALLRET_LEAN=1 the test is left out of an entry point that directly follows the
CALL it belongs to: two instructions fewer on every return from a guest call, twelve bytes less code per call site. The code
between the CALL and its return point always passes a test of its own (the x64 callee's entry point, or ExitFunctionEC for an
ARM64EC callee), so the test left out was the second in a row. Every other entry point and backward branch keeps its test.

Unless MADEIRA_FEX_CALLRET_LEAN is exactly 1 when the program starts (default off) every entry point is emitted as before, byte
for byte. Unlike BCD, no log line (this tree's Module.cpp has no call-ret elision line to hang it on).

Applied by tools/build-xtajit64.sh after its other overlays (JIT.cpp and JITClass.h are restored after the build);
idempotent; a moved anchor or a partial overlay refuses the patch and the build goes on without it.
Usage: patch-fex-ios-callret-lean.py FEX-ROOT
"""
from pathlib import Path
import sys

MARKER = "callret-lean-v1 madeira-doge"
JIT = "FEXCore/Source/Interface/Core/JIT/JIT.cpp"
JIT_H = "FEXCore/Source/Interface/Core/JIT/JITClass.h"

HUNKS = (
    (JIT_H, "EmitEntryPoint's declaration",
     "  void EmitEntryPoint(ARMEmitter::BackwardLabel& HeaderLabel, bool CheckTF);\n",
     "  // callret-lean-v1 madeira-doge (tools/patch-fex-ios-callret-lean.py): SkipSuspendCheck leaves the suspend doorbell test out of\n"
     "  // the entry point; only the point a CALL falls through into asks for it, and only with MADEIRA_FEX_CALLRET_LEAN=1.\n"
     "  void EmitEntryPoint(ARMEmitter::BackwardLabel& HeaderLabel, bool CheckTF, bool SkipSuspendCheck = false);\n"),
    (JIT, "the includes",
     "#include <cstdio>\n#include <cstring>\n",
     "#include <cstdio>\n#include <cstdlib>\n#include <cstring>\n"),
    (JIT, "EmitEntryPoint's definition",
     "void Arm64JITCore::EmitEntryPoint(ARMEmitter::BackwardLabel& HeaderLabel, bool CheckTF) {\n",
     "// callret-lean-test:begin\n"
     "/* callret-lean-v1 madeira-doge (from BCD 0.1.659 / Porthole 0143): whether the suspend doorbell test is left out at the point a\n"
     " * guest CALL returns to. Only exactly \"1\" is on (default off); read once. Only the iOS ARM64EC module has the switch. */\n"
     "static bool CallRetLeanEnabled() {\n"
     "#if defined(FEX_IOS_HOST) && defined(ARCHITECTURE_arm64ec)\n"
     "  static const bool On = [] {\n"
     "    const char* Env = getenv(\"MADEIRA_FEX_CALLRET_LEAN\");\n"
     "    return Env && Env[0] == '1' && !Env[1];\n"
     "  }();\n"
     "  return On;\n"
     "#else\n"
     "  return false;\n"
     "#endif\n"
     "}\n"
     "// callret-lean-test:end\n"
     "\n"
     "void Arm64JITCore::EmitEntryPoint(ARMEmitter::BackwardLabel& HeaderLabel, bool CheckTF, bool SkipSuspendCheck) {\n"),
    (JIT, "the end of EmitEntryPoint",
     "  EmitSuspendInterruptCheck();\n}\n\nCPUBackend::CompiledCode Arm64JITCore::CompileCode(",
     "  /* callret-lean-v1 madeira-doge: the doorbell test is left out at the point a CALL returns to (the callee's own entry point, or\n"
     "   * ExitFunctionEC for an ARM64EC callee, tested it on the way). Every other entry point and every backward jump keeps its test. */\n"
     "  if (!SkipSuspendCheck) {\n"
     "    EmitSuspendInterruptCheck();\n"
     "  }\n}\n\nCPUBackend::CompiledCode Arm64JITCore::CompileCode("),
    (JIT, "the entry point of a block (the pending call return)",
     "        PendingCallReturnTargetLabel = nullptr;\n\n        BindOrRestart(&IsReturnTarget->second);\n",
     "        // callret-lean-v1 madeira-doge: this entry point directly follows the CALL it is the return block of, and nothing branches into it here\n"
     "        const bool IsCallReturnFallthrough = PendingCallReturnTargetLabel == &IsReturnTarget->second && !PendingTargetLabel;\n"
     "        PendingCallReturnTargetLabel = nullptr;\n\n        BindOrRestart(&IsReturnTarget->second);\n"),
    (JIT, "the entry point of a block (EmitEntryPoint's call)",
     "        EmitEntryPoint(JITCodeHeaderLabel, CheckTF);\n",
     "        EmitEntryPoint(JITCodeHeaderLabel, CheckTF, IsCallReturnFallthrough && CallRetLeanEnabled());\n"),
)
FILES = (JIT_H, JIT)


def patch(texts):
    present = [MARKER in texts[f] for f in FILES]
    if all(present):
        for f, what, old, new in HUNKS:
            if texts[f].count(new) != 1:
                raise ValueError("partial or changed callret-lean (" + what + ")")
        return texts
    if any(present):
        raise ValueError("partial callret-lean: " + ", ".join(f for f, p in zip(FILES, present) if p) + " patched, the rest not")
    out = dict(texts)
    for f, what, old, new in HUNKS:
        if out[f].count(old) != 1:
            raise ValueError(what + " not found once in " + f + " (FEX changed)")
        out[f] = out[f].replace(old, new, 1)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[-1])
    root = Path(sys.argv[1])
    try:
        sources = {f: (root / f).read_text() for f in FILES}
        result = patch(sources)
    except (OSError, ValueError) as error:
        sys.exit("patch-fex-ios-callret-lean: " + str(error))
    if result == sources:
        print("patch-fex-ios-callret-lean: already in")
    else:
        for f in FILES:
            (root / f).write_text(result[f])
        print("FEX: no suspend check at the point a guest CALL returns to (MADEIRA_FEX_CALLRET_LEAN=1; without it every entry point is as before)")
