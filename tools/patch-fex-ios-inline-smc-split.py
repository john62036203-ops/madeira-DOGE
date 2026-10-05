#!/usr/bin/env python3
"""End a block after an instruction that writes into the bytes that follow it.

P3R Demo, 147AC8D20:
    xor dword [rip+0], 0x211e394d    ; turns the next four bytes into nop; cpuid; nop
    <four bytes>
    add dword [rip-0xe], 0x211a274d  ; puts them back
    ret
The decoder reads the whole block before any of it runs, so it compiled the four
bytes as they were before the xor (fnsave, mov esp, imm32, then an invalid
opcode). FEX's inline self-modifying-code path needs the write to fault with the
page tracked, which it does not on iOS, where such stores are completed through
the RW alias.

An instruction whose destination is RIP-relative and lands within the next 64
bytes now ends its block: the following bytes are decoded when execution gets
there, after the write. The block ends the same way as when the instruction
limit is reached.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-inline-smc-split.py FEX/FEXCore/Source/Interface/Core/Frontend.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "madeira-doge: a write into the bytes that follow" in s:
    print("already patched"); sys.exit(0)

old = """      if (FinalInstruction) {
        break;
      }

      if (!InstCanContinue()) {
"""
new = """      if (FinalInstruction) {
        break;
      }

      /* madeira-doge: a write into the bytes that follow ends the block
       * (tools/patch-fex-ios-inline-smc-split.py). */
      if (DecodeInst->Dest.IsRIPRelative() &&
          static_cast<uint64_t>(DecodeInst->Dest.Data.RIPLiteral.Value) < 64) {
        static std::atomic<uint32_t> MadSplitSaid {};
        if (MadSplitSaid.fetch_add(1) < 8) {
          LogMan::Msg::EFmt("[smc-split] {:X}: writes {} bytes ahead, block ends here", OpAddress,
                            static_cast<uint64_t>(DecodeInst->Dest.Data.RIPLiteral.Value));
        }
        break;
      }

      if (!InstCanContinue()) {
"""
if s.count(old) != 1:
    sys.exit("patch-fex-ios-inline-smc-split: anchor not found exactly once")
s = s.replace(old, new)
open(path, "w").write(s)
print("patched")
