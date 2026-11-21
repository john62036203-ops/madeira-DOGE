#!/usr/bin/env python3
"""FEX (ARM64EC module): x64->EC call targets translated by one table probe (MADEIRA_FEX_ALIAS_GRANULES=1; opt-in).

madeira-doge, adapted from the "alias" item of Playport patches/fex/0071 (MADEIRA_FEX_BATCH2;
https://github.com/playportdev/playport, The Playport authors, GPL-3.0-or-later). Only that item is taken (not
ffs, dmb or uabp), and this tree's alias table has no sequence count, so the granule table carries its own.

Every call from translated x64 code into ARM64EC code (d3d11.dll, dxgi.dll, XAudio2, the EC kernel32/ntdll ...)
leaves the JIT through ExitFunctionECJit / ExitFunctionEC (Module.S), which translate the target from the PE
address to the runnable copy in the JIT pool: the thread's last hit first, then a walk over the whole alias
table, newest first. A target that matches neither (it is already a pool address, as every pointer inside a
relocated pool copy is) walks the whole table (200+ entries) for nothing. BCD measured that walk at 42-52 % of
the CPU of Direct3D 11 render threads (engine review I10, 2026-11-17); Playport counts ~520,000 such calls a
second in RDR2.

With MADEIRA_FEX_ALIAS_GRANULES=1 the writer (BTCpu64IosAddAliasMapping, IosJitAlias.cpp) also keeps every
listed image's 64 KB granules in IosAliasGranules (32768 slots, linear probing, at most half full): the key is
granule + 1, the value JitBase - PeBase of the one image the granule lies in whole, or 1 (no delta is odd) for a
granule shared or only partly an image's. Module.S probes it before the hint: an empty slot means no image (the
target stays, as when the walk finds nothing); a whole granule read under an even, unmoved IosAliasGranGen adds
its delta; anything else (a writer active, the count moved, a part granule) takes the hint and walk as before.
While it is on, writers are serialized by a spin lock and every change rebuilds the granules with the count
odd, so no reader ever pairs an old delta with a reused range. It is switched on once, in ProcessInit, before
the process has translated threads; an overflow switches it off for the process. When the
granules would fill more than half the table the lookup turns itself off for the process.

Unset (default) IosAliasGranOn stays 0: the probe is skipped by its first test (three instructions) and the
writer runs what it ran before, without the lock. "FEX: alias-granules" is logged at process start.

Applied by tools/build-xtajit64.sh after the other overlays; idempotent; a moved anchor refuses the patch and
the build goes on without it.
Usage: patch-fex-ios-alias-granules.py FEX-ROOT
"""
import sys
from pathlib import Path

MARK = "madeira-doge alias-granules"

ALIAS = "Source/Windows/ARM64EC/IosJitAlias.cpp"
ASM = "Source/Windows/ARM64EC/Module.S"
MODULE = "Source/Windows/ARM64EC/Module.cpp"

ALIAS_GLOBALS = (
    "IosAliasEntry* volatile IosAliasLast = nullptr;\n}\n",
    "IosAliasEntry* volatile IosAliasLast = nullptr;\n"
    f"/* {MARK} (tools/patch-fex-ios-alias-granules.py): every listed image's 64 KB granules, probed by\n"
    " * Module.S before the hint and walk while IosAliasGranOn is 1. Slot: Key = granule + 1 (0 empty),\n"
    " * Delta = JitBase - PeBase of the one image the granule lies in whole, or 1 for a part granule.\n"
    " * IosAliasGranGen is odd while a writer changes the table. Module.S relies on the 16-byte slot,\n"
    " * the 32768 slots and Key below 2^40. */\n"
    "struct IosAliasGranule {\n"
    "  uint64_t Key;\n"
    "  uint64_t Delta;\n"
    "};\n"
    "alignas(16) IosAliasGranule IosAliasGranules[32768];\n"
    "volatile uint64_t IosAliasGranGen = 0;\n"
    "volatile uint32_t IosAliasGranOn = 0;\n"
    "}\n",
)

