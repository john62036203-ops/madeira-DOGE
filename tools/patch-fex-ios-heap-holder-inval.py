#!/usr/bin/env python3
"""A thread that holds the process heap does not park on the code-invalidation lock.

FINAL FANTASY VII REMAKE through the Dock, build 695, 2026-11-23 23:57: the game
never drew a frame. Valve's MachineIDInfoThread (0124) loaded wbemprox.dll;
ImageTracker::HandleImageMap holds CodeInvalidationMutex exclusively and its thread
then waited for the process heap's critical section ("[heap-lock] ... waiter
tid=0124", "[fexlock] ... owner tid=0124"). The heap's owner (010c, IPC:CSteamEngine)
was inside a heap call whose arena change came back as a memory notification ->
InvalidateAlignedInterval -> InvalidateIntervalInternal -> the same mutex
("[fexlock] STUCK write-wait"). Each waits for the other for ever, and the main
thread waits for 010c.

A thread that owns the process heap's critical section now asks for the mutex
without parking: a few tries over about 20 ms, then the interval goes to the
pending queue tools/patch-fex-ios-codelock-reentry.py added (served by the next
caller that gets the lock) and the thread returns, so it can leave the heap. The
memory such a notification names is the heap's own arena. Every other caller is
unchanged. env.MADEIRA_FEX_HEAP_INVAL_DEFER = 0 restores the old wait.

Fork-local build patch (tools/build-xtajit64.sh), after
patch-fex-ios-codelock-reentry.py; not a contribution to FEX.
Usage: patch-fex-ios-heap-holder-inval.py FEX/Source/Windows/Common/InvalidationTracker.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "madeira-doge: heap holder" in s:
    print("already patched"); sys.exit(0)

old = """  if (!CodeMutex.ios_lock_write_nested_aware()) {
    static std::atomic<uint32_t> MadNested {};
"""
new = """  /* madeira-doge: heap holder (tools/patch-fex-ios-heap-holder-inval.py) */
  {
    static std::atomic<int> MadHeapOn {-1};
    int On = MadHeapOn.load(std::memory_order_relaxed);
    if (On < 0) {
      const char* Env = getenv("MADEIRA_FEX_HEAP_INVAL_DEFER");
      On = (Env && Env[0] == '0' && !Env[1]) ? 0 : 1;
      MadHeapOn.store(On, std::memory_order_relaxed);
    }
    bool MadOwnsHeap = false;
    if (On && MadTeb) {
      /* TEB+0x60 = PEB, PEB+0x30 = ProcessHeap; Wine's heap keeps its critical section 0x10 past the 'HEAP' magic.
       * RTL_CRITICAL_SECTION+0x10 = OwningThread, compared with TEB+0x48 (ClientId.UniqueThread). */
      static std::atomic<uint64_t> MadHeapSeen {}, MadHeapCs {};
      const uint64_t Peb = *reinterpret_cast<uint64_t*>(MadTeb + 0x60);
      const uint64_t Heap = Peb ? *reinterpret_cast<uint64_t*>(Peb + 0x30) : 0;
      uint64_t Cs = 0;
      if (Heap) {
        if (MadHeapSeen.load(std::memory_order_acquire) == Heap) {
          Cs = MadHeapCs.load(std::memory_order_acquire);
        } else {
          const auto* Words = reinterpret_cast<const uint32_t*>(Heap);
          for (uint32_t k = 0; k < 0x60; k++) {
            if (Words[k] == 0x50414548) {
              Cs = Heap + uint64_t {k} * 4 + 0x10;
              break;
            }
          }
          MadHeapCs.store(Cs, std::memory_order_release);
          MadHeapSeen.store(Heap, std::memory_order_release);
        }
      }
      const uint64_t Tid = *reinterpret_cast<uint32_t*>(MadTeb + 0x48);
      MadOwnsHeap = Cs && Tid && *reinterpret_cast<uint64_t*>(Cs + 0x10) == Tid;
    }
    if (MadOwnsHeap) {
      bool Got = false;
      for (int Try = 0; Try < 20 && !Got; Try++) {
        Got = CodeMutex.try_lock();
        if (!Got) {
          LARGE_INTEGER Delay;
          Delay.QuadPart = -10000; /* 1 ms */
          NtDelayExecution(false, &Delay);
        }
      }
      if (!Got) {
        static std::atomic<uint32_t> MadHeapDeferred {};
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
        const uint32_t N = MadHeapDeferred.fetch_add(1, std::memory_order_relaxed);
        if (N < 8 || (N & 0xfff) == 0) {
          LogMan::Msg::EFmt("[fexlock] madeira-doge: invalidation {:X}+{:X} asked for by the process heap's owner while the lock is "
                            "held: {} (#{}; MADEIRA_FEX_HEAP_INVAL_DEFER=0 waits instead)",
                            Address, Size, Queued ? "deferred" : "dropped, the queue is full", N + 1);
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
      return;
    }
  }
  if (!CodeMutex.ios_lock_write_nested_aware()) {
    static std::atomic<uint32_t> MadNested {};
"""
if s.count(old) != 1:
    sys.exit("patch-fex-ios-heap-holder-inval: anchor not found exactly once")
open(path, "w").write(s.replace(old, new))
print("patched")
