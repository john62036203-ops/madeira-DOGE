#!/usr/bin/env python3
"""What the guest ran just before the decoder refused an instruction.

P3R Demo (builds 106-111) reaches "Invalid instruction in entry block" at the
same address every run, with a 32-bit value in rsp and 0x80000002 in rax. The
faults before it are now known to be handled correctly (build 111), so the
question is which guest code led there. Two records, both cheap:

  - the entry addresses of the last 64 blocks the decoder was asked for, printed
    when an instruction is refused ([bad-inst] path of patch-fex-ios-invalid-bytes.py,
    which must already be applied);
  - the first 300 CPUID calls of a process with what they returned.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-trace-tail.py FEX/FEXCore/Source/Interface/Core
Idempotent; fails by name if an anchor moved.
"""
import os, sys

d = sys.argv[1]
fe, ch = os.path.join(d, "Frontend.cpp"), os.path.join(d, "CPUID.h")
s = open(fe).read()
if "madeira-doge: block ring" in s:
    print("already patched"); sys.exit(0)

def sub(text, old, new, what):
    if text.count(old) != 1:
        sys.exit("patch-fex-ios-trace-tail: anchor for %s not found exactly once" % what)
    return text.replace(old, new)

s = sub(s, """    // Do a bit of pointer math to figure out where we are in code
    InstStream = AdjustAddrForSpecialRegion(_InstStream, EntryPoint, RIPToDecode);
""", """    {
      /* madeira-doge: block ring (tools/patch-fex-ios-trace-tail.py) */
      const uint32_t MadSlot = MadBlockRingNext.fetch_add(1, std::memory_order_relaxed);
      MadBlockRing[MadSlot & 63].store(RIPToDecode, std::memory_order_relaxed);
    }
    // Do a bit of pointer math to figure out where we are in code
    InstStream = AdjustAddrForSpecialRegion(_InstStream, EntryPoint, RIPToDecode);
""", "the block entry")

s = sub(s, """                                B[0], B[1], B[2], B[3], B[4], B[5], B[6], B[7], B[8], B[9], B[10], B[11], B[12], B[13], B[14], B[15]);
""", """                                B[0], B[1], B[2], B[3], B[4], B[5], B[6], B[7], B[8], B[9], B[10], B[11], B[12], B[13], B[14], B[15]);
              {
                /* madeira-doge: block ring, oldest first, eight to a line */
                const uint32_t MadEnd = MadBlockRingNext.load(std::memory_order_relaxed);
                const uint32_t MadCount = MadEnd < 64 ? MadEnd : 64;
                for (uint32_t i = 0; i < MadCount; i += 8) {
                  uint64_t R[8] = {};
                  for (uint32_t k = 0; k < 8 && i + k < MadCount; k++) {
                    R[k] = MadBlockRing[(MadEnd - MadCount + i + k) & 63].load(std::memory_order_relaxed);
                  }
                  LogMan::Msg::EFmt("[bad-inst] blocks decoded before it ({} of {}): {:X} {:X} {:X} {:X} {:X} {:X} {:X} {:X}", i, MadCount,
                                    R[0], R[1], R[2], R[3], R[4], R[5], R[6], R[7]);
                }
                /* ... and the code of the last six (they were decoded moments ago, so they are mapped) */
                for (uint32_t i = MadCount > 6 ? MadCount - 6 : 0; i < MadCount; i++) {
                  const uint64_t A = MadBlockRing[(MadEnd - MadCount + i) & 63].load(std::memory_order_relaxed);
                  uint8_t C[24] = {};
                  const uint64_t CLeft = 0x4000 - (A & 0x3fff);
                  if (A < 0x10000) continue;
                  std::memcpy(C, reinterpret_cast<const void*>(A), CLeft < 24 ? CLeft : 24);
                  LogMan::Msg::EFmt("[bad-inst] code at {:X}: {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} "
                                    "{:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x} {:02x}", A,
                                    C[0], C[1], C[2], C[3], C[4], C[5], C[6], C[7], C[8], C[9], C[10], C[11],
                                    C[12], C[13], C[14], C[15], C[16], C[17], C[18], C[19], C[20], C[21], C[22], C[23]);
                }
              }
""", "the [bad-inst] line")

# the ring itself, at namespace scope before the first function that uses it
s = sub(s, """bool Decoder::CheckRangeExecutable(uint64_t Address, uint64_t Size) {
""", """/* madeira-doge: block ring (tools/patch-fex-ios-trace-tail.py) */
static std::atomic<uint32_t> MadBlockRingNext {};
static std::atomic<uint64_t> MadBlockRing[64] {};

bool Decoder::CheckRangeExecutable(uint64_t Address, uint64_t Size) {
""", "the ring definition")
open(fe, "w").write(s)

h = open(ch).read()
h = sub(h, """  FEXCore::CPUID::FunctionResults RunFunction(uint32_t Function, uint32_t Leaf) const {
    if (Function < Primary.size()) {
""", """  FEXCore::CPUID::FunctionResults RunFunction(uint32_t Function, uint32_t Leaf) const {
    /* madeira-doge: the first CPUID calls of a process (tools/patch-fex-ios-trace-tail.py) */
    const auto MadRes = MadRunFunction(Function, Leaf);
    static std::atomic<uint32_t> MadSaid {};
    if (MadSaid.fetch_add(1, std::memory_order_relaxed) < 300) {
      LogMan::Msg::EFmt("[cpuid] {:X}.{:X} -> {:08X} {:08X} {:08X} {:08X}", Function, Leaf, MadRes.eax, MadRes.ebx, MadRes.ecx, MadRes.edx);
    }
    return MadRes;
  }

  FEXCore::CPUID::FunctionResults MadRunFunction(uint32_t Function, uint32_t Leaf) const {
    if (Function < Primary.size()) {
""", "CPUID RunFunction")
if "#include <atomic>" not in h:
    h = h.replace("#pragma once\n", "#pragma once\n#include <atomic>\n", 1)
if "LogManager.h" not in h:
    h = h.replace("#pragma once\n", "#pragma once\n#include <FEXCore/Utils/LogManager.h>\n", 1)
open(ch, "w").write(h)
print("patched " + fe + " and " + ch)
