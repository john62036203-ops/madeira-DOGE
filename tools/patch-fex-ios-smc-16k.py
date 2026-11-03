#!/usr/bin/env python3
"""Self-modifying-code write traps per 16 KB host page (opt-in, ARM64EC and WoW64 FEX on iOS).

The iOS host page is 16 KB and Wine gives it the union of its four 4 KB
pages' protections. FEX arms its write trap (PAGE_EXECUTE_READ) on single
4 KB pages, so a host page with one trapped and one writable 4 KB page stays
writable: writes to the trapped page never fault and FEX keeps running stale
translations. Ported from upstream willfaust/Madeira #518
(build/fex-patches/0001-windows-ios-smc-traps-per-16k-host-page.patch, The
Escapists 2 / Project Zomboid), without upstream's hot-page tracking, which
this fork's FEX pin does not have.

With MADEIRA_FEX_SMC_16K=1 in the environment: traps are armed and released
on whole 16 KB host pages, and a write fault invalidates the whole host page
and untraps each RWX 4 KB page in it with that page's own untrap protection.
Unset keeps FEX's 4 KB behaviour unchanged.

Usage: patch-fex-ios-smc-16k.py FEX/Source/Windows/Common/InvalidationTracker.cpp
"""
import sys

path = sys.argv[1]
src = open(path).read()
marker = "madeira-doge: MADEIRA_FEX_SMC_16K"
if marker in src:
    print("already patched")
    sys.exit(0)

def once(old, new, what):
    global src
    if src.count(old) != 1:
        sys.exit("patch-fex-ios-smc-16k: %s anchor found %d times" % (what, src.count(old)))
    src = src.replace(old, new)

# 1. helper before the namespace
ns = "namespace FEX::Windows {\n"
if src.count(ns) < 1:
    sys.exit("patch-fex-ios-smc-16k: namespace anchor not found")
helper = '''/* madeira-doge: MADEIRA_FEX_SMC_16K (tools/patch-fex-ios-smc-16k.py, from upstream #518):
 * 1 = self-modifying-code traps are armed, released and invalidated per 16 KB iOS host page. */
static bool MadeiraSmc16k() {
  static const bool On = [] {
    const char* E = getenv("MADEIRA_FEX_SMC_16K");
    const bool V = E && E[0] == '1';
    if (V) {
      LogMan::Msg::IFmt("[smc-16k] MADEIRA_FEX_SMC_16K: SMC write traps per 16 KB host page");
    }
    return V;
  }();
  return On;
}
static constexpr uint64_t MADEIRA_HOST_PAGE_SIZE = 0x4000;
static constexpr uint64_t MADEIRA_HOST_PAGE_MASK = ~(MADEIRA_HOST_PAGE_SIZE - 1);

'''
src = src.replace(ns, helper + ns, 1)
if "#include <cstdlib>" not in src:
    src = "#include <cstdlib>\n" + src

# 2. the write-fault path
old_fault = '''      InvalidateIntervalInternalLocked(FaultAddress & FEXCore::Utils::FEX_PAGE_MASK, FEXCore::Utils::FEX_PAGE_SIZE);

      // Invalidate, then unprotect the faulting page with the compilation lock held to ensure that any racing invalidations are not dropped.
      ULONG TmpProt;
      void* TmpAddress = reinterpret_cast<void*>(FaultAddress);
      SIZE_T TmpSize = 1;
      NtProtectVirtualMemory(NtCurrentProcess(), &TmpAddress, &TmpSize, UntrapProt, &TmpProt);
'''
new_fault = '''      if (MadeiraSmc16k()) {
        /* madeira-doge: MADEIRA_FEX_SMC_16K: the whole host page, every RWX 4 KB page in it
         * untrapped with its own protection (queried first, IntervalsLock released before
         * NtProtectVirtualMemory). */
        const uint64_t HostPage = FaultAddress & MADEIRA_HOST_PAGE_MASK;
        constexpr int N = MADEIRA_HOST_PAGE_SIZE / FEXCore::Utils::FEX_PAGE_SIZE;
        ULONG Prots[N] {};
        {
          std::shared_lock QLock(IntervalsLock);
          for (int i = 0; i < N; i++) {
            const uint64_t Page = HostPage + i * FEXCore::Utils::FEX_PAGE_SIZE;
            if (!((Page ^ FaultAddress) & FEXCore::Utils::FEX_PAGE_MASK)) {
              Prots[i] = UntrapProt;
            } else if (RWXIntervals.Query(Page).Enclosed) {
              Prots[i] = GetUntrapProt(Page);
            }
          }
        }
        InvalidateIntervalInternalLocked(HostPage, MADEIRA_HOST_PAGE_SIZE);
        for (int i = 0; i < N; i++) {
          if (!Prots[i]) {
            continue;
          }
          ULONG TmpProt;
          void* TmpAddress = reinterpret_cast<void*>(HostPage + i * FEXCore::Utils::FEX_PAGE_SIZE);
          SIZE_T TmpSize = FEXCore::Utils::FEX_PAGE_SIZE;
          NtProtectVirtualMemory(NtCurrentProcess(), &TmpAddress, &TmpSize, Prots[i], &TmpProt);
        }
      } else {
      InvalidateIntervalInternalLocked(FaultAddress & FEXCore::Utils::FEX_PAGE_MASK, FEXCore::Utils::FEX_PAGE_SIZE);

      // Invalidate, then unprotect the faulting page with the compilation lock held to ensure that any racing invalidations are not dropped.
      ULONG TmpProt;
      void* TmpAddress = reinterpret_cast<void*>(FaultAddress);
      SIZE_T TmpSize = 1;
      NtProtectVirtualMemory(NtCurrentProcess(), &TmpAddress, &TmpSize, UntrapProt, &TmpProt);
      }
'''
once(old_fault, new_fault, "HandleRWXAccessViolation")

# 3. arming / releasing traps
old_prot = '''bool InvalidationTracker::ProtectRWXIntervalsInternal(uint64_t Address, uint64_t Size, bool ForWriteLocked) {
  const auto End = Address + Size;
'''
new_prot = '''bool InvalidationTracker::ProtectRWXIntervalsInternal(uint64_t Address, uint64_t Size, bool ForWriteLocked) {
  if (MadeiraSmc16k() && Size) {
    /* madeira-doge: MADEIRA_FEX_SMC_16K: whole host pages (only RWX intervals inside are touched) */
    const uint64_t HostEnd = (Address + Size + MADEIRA_HOST_PAGE_SIZE - 1) & MADEIRA_HOST_PAGE_MASK;
    Address &= MADEIRA_HOST_PAGE_MASK;
    Size = HostEnd - Address;
  }
  const auto End = Address + Size;
'''
once(old_prot, new_prot, "ProtectRWXIntervalsInternal")

open(path, "w").write(src)
print("patched " + path)
