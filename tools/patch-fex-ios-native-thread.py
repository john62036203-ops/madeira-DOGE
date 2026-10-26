#!/usr/bin/env python3
"""A thread without a CHPE CPU area has no FEX thread state.

ThreadCPUArea reads TEB->ChpeV2CpuAreaInfo and dereferences it for StateFrame()
and ThreadState(). Madeira only allocates that area for threads that belong to an
x64 image (thread_ios.c: "NOT setting cpu_area (owner machine=0xaa64 ...)"), but
ntdll's ARM64EC syscall wrappers notify the module from EVERY thread of the
session: a native AArch64 Wine child's first NtAllocateVirtualMemory went
NotifyMemoryAlloc -> GetCPUArea().ThreadState() -> load from NULL+0x38
(jittest_arm64.exe 2026-10-26 22:05, libarm64ecfex.dll+0x113e78, lr ntdll+0x58ffc).

Now: with no CPU area, StateFrame() and ThreadState() are a null pointer held in
a shared static slot (by reference, so the callers still compile; nothing ever
stores a non-null value there, since ThreadInit only runs on threads with an
area), and every notification that guards on ThreadState() returns as it does
for a thread FEX has not initialised. Not a thread_local: ml412 -- mingw TLS
goes through TEB->ThreadLocalStoragePointer, which can still be NULL here.
ThreadInit and the exception paths are reached only from threads that do have
an area, so they are unchanged.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-native-thread.py FEX/Source/Windows/ARM64EC/Module.cpp
Idempotent; fails by name if the anchor moved.
"""
import sys

path = sys.argv[1]
s = open(path).read()
if "madeira-doge: no CPU area, no thread state" in s:
    print("already patched"); sys.exit(0)

old = """  FEXCore::Core::CpuStateFrame*& StateFrame() const {
    return reinterpret_cast<FEXCore::Core::CpuStateFrame*&>(Area->EmulatorData[0]);
  }

  FEXCore::Core::InternalThreadState*& ThreadState() const {
    return reinterpret_cast<FEXCore::Core::InternalThreadState*&>(Area->EmulatorData[1]);
  }
"""
new = """  /* madeira-doge: no CPU area, no thread state (tools/patch-fex-ios-native-thread.py).
   * A native AArch64 thread of this session never gets a CHPE area, yet ntdll's
   * ARM64EC syscall wrappers notify the module from it too. Answer "not initialised"
   * (a shared null slot, by reference; ml412: no thread_local in this module)
   * instead of dereferencing NULL. Nothing stores a non-null value through it:
   * ThreadInit only runs on threads that do have an area. */
  static uint64_t& NullSlot() {
    static uint64_t Slot = 0;
    Slot = 0;
    return Slot;
  }

  FEXCore::Core::CpuStateFrame*& StateFrame() const {
    if (!Area) return reinterpret_cast<FEXCore::Core::CpuStateFrame*&>(NullSlot());
    return reinterpret_cast<FEXCore::Core::CpuStateFrame*&>(Area->EmulatorData[0]);
  }

  FEXCore::Core::InternalThreadState*& ThreadState() const {
    if (!Area) return reinterpret_cast<FEXCore::Core::InternalThreadState*&>(NullSlot());
    return reinterpret_cast<FEXCore::Core::InternalThreadState*&>(Area->EmulatorData[1]);
  }
"""
if old not in s:
    sys.exit("patch-fex-ios-native-thread: anchor not found in " + path)
s = s.replace(old, new, 1)
open(path, "w").write(s)
print("Module.cpp: a thread without a CHPE CPU area reports no FEX thread state")