ALIAS_HELPERS = (
    "volatile int& g_EntryCount = IosAliasCount;\n}  // namespace\n",
    "volatile int& g_EntryCount = IosAliasCount;\n"
    "\n"
    f"// {MARK}: the writer side of IosAliasGranules.\n"
    "constexpr uint32_t kGranSlots = 32768;\n"
    "constexpr uint64_t kGranPart = 1;\n"
    "uint32_t g_GranUsed = 0;\n"
    "volatile uint32_t g_AliasWriteLock = 0;\n"
    "\n"
    "// No logging and no calls: this runs inside unix-side syscalls (see the table-full note below).\n"
    "void AliasWriteLock() {\n"
    "  while (__atomic_exchange_n(&g_AliasWriteLock, 1u, __ATOMIC_ACQUIRE)) {\n"
    "    while (__atomic_load_n(&g_AliasWriteLock, __ATOMIC_RELAXED)) {\n"
    "      __asm__ volatile(\"yield\");\n"
    "    }\n"
    "  }\n"
    "}\n"
    "void AliasWriteUnlock() {\n"
    "  __atomic_store_n(&g_AliasWriteLock, 0u, __ATOMIC_RELEASE);\n"
    "}\n"
    "\n"
    "// IosAliasGranGen odd: readers take the hint and walk until GranEnd.\n"
    "void GranBegin() {\n"
    "  __atomic_store_n(&IosAliasGranGen, IosAliasGranGen + 1, __ATOMIC_RELAXED);\n"
    "  __atomic_thread_fence(__ATOMIC_SEQ_CST);\n"
    "}\n"
    "void GranEnd() {\n"
    "  __atomic_store_n(&IosAliasGranGen, IosAliasGranGen + 1, __ATOMIC_RELEASE);\n"
    "}\n"
    "\n"
    "bool GranPut(uint64_t Key, uint64_t Delta) {\n"
    "  for (uint32_t i = Key & (kGranSlots - 1);; i = (i + 1) & (kGranSlots - 1)) {\n"
    "    IosAliasGranule& Slot = IosAliasGranules[i];\n"
    "    if (Slot.Key == Key) {\n"
    "      if (Slot.Delta != Delta) {\n"
    "        Slot.Delta = kGranPart;\n"
    "      }\n"
    "      return true;\n"
    "    }\n"
    "    if (!Slot.Key) {\n"
    "      if (g_GranUsed >= kGranSlots / 2) {\n"
    "        return false;\n"
    "      }\n"
    "      Slot.Delta = Delta;\n"
    "      Slot.Key = Key;\n"
    "      g_GranUsed++;\n"
    "      return true;\n"
    "    }\n"
    "  }\n"
    "}\n"
    "\n"
    "bool GranAddImage(uint64_t PeBase, uint64_t JitBase, uint64_t Size) {\n"
    "  const uint64_t End = PeBase + Size;\n"
    "  if (!Size || End < PeBase || (End >> 56)) {\n"
    "    return false;\n"
    "  }\n"
    "  const uint64_t Delta = JitBase - PeBase;\n"
    "  for (uint64_t Granule = PeBase >> 16; Granule <= (End - 1) >> 16; Granule++) {\n"
    "    const bool Whole = (Granule << 16) >= PeBase && ((Granule + 1) << 16) <= End && !(Delta & 1);\n"
    "    if (!GranPut(Granule + 1, Whole ? Delta : kGranPart)) {\n"
    "      return false;\n"
    "    }\n"
    "  }\n"
    "  return true;\n"
    "}\n"
    "\n"
    "// Under the lock, between GranBegin and GranEnd: the granules of the live entries, or off on overflow.\n"
    "void GranRebuild() {\n"
    "  for (uint32_t i = 0; i < kGranSlots; i++) {\n"
    "    IosAliasGranules[i].Key = 0;\n"
    "    IosAliasGranules[i].Delta = 0;\n"
    "  }\n"
    "  g_GranUsed = 0;\n"
    "  const int count = g_EntryCount;\n"
    "  for (int i = 0; i < count; i++) {\n"
    "    if (g_Entries[i].Size && !GranAddImage(g_Entries[i].PeBase, g_Entries[i].JitBase, g_Entries[i].Size)) {\n"
    "      __atomic_store_n(&IosAliasGranOn, 0u, __ATOMIC_RELAXED);\n"
    "      return;\n"
    "    }\n"
    "  }\n"
    "}\n"
    "}  // namespace\n",
)

ALIAS_RENAME = (
    "void BTCpu64IosAddAliasMapping(uint64_t PeBase, uint64_t JitBase, uint64_t Size) {\n",
    f"/* {MARK}: the original body; BTCpu64IosAddAliasMapping below serializes it and keeps the granules. */\n"
    "static void IosAliasAddMappingBody(uint64_t PeBase, uint64_t JitBase, uint64_t Size) {\n",
)

