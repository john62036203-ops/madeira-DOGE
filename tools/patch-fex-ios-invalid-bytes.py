#!/usr/bin/env python3
"""Say WHICH instruction the decoder refused.

"Invalid instruction in entry block: 147AC8D31" names an address and nothing
else; the process dies on the #UD that follows and the bytes are gone with it
(P3R Demo, after its start-up code had run for a minute). The first sixteen
bytes at that address are now printed with the message, for the first few.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-invalid-bytes.py FEX/FEXCore/Source/Interface/Core/Frontend.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "madeira-doge: the refused instruction's bytes" in s:
    print("already patched"); sys.exit(0)

old = """                            OpAddress);
        }
        break;
"""
new = """                            OpAddress);
          /* madeira-doge: the refused instruction's bytes (tools/patch-fex-ios-invalid-bytes.py).
           * Only for a decode failure: the decoder has just read these bytes. */
          if (BlockIt->BlockStatus == DecodedBlockStatus::INVALID_INST || BlockIt->BlockStatus == DecodedBlockStatus::UNIMPLEMENTED_INST) {
            static std::atomic<uint32_t> Said {};
            if (Said.fetch_add(1) < 6) {
              /* not past the end of the 16K page the instruction starts in */
              uint8_t B[16] = {};
              const uint64_t Left = 0x4000 - (OpAddress & 0x3fff);
              std::memcpy(B, reinterpret_cast<const void*>(OpAddress), Left < 16 ? Left : 16);
              LogMan::Msg::EFmt("[bad-inst] {:X}: {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x}", OpAddress,
                                B[0], B[1], B[2], B[3], B[4], B[5], B[6], B[7], B[8], B[9], B[10], B[11], B[12], B[13], B[14], B[15]);
            }
          }
        }
        break;
"""
if s.count(old) != 1:
    sys.exit("patch-fex-ios-invalid-bytes: anchor not found exactly once in " + path)
s = s.replace(old, new)
if "#include <atomic>" not in s:
    s = s.replace("#include <array>\n", "#include <array>\n#include <atomic>\n", 1)
open(path, "w").write(s)
print("patched " + path)
