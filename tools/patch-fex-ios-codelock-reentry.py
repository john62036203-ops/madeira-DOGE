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
  if (!CodeMutex.ios_lock_write_nested_aware()) {
    static std::atomic<uint32_t> MadNested {};
    const uint32_t N = MadNested.fetch_add(1, std::memory_order_relaxed);
    if (N < 4 || (N & 0xffff) == 0) {
      LogMan::Msg::EFmt("[fexlock] madeira-doge: nested invalidation {:X}+{:X} on the lock's owner dropped (#{})", Address, Size, N + 1);
    }
    return;
  }
  InvalidateIntervalInternalLocked(Address, Size);
  CodeMutex.unlock();
}
"""
if s.count(old) != 1:
    sys.exit("patch-fex-ios-codelock-reentry: anchor not found exactly once")
open(path, "w").write(s.replace(old, new))
print("patched")
