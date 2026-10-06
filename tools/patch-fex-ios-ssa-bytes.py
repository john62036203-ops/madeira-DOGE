#!/usr/bin/env python3
"""Room for a validated block in the JIT's temporary buffer.

A block is emitted into a temporary buffer sized 24 bytes per IR node; a write
past it lands on a guard page and the compile restarts with twice the room.
MHR's Sunbreak demo declares every code section writable, so with
env.MADEIRA_FEX_RWX_SMC = 1 each instruction is preceded by a byte-for-byte
check of itself, far more than 24 bytes a node. Build 136, log 2026-10-06
21:38: a 2.4 MB buffer overflowed (AV WRITE at its guard page from the
emitter), the restart resumed, and the thread then ran to pc 0 and the game
ended at start-up. The restart itself is not changed here; the first estimate
is, so that it is not needed: 96 bytes a node when MADEIRA_FEX_RWX_SMC is 1,
24 otherwise. env.MADEIRA_FEX_SSA_BYTES = 24..512 overrides either. The
buffer is address space until written.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-ssa-bytes.py FEX/FEXCore/Source/Interface/Core/JIT/JIT.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "MADEIRA_FEX_SSA_BYTES" in s:
    print("already patched"); sys.exit(0)

old = "  SSANodeMultiplier = 24;\n"
new = """  {
    /* madeira-doge (tools/patch-fex-ios-ssa-bytes.py): the first estimate of host bytes per IR node */
    static const uint32_t MadSsaBytes = [] {
      uint32_t N = 24;
      const char* Smc = getenv("MADEIRA_FEX_RWX_SMC");
      if (Smc && Smc[0] == '1') N = 96;
      const char* E = getenv("MADEIRA_FEX_SSA_BYTES");
      if (E && *E) {
        const long V = strtol(E, nullptr, 10);
        if (V >= 24 && V <= 512) N = static_cast<uint32_t>(V);
      }
      if (N != 24) LogMan::Msg::EFmt("[jit-temp] madeira-doge: {} bytes per IR node in the temporary buffer (24 upstream)", N);
      return N;
    }();
    SSANodeMultiplier = MadSsaBytes;
  }
"""
if s.count(old) != 1:
    sys.exit("patch-fex-ios-ssa-bytes: anchor not found exactly once")
s = s.replace(old, new)
inc = "#include <FEXCore/Utils/LogManager.h>\n"
if s.count(inc) != 1:
    sys.exit("patch-fex-ios-ssa-bytes: include anchor not found exactly once")
s = s.replace(inc, inc + "#include <cstdlib>\n")
open(path, "w").write(s)
print("patched")
