#!/usr/bin/env python3
"""Keep an invalidation from waiting on the code-invalidation lock its own thread holds.

MHR with per-instruction validation in its writable start-up section (and, the
night before, with FEX_SMCCHECKS=full): the main thread parked for good,
  [fexlock] STUCK write-wait on mutex ... write-owned=true ... owner tid=00a8
with 00a8 the waiter itself. An invalidation holds CodeInvalidationMutex
exclusively while it drops blocks; memory FEX frees or maps there comes back as
a memory notification -> InvalidateAlignedInterval -> InvalidateIntervalInternal
-> the same lock, which is not recursive. Page-tracked SMC invalidates rarely;
validation invalidates on every changed byte, so the nested case is reached at once.

InvalidateIntervalInternal now takes the lock through the mutex's own
owner-aware entry (ios_lock_write_nested_aware, already in the tree, unused):
on the owning thread it returns without locking, and the nested request is
dropped -- it names FEX's own memory, raised under the lock, the same reasoning
as tools/patch-fex-ios-intervals-reentry.py. The first few are logged.

A thread that holds the lock SHARED (compiling) cannot take it exclusively
either: the request is queued and served by the next caller that gets the lock.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-codelock-reentry.py FEX/Source/Windows/Common/InvalidationTracker.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "madeira-doge: code-invalidation lock re-entry" in s:
    print("already patched"); sys.exit(0)

old = """void InvalidationTracker::InvalidateIntervalInternal(uint64_t Address, uint64_t Size) {
  std::scoped_lock CodeLock(CTX.GetCodeInvalidationMutex());
  InvalidateIntervalInternalLocked(Address, Size);
}
"""
new = """void InvalidationTracker::InvalidateIntervalInternal(uint64_t Address, uint64_t Size) {
  /* madeira-doge: code-invalidation lock re-entry (tools/patch-fex-ios-codelock-reentry.py) */
  auto& CodeMutex = CTX.GetCodeInvalidationMutex();
  /* A thread that holds this lock SHARED (it is compiling) and is told that
   * memory went away must not ask for it exclusively: the writer waits for the
   * readers to leave and one of them is itself. Onimusha parked two threads
   * that way while loading a scene, four launches in eleven (build 128-132:
   * [census-hold] ... HOLDS fexlock, waiting, the rest of the process behind
   * them). The interval is kept and invalidated by the next caller that does
   * get the lock. One word per interval: page number << 16 | pages. */
  static std::atomic<uint64_t> MadPending[64] {};
  uint64_t MadTeb = 0;
#if defined(ARCHITECTURE_arm64) || defined(ARCHITECTURE_arm64ec)
  __asm volatile("mov %0, x18" : "=r"(MadTeb));
#endif
  if (MadTeb && *reinterpret_cast<uint32_t*>(MadTeb + 0x16f0) != 0 &&
      *reinterpret_cast<uint64_t*>(MadTeb + 0x16f8) == CodeMutex.IosStampAddress()) {
    static std::atomic<uint32_t> MadShared {};
    uint64_t Pages = (Size + (Address & 0xfff) + 0xfff) >> 12;
    if (Pages == 0) Pages = 1;
    if (Pages > 0xffff) Pages = 0xffff;
    const uint64_t Packed = (Address >> 12) << 16 | Pages;
    bool Queued = false;
    for (auto& Slot : MadPending) {
      uint64_t Empty = 0;
      if (Slot.compare_exchange_strong(Empty, Packed, std::memory_order_acq_rel)) {
        Queued = true;
        break;
      }
    }
    const uint32_t N = MadShared.fetch_add(1, std::memory_order_relaxed);
    if (N < 8 || (N & 0xfff) == 0) {
      LogMan::Msg::EFmt("[fexlock] madeira-doge: invalidation {:X}+{:X} asked for by a thread that holds the lock shared: {} (#{})", Address, Size,
                        Queued ? "deferred" : "dropped, the queue is full", N + 1);
    }
    return;
  }
  if (!CodeMutex.ios_lock_write_nested_aware()) {
    static std::atomic<uint32_t> MadNested {};
    const uint32_t N = MadNested.fetch_add(1, std::memory_order_relaxed);
    if (N < 4 || (N & 0xffff) == 0) {
      LogMan::Msg::EFmt("[fexlock] madeira-doge: nested invalidation {:X}+{:X} on the lock's owner dropped (#{})", Address, Size, N + 1);
    }
    return;
  }
  for (auto& Slot : MadPending) {
    const uint64_t Packed = Slot.exchange(0, std::memory_order_acq_rel);
    if (Packed) {
      InvalidateIntervalInternalLocked((Packed >> 16) << 12, (Packed & 0xffff) << 12);
    }
  }
  InvalidateIntervalInternalLocked(Address, Size);
  CodeMutex.unlock();
}
"""
if s.count(old) != 1:
    sys.exit("patch-fex-ios-codelock-reentry: anchor not found exactly once")
open(path, "w").write(s.replace(old, new))
print("patched")
