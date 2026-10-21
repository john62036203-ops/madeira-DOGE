#!/usr/bin/env python3
"""Hide chosen CPUID feature bits from the guest (opt-in, ARM64EC and WoW64 FEX).

A program that picks its code path from CPUID (Flash Player's software
renderer, 2026-10-22: most characters of a .swf game drawn missing or black
under 32-bit FEX) can be steered onto an older path by hiding a feature. That
both narrows an emulation bug to an instruction family and works around it.

MADEIRA_FEX_CPUID_MASK in the environment: comma-separated names, e.g.
"sse41,sse42,ssse3". Known names: sse3 pclmul ssse3 fma cx16 sse41 sse42 movbe
popcnt aes xsave osxsave avx f16c rdrand (leaf 1 ECX), mmx sse sse2 (leaf 1
EDX), bmi1 avx2 bmi2 erms (leaf 7 EBX), lzcnt sse4a (leaf 0x80000001 ECX).
Unknown names are ignored. Unset or empty: CPUID unchanged.

Usage: patch-fex-ios-cpuid-mask.py FEX/FEXCore/Source/Interface/Core/CPUID.h
"""
import sys

MARKER = "madeira-doge: MADEIRA_FEX_CPUID_MASK"
path = sys.argv[1]
src = open(path).read()
if MARKER in src:
    print("already patched")
    sys.exit(0)

OLD_PRIMARY = """    if (Function < Primary.size()) {
      const auto Handler = Primary[Function];
      return (this->*Handler)(Leaf);
    }"""
NEW_PRIMARY = """    if (Function < Primary.size()) {
      const auto Handler = Primary[Function];
      return MadeiraCpuidMask(Function, Leaf, (this->*Handler)(Leaf));
    }"""
OLD_EXT = """    if (Function >= ExtendedBase && Function < (ExtendedBase + Extended.size())) {
      const auto Handler = Extended[Function - ExtendedBase];
      return (this->*Handler)(Leaf);
    }"""
NEW_EXT = """    if (Function >= ExtendedBase && Function < (ExtendedBase + Extended.size())) {
      const auto Handler = Extended[Function - ExtendedBase];
      return MadeiraCpuidMask(Function, Leaf, (this->*Handler)(Leaf));
    }"""
CLASS = "class CPUIDEmu final {"
HELPER = r'''/* madeira-doge: MADEIRA_FEX_CPUID_MASK (tools/patch-fex-ios-cpuid-mask.py): feature
 * bits named in the environment are cleared from the guest's CPUID results. */
static inline FEXCore::CPUID::FunctionResults MadeiraCpuidMask(uint32_t Function, uint32_t Leaf,
                                                               FEXCore::CPUID::FunctionResults R) {
  struct Masks {
    uint32_t c1, d1, b7, c81;
  };
  static const Masks M = [] {
    Masks m {};
    const char* E = getenv("MADEIRA_FEX_CPUID_MASK");
    if (!E || !E[0]) {
      return m;
    }
    struct Name {
      const char* n;
      int reg;
      uint32_t bit;
    };
    static const Name T[] = {
      {"sse3", 0, 0},    {"pclmul", 0, 1},  {"ssse3", 0, 9},   {"fma", 0, 12},     {"cx16", 0, 13},
      {"sse41", 0, 19},  {"sse42", 0, 20},  {"movbe", 0, 22},  {"popcnt", 0, 23},  {"aes", 0, 25},
      {"xsave", 0, 26},  {"osxsave", 0, 27}, {"avx", 0, 28},   {"f16c", 0, 29},    {"rdrand", 0, 30},
      {"mmx", 1, 23},    {"sse", 1, 25},    {"sse2", 1, 26},   {"bmi1", 2, 3},     {"avx2", 2, 5},
      {"bmi2", 2, 8},    {"erms", 2, 9},    {"lzcnt", 3, 5},   {"sse4a", 3, 6},
    };
    char Buf[256];
    strncpy(Buf, E, sizeof(Buf) - 1);
    Buf[sizeof(Buf) - 1] = 0;
    for (char* Tok = strtok(Buf, ", "); Tok; Tok = strtok(nullptr, ", ")) {
      for (const auto& N : T) {
        if (strcmp(Tok, N.n) == 0) {
          uint32_t* Reg = N.reg == 0 ? &m.c1 : N.reg == 1 ? &m.d1 : N.reg == 2 ? &m.b7 : &m.c81;
          *Reg |= 1U << N.bit;
        }
      }
    }
    LogMan::Msg::IFmt("[cpuid-mask] MADEIRA_FEX_CPUID_MASK=\"{}\": leaf1 ecx&=~{:#x} edx&=~{:#x}, leaf7 ebx&=~{:#x}, "
                      "0x80000001 ecx&=~{:#x}", E, m.c1, m.d1, m.b7, m.c81);
    return m;
  }();
  if (Function == 1) {
    R.ecx &= ~M.c1;
    R.edx &= ~M.d1;
  } else if (Function == 7 && Leaf == 0) {
    R.ebx &= ~M.b7;
  } else if (Function == 0x8000'0001U) {
    R.ecx &= ~M.c81;
  }
  return R;
}

'''
INCLUDE = "#include <cstdint>\n"

for anchor in (OLD_PRIMARY, OLD_EXT, CLASS, INCLUDE):
    if src.count(anchor) != 1:
        sys.exit("patch-fex-ios-cpuid-mask: anchor not found or not unique: " + anchor[:60])
src = src.replace(OLD_PRIMARY, NEW_PRIMARY).replace(OLD_EXT, NEW_EXT)
src = src.replace(CLASS, HELPER + CLASS)
src = src.replace(INCLUDE, INCLUDE + "#include <cstdlib>\n#include <cstring>\n#include <FEXCore/Utils/LogManager.h>\n")
open(path, "w").write(src)
print("patched " + path)
