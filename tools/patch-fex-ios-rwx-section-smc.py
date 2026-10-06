#!/usr/bin/env python3
"""Validate code before each instruction in image sections declared writable.

MHR's start-up stub (an unnamed section declared EXECUTE|WRITE) decrypts the
0x2a5 bytes that follow it with a byte loop (xor [rax], dl) and jumps into
them. The decoder had already read those bytes as part of the same multiblock,
so the stale translation ran: garbage registers, then a read fault at
runtime_il2cpp.exe+0xe7211dd. On iOS the write never faults (the backing of a
writable code section stays writable), so FEX's page-tracking never sees it and
its inline self-modifying-code path is never entered.

Blocks whose entry lies in a section the image itself declares both executable
and writable now get FEX's existing per-instruction validator (the one
FEX_SMCCHECKS=full applies everywhere), so a changed byte is noticed before it
runs. Ordinary .text is untouched. Opt-in per game: env.MADEIRA_FEX_RWX_SMC = 1
(a game whose hot code sits in such a section would pay for it every frame).

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-rwx-section-smc.py FEX
Idempotent; fails by name if an anchor moved.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1])
MARK = "madeira-doge: writable code sections"

def patch(rel, old, new):
    p = root / rel
    s = p.read_text()
    if new in s:
        print(f"{rel}: already patched"); return
    if s.count(old) != 1:
        sys.exit(f"patch-fex-ios-rwx-section-smc: anchor not found exactly once in {rel}")
    p.write_text(s.replace(old, new))
    print(f"{rel}: patched")

# 1. The table, in FEXCore (Frontend.cpp), and its use when a multiblock is finished.
patch("FEXCore/Source/Interface/Core/Frontend.cpp",
"""namespace FEXCore::Frontend {
""",
"""/* madeira-doge: writable code sections (tools/patch-fex-ios-rwx-section-smc.py).
 * Filled by the Windows invalidation tracker at image map; read by the decoder. */
namespace FEXCore {
std::atomic<uint64_t> IosRwxSection[32][2] {};
std::atomic<uint32_t> IosRwxSectionCount {};
void IosRwxSectionAdd(uint64_t Start, uint64_t End) {
  const uint32_t N = IosRwxSectionCount.load(std::memory_order_acquire);
  for (uint32_t i = 0; i < N && i < 32; i++) {
    if (IosRwxSection[i][0].load(std::memory_order_relaxed) == Start) return;
  }
  if (N >= 32) return;
  IosRwxSection[N][0].store(Start, std::memory_order_relaxed);
  IosRwxSection[N][1].store(End, std::memory_order_relaxed);
  IosRwxSectionCount.store(N + 1, std::memory_order_release);
}
static bool IosRwxSectionHas(uint64_t Address) {
  const uint32_t N = IosRwxSectionCount.load(std::memory_order_acquire);
  for (uint32_t i = 0; i < N && i < 32; i++) {
    if (Address >= IosRwxSection[i][0].load(std::memory_order_relaxed) &&
        Address < IosRwxSection[i][1].load(std::memory_order_relaxed)) return true;
  }
  return false;
}
}

namespace FEXCore::Frontend {
""")
patch("FEXCore/Source/Interface/Core/Frontend.cpp",
"""  for (auto& Block : BlockInfo.Blocks) {
    Block.IsEntryPoint = BlockInfo.EntryPoints.contains(Block.Entry);
""",
"""  for (auto& Block : BlockInfo.Blocks) {
    if (FEXCore::IosRwxSectionHas(Block.Entry)) {
      Block.ForceFullSMCDetection = true;
      static std::atomic<uint32_t> MadRwxSaid {};
      if (MadRwxSaid.fetch_add(1) < 4) {
        LogMan::Msg::EFmt("[smc-rwx] block {:X} is in a writable code section: validated before each instruction", Block.Entry);
      }
    }
    Block.IsEntryPoint = BlockInfo.EntryPoints.contains(Block.Entry);
""")

# 2. Registration where the tracker records a section that is executable and writable.
patch("Source/Windows/Common/InvalidationTracker.cpp",
"""        RWXIntervals.Insert({SectionBase, SectionBase + Section->Misc.VirtualSize});
      }
    }
  }
""",
"""        RWXIntervals.Insert({SectionBase, SectionBase + Section->Misc.VirtualSize});
        /* madeira-doge: writable code sections (tools/patch-fex-ios-rwx-section-smc.py) */
        {
          const char* Off = getenv("MADEIRA_FEX_RWX_SMC"); /* opt-in: a game with hot code in such a section would slow down */
          if (Off && Off[0] == '1') {
            FEXCore::IosRwxSectionAdd(SectionBase, SectionBase + Section->Misc.VirtualSize);
          }
        }
      }
    }
  }
""")
patch("Source/Windows/Common/InvalidationTracker.cpp",
"""namespace FEX::Windows {
""",
"""namespace FEXCore { void IosRwxSectionAdd(uint64_t Start, uint64_t End); } /* madeira-doge: writable code sections decl */

namespace FEX::Windows {
""")
