#!/usr/bin/env python3
"""FEX: RDTSC reads the timer self-synchronized with MADEIRA_X64_QPC_FASTPATH=1 (opt-in).

madeira-doge, from Playport (playportdev/playport patches/fex 0061). FEX's RDTSC
reads CNTVCT_EL0 with no ISB, so a read can be taken ahead of the instructions
before it and two reads in a thread can come out of order. ntdll-x64fast.dll
(tools/patch-wine-ntdll-x64fast.py) binds x64 imports of QueryPerformanceCounter to
an x64 stub that counts with RDTSC under MADEIRA_X64_QPC_FASTPATH=1, and
QueryPerformanceCounter must never go back; RtlQueryPerformanceCounter's own read has
an ISB. With the same switch RDTSC reads the timer as RDTSCP already does
(CycleCounter(true): CNTVCTSS_EL0 with ECV, else ISB + CNTVCT_EL0). Unset or anything
but 1: FEX's RDTSC, unchanged. Read once per process, the first time RDTSC is compiled.

Applied by tools/build-xtajit64.sh (ARM64EC only; restores OpcodeDispatcher.cpp after
its build); idempotent; a moved anchor refuses the patch and the build goes on.
Usage: patch-fex-ios-rdtsc-selfsync.py FEX-ROOT
"""
from pathlib import Path
import sys

MARKER = "madeira-doge rdtsc-selfsync"
DISPATCH = "FEXCore/Source/Interface/Core/OpcodeDispatcher.cpp"

OLD = "void OpDispatchBuilder::RDTSCOp(OpcodeArgs) {\n  auto Counter = CycleCounter(false);\n"
INCLUDE_ANCHOR = '#include "FEXCore/Core/HostFeatures.h"\n'
INCLUDE = "#include <cstdlib>\n"

NEW = '''#ifdef FEX_IOS_HOST
/* madeira-doge rdtsc-selfsync (Playport fex 0061): MADEIRA_X64_QPC_FASTPATH=1, read once per process. */
static bool IosRdtscSelfSync() {
  static const bool On = [] {
    const char* Env = getenv("MADEIRA_X64_QPC_FASTPATH");
    return Env && Env[0] == '1' && !Env[1];
  }();
  return On;
}
#endif

void OpDispatchBuilder::RDTSCOp(OpcodeArgs) {
#ifdef FEX_IOS_HOST
  auto Counter = CycleCounter(IosRdtscSelfSync());
#else
  auto Counter = CycleCounter(false);
#endif
'''


def patch(src):
    if MARKER in src:
        if src.count(NEW) != 1 or src.count(INCLUDE_ANCHOR + INCLUDE) != 1:
            raise ValueError("partial or changed rdtsc-selfsync")
        return src
    if src.count(OLD) != 1 or src.count(INCLUDE_ANCHOR) != 1:
        raise ValueError("RDTSCOp or the HostFeatures include not found once (FEX changed)")
    return src.replace(INCLUDE_ANCHOR, INCLUDE_ANCHOR + INCLUDE, 1).replace(OLD, NEW, 1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[-1])
    path = Path(sys.argv[1]) / DISPATCH
    source = path.read_text()
    try:
        result = patch(source)
    except ValueError as error:
        sys.exit("patch-fex-ios-rdtsc-selfsync: " + str(error))
    if result == source:
        print("patch-fex-ios-rdtsc-selfsync: already in")
    else:
        path.write_text(result)
        print("FEX: RDTSC is self-synchronizing with MADEIRA_X64_QPC_FASTPATH=1 (opt-in)")