ALIAS_WRAPPER = (
    "  g_EntryCount = count + 1;\n}\n",
    "  g_EntryCount = count + 1;\n}\n"
    "\n"
    f"/* {MARK}: one writer at a time; with the granules on, readers take the walk while the entries and the\n"
    " * granules change, and see both new afterwards. Off, the body runs as before (under the lock). */\n"
    "void BTCpu64IosAddAliasMapping(uint64_t PeBase, uint64_t JitBase, uint64_t Size) {\n"
    "  if (!__atomic_load_n(&IosAliasGranOn, __ATOMIC_ACQUIRE)) {\n"
    "    IosAliasAddMappingBody(PeBase, JitBase, Size); // off: exactly as before, no lock\n"
    "    return;\n"
    "  }\n"
    "  AliasWriteLock();\n"
    "  GranBegin();\n"
    "  IosAliasAddMappingBody(PeBase, JitBase, Size);\n"
    "  if (__atomic_load_n(&IosAliasGranOn, __ATOMIC_RELAXED)) {\n"
    "    GranRebuild();\n"
    "  }\n"
    "  GranEnd();\n"
    "  AliasWriteUnlock();\n"
    "}\n"
    "\n"
    f"/* {MARK}: MADEIRA_FEX_ALIAS_GRANULES=1 (Module.cpp, ProcessInit). Builds the granules of the entries\n"
    " * listed so far under the writer lock. Returns the granules used, or -1 when they did not fit. */\n"
    "int IosAliasGranulesEnable(void) {\n"
    "  AliasWriteLock();\n"
    "  GranBegin();\n"
    "  __atomic_store_n(&IosAliasGranOn, 1u, __ATOMIC_RELAXED);\n"
    "  GranRebuild();\n"
    "  const int Used = __atomic_load_n(&IosAliasGranOn, __ATOMIC_RELAXED) ? static_cast<int>(g_GranUsed) : -1;\n"
    "  GranEnd();\n"
    "  AliasWriteUnlock();\n"
    "  return Used;\n"
    "}\n",
)

ASM_MACRO = (
    ".macro IOS_LOAD_TEB reg\n"
    "  mrs \\reg, TPIDRRO_EL0\n"
    "  and \\reg, \\reg, #~7\n"
    "  ldr \\reg, [\\reg, #0x898]\n"
    ".endm\n",
    ".macro IOS_LOAD_TEB reg\n"
    "  mrs \\reg, TPIDRRO_EL0\n"
    "  and \\reg, \\reg, #~7\n"
    "  ldr \\reg, [\\reg, #0x898]\n"
    ".endm\n"
    f"// {MARK} (Playport 0071 \"alias\"): x9's 64 KB granule in IosAliasGranules (IosJitAlias.cpp). An empty\n"
    "// slot ends the probe: no image there, x9 stays, \\done. A whole granule's delta read with IosAliasGranGen\n"
    "// even and unmoved is added to x9, \\done. Anything else (off, a writer active, the count moved, a part\n"
    "// granule) falls through to the hint and walk. Clobbers x4, x16, x17, x23.\n"
    ".macro IOS_ALIAS_GRANULE_LOOKUP done\n"
    "  adrp x16, IosAliasGranOn\n"
    "  ldr w16, [x16, #:lo12:IosAliasGranOn]\n"
    "  tbz w16, #0, .Lios_gl_slow\\@\n"
    "  adrp x16, IosAliasGranGen\n"
    "  add x16, x16, #:lo12:IosAliasGranGen\n"
    "  ldar x23, [x16]\n"
    "  tbnz x23, #0, .Lios_gl_slow\\@\n"
    "  adrp x16, IosAliasGranules\n"
    "  add x16, x16, #:lo12:IosAliasGranules\n"
    "  lsr x17, x9, #16\n"
    "  add x17, x17, #1              // the slot key, granule + 1\n"
    "  bfi x17, x23, #40, #24        // the count's low 24 bits above it\n"
    "  ubfiz x4, x17, #4, #15        // 32768 slots of 16 bytes\n"
    ".Lios_gl_probe\\@:\n"
    "  ldr x23, [x16, x4]\n"
    "  cbz x23, \\done\n"
    "  eor x23, x23, x17\n"
    "  lsl x23, x23, #24\n"
    "  cbz x23, .Lios_gl_found\\@\n"
    "  add x4, x4, #16\n"
    "  and x4, x4, #0x7fff0\n"
    "  b .Lios_gl_probe\\@\n"
    ".Lios_gl_found\\@:\n"
    "  add x16, x16, x4\n"
    "  ldr x4, [x16, #8]\n"
    "  dmb ishld\n"
    "  adrp x16, IosAliasGranGen\n"
    "  ldr x23, [x16, #:lo12:IosAliasGranGen]\n"
    "  eor x23, x23, x17, lsr #40\n"
    "  lsl x23, x23, #40\n"
    "  cbnz x23, .Lios_gl_slow\\@\n"
    "  tbnz x4, #0, .Lios_gl_slow\\@\n"
    "  add x9, x9, x4\n"
    "  b \\done\n"
    ".Lios_gl_slow\\@:\n"
    ".endm\n",
)

