#!/usr/bin/env python3
"""Name a READ fault that the self-modifying-code path claims.

The ARM64EC exception handler gives every access violation on a tracked code
page to InvalidationTracker::HandleRWXAccessViolation, reads included, and the
iOS branch then hands it to the unaligned-atomic helper, which may advance Pc.
P3R Demo (builds 106 and 109) dies deterministically a few faults after an
"AV READ" on one of its own code pages whose handling moved Pc by +4, and
nothing recorded which host instruction that was. This prints it, for the
first 64 such faults of a process.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-smc-read.py FEX/Source/Windows/ARM64EC/Module.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "madeira-doge: a READ fault claimed" in s:
    print("already patched"); sys.exit(0)

old = """      {
        const uint64_t N = IosSmcHandled.fetch_add(1, std::memory_order_relaxed) + 1;
"""
new = """      if (Exception->NumberParameters >= 2 && Exception->ExceptionInformation[0] == 0 &&
          CTX->IsAddressInCodeBuffer(Thread, NativeContext->Pc)) {
        /* madeira-doge: a READ fault claimed as self-modifying code (tools/patch-fex-ios-smc-read.py). */
        static std::atomic<uint32_t> IosSmcReadSaid {0};
        if (IosSmcReadSaid.fetch_add(1, std::memory_order_relaxed) < 64) {
          const uint32_t* IosSmcReadPc = reinterpret_cast<const uint32_t*>(NativeContext->Pc);
          LogMan::Msg::EFmt("[smc-read] pc {:X} insn {:08X} prev {:08X} next {:08X} fault {:X}", NativeContext->Pc,
                            IosSmcReadPc[0], IosSmcReadPc[-1], IosSmcReadPc[1], FaultAddress);
        }
      }
""" + old
if old not in s:
    sys.exit("patch-fex-ios-smc-read: anchor not found in " + path)
s = s.replace(old, new, 1)

# ... and what the unaligned-atomic helper left behind when it took such a fault.
old2 = """          static unsigned SmcAtomicCount;
"""
new2 = """          if (Exception->NumberParameters >= 2 && Exception->ExceptionInformation[0] == 0) {
            static std::atomic<uint32_t> IosSmcReadDone {0};
            if (IosSmcReadDone.fetch_add(1, std::memory_order_relaxed) < 64) {
              LogMan::Msg::EFmt("[smc-read] emulated as an unaligned atomic: pc {:X} -> {:X} x29 {:X} x23 {:X} x6 {:X}", SmcPc,
                                NativeContext->Pc, NativeContext->Fp, NativeContext->X23, NativeContext->X6);
            }
          }
""" + old2
if old2 not in s:
    sys.exit("patch-fex-ios-smc-read: second anchor not found in " + path)
open(path, "w").write(s.replace(old2, new2, 1))
print("patched")
