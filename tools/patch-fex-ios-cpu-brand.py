#!/usr/bin/env python3
"""CPUID brand string that agrees with the vendor (opt-in, ARM64EC FEX).

FEX reports vendor "GenuineIntel" and family 6 model 0xA6 (leaf 1 EAX
000A0661) but its brand-string leaves 0x8000'0002..4 say "Unknown ARM CPU"
(the iOS host has no MIDR table entry). Real Intel parts never pair those.
Anti-tamper code (FINAL FANTASY RESONANCE demo, Denuvo, 2026-10-21) reads the
brand leaves; whether the mismatch matters is what this switch tests.

MADEIRA_FEX_CPU_BRAND in the environment:
  unset / "0"  FEX's own string (unchanged)
  "1"          "Intel(R) Core(TM) i7-10710U CPU @ 1.10GHz" (a family 6 model
               0xA6 part, so leaf 1 and the brand agree)
  other text   that text (first 47 characters)

Usage: patch-fex-ios-cpu-brand.py FEX/FEXCore/Source/Interface/Core/CPUID.cpp
"""
import sys

path = sys.argv[1]
src = open(path).read()
marker = "madeira-doge: MADEIRA_FEX_CPU_BRAND"
if marker in src:
    print("already patched")
    sys.exit(0)

head = "FEXCore::CPUID::FunctionResults CPUIDEmu::Function_8000_0002h(uint32_t Leaf, uint32_t CPU) const {"
tail = "// L1 Cache and TLB identifiers"
if src.count(head) != 1 or src.count(tail) != 1:
    sys.exit("patch-fex-ios-cpu-brand: brand-string leaf anchors not found")
a = src.index(head)
b = src.index(tail, a)
body = src[a:b]
if body.count("Data.ProductName") < 5:
    sys.exit("patch-fex-ios-cpu-brand: unexpected brand-string leaf bodies")
body = body.replace("Data.ProductName", "MadeiraBrand(Data.ProductName)")

helper = '''/* madeira-doge: MADEIRA_FEX_CPU_BRAND (tools/patch-fex-ios-cpu-brand.py): "1" gives a
 * brand string that matches the reported Intel family/model, other text is used
 * as is; unset or "0" keeps FEX's own string. */
static const char* MadeiraBrand(const char* Own) {
  static const char* Brand = [] () -> const char* {
    static char Buf[48];
    const char* E = getenv("MADEIRA_FEX_CPU_BRAND");
    if (!E || !E[0] || (E[0] == '0' && !E[1])) {
      return nullptr;
    }
    if (E[0] == '1' && !E[1]) {
      E = "Intel(R) Core(TM) i7-10710U CPU @ 1.10GHz";
    }
    strncpy(Buf, E, sizeof(Buf) - 1);
    LogMan::Msg::IFmt("[cpu-brand] MADEIRA_FEX_CPU_BRAND: CPUID 0x80000002-4 report \\"{}\\"", Buf);
    return Buf;
  }();
  return Brand ? Brand : Own;
}

'''
src = src[:a] + helper + body + src[b:]

inc = "#include <cstring>\n"
if src.count(inc) < 1:
    sys.exit("patch-fex-ios-cpu-brand: include anchor not found")
src = src.replace(inc, "#include <cstdlib>\n" + inc, 1)

open(path, "w").write(src)
print("patched " + path)