ASM_JIT = (
    "  cbnz w17, ExitFunctionSuspendPoint\n"
    "  ldr x16, [x28, #IOS_FRAME_ALIAS_HINT]\n",
    "  cbnz w17, ExitFunctionSuspendPoint\n"
    f"  IOS_ALIAS_GRANULE_LOOKUP ios_ec_xlate_done // {MARK}\n"
    "  ldr x16, [x28, #IOS_FRAME_ALIAS_HINT]\n",
)

ASM_EC = (
    "  // regardless.\n"
    "  // ml1116: last-hit entry first, then the table newest-first.\n",
    "  // regardless.\n"
    f"  IOS_ALIAS_GRANULE_LOOKUP ios_ec_xlate_done // {MARK}\n"
    "  // ml1116: last-hit entry first, then the table newest-first.\n",
)

MOD_DECL = (
    'extern "C" uint32_t IosEcReturnWithRet;\n',
    'extern "C" uint32_t IosEcReturnWithRet;\n'
    f'extern "C" int IosAliasGranulesEnable(void); /* {MARK} (IosJitAlias.cpp) */\n',
)

MOD_INIT = (
    "  CTX->InitCore();\n",
    "#ifdef FEX_IOS_HOST\n"
    "  {\n"
    f"    /* {MARK}: MADEIRA_FEX_ALIAS_GRANULES=1 translates x64->EC call targets by one table probe\n"
    "     * (IosJitAlias.cpp, Module.S). Off by default. */\n"
    '    const char* GranOpt = getenv("MADEIRA_FEX_ALIAS_GRANULES");\n'
    '    if (GranOpt && strcmp(GranOpt, "1") == 0) {\n'
    "      const int Granules = IosAliasGranulesEnable();\n"
    '      LogMan::Msg::IFmt("FEX: alias-granules enabled granules={} (-1: too many, off)", Granules);\n'
    "    }\n"
    "  }\n"
    "#endif\n"
    "  CTX->InitCore();\n",
)

PLAN = {
    ALIAS: [ALIAS_GLOBALS, ALIAS_HELPERS, ALIAS_RENAME, ALIAS_WRAPPER],
    ASM: [ASM_MACRO, ASM_JIT, ASM_EC],
    MODULE: [MOD_DECL, MOD_INIT],
}


def main(argv):
    if len(argv) != 2:
        print(f"usage: {argv[0]} FEX-ROOT", file=sys.stderr)
        return 2
    root = Path(argv[1])
    texts = {rel: (root / rel).read_text() for rel in PLAN}
    if all(MARK in t for t in texts.values()):
        print("alias-granules: already applied")
        return 0
    if any(MARK in t for t in texts.values()):
        print("patch-fex-ios-alias-granules.py: partial overlay", file=sys.stderr)
        return 1
    out = {}
    for rel, pairs in PLAN.items():
        t = texts[rel]
        for old, new in pairs:
            if t.count(old) != 1:
                print(f"patch-fex-ios-alias-granules.py: {rel}: anchor moved: {old.strip().splitlines()[0][:70]!r}",
                      file=sys.stderr)
                return 1
            t = t.replace(old, new, 1)
        out[rel] = t
    for rel, t in out.items():
        (root / rel).write_text(t)
    print("FEX ARM64EC: x64->EC target granule table opt-in (MADEIRA_FEX_ALIAS_GRANULES=1)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
