#!/usr/bin/env python3
"""A pooled FEX buffer is never NULL.

FEXCore's pooled allocator (ThreadPoolAllocator.h) hands each thread its 16 MB
IR buffer (DualIntrusiveAllocatorThreadPool) and returns it to the pool after
five idle seconds. On iOS every FEXMem allocation is confined to the emulator's
host-only band (AllocatorHooks.h, ml321/ml799) and returns nullptr when the
band has no room. ClaimBufferImpl stored that nullptr as a buffer: the thread
that claimed it computed List = Data + 8 MB = 0x800000 and IREmitter's
ResetWorkingList wrote the invalid node there.

Onimusha: Way of the Sword on a 63 GB map (no extended virtual addressing),
three sessions: "AV WRITE of 800010" at libarm64ecfex.dll+0xf4760 with
x8 = 0x800000, a few minutes into the scene; the game's own 4 MB heap blocks
share the band there.

Now: when the band refuses, every idle buffer in the pool is released and the
request is repeated; if it is still refused the buffer comes from an
unconstrained mapping (an IR scratch buffer holds no code pointers, so the
ml321 concern does not apply to it), and the event is logged once.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-pool-null.py FEX/FEXCore/include/FEXCore/Utils/ThreadPoolAllocator.h
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "madeira-doge: a pooled buffer is never NULL" in s:
    print("already patched"); sys.exit(0)

old = """    auto Data = Alloc(Size);
    return ClaimedBuffers.emplace(ClaimedBuffers.end(), new MemoryBuffer {Data, Size, ClockType::now()});
"""
new = """    auto Data = Alloc(Size);
    if (!Data) {
      /* madeira-doge: a pooled buffer is never NULL (tools/patch-fex-ios-pool-null.py).
       * The band refused: give back every idle buffer and ask again. */
      for (auto it : UnclaimedBuffers) {
        Free(it->Ptr, it->Size);
        delete it;
      }
      UnclaimedBuffers.clear();
      Data = Alloc(Size);
#ifdef _WIN32
      if (!Data) {
        Data = ::VirtualAlloc(nullptr, Size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
      }
#endif
      static std::atomic<uint32_t> Said {};
      if (Said.fetch_add(1) < 8) {
        LogMan::Msg::EFmt("[fex-pool] the band refused a {:#x} byte pooled buffer; {}", Size,
                          Data ? "served after releasing idle buffers or from an unconstrained mapping" : "NO MEMORY AT ALL");
      }
    }
    return ClaimedBuffers.emplace(ClaimedBuffers.end(), new MemoryBuffer {Data, Size, ClockType::now()});
"""
if old not in s:
    sys.exit("patch-fex-ios-pool-null: anchor not found in " + path)
s = s.replace(old, new, 1)
open(path, "w").write(s)
print("ThreadPoolAllocator.h: a refused pooled buffer is retried, then served unconstrained")
