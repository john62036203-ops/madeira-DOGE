#!/usr/bin/env python3
"""A stuck code-invalidation lock report names the path its owner took.

RE Requiem demo, build 136: the lock stayed write-owned by a thread that was
parked in a guest wait, every other thread behind it. The report named the
thread, not why it held the lock. The one path that keeps the lock across a
call out of FEX (read-file into tracked pages) now tags its hold.

Fork-local build patch (tools/build-xtajit64.sh); not a contribution to FEX.
Usage: patch-fex-ios-codelock-why.py <FEX root>
Idempotent; fails by name if an anchor moved.
"""
import sys

root = sys.argv[1]


def edit(rel, pairs):
    path = root + "/" + rel
    s = open(path).read()
    if "madeira-doge: owner path" in s or "IosNoteWhy(1," in s:
        print("already patched: " + rel)
        return
    for old, add in pairs:
        if s.count(old) != 1:
            sys.exit("patch-fex-ios-codelock-why: anchor not found exactly once in " + rel + ": " + old.strip()[:50])
        s = s.replace(old, old + add)
    open(path, "w").write(s)
    print("patched: " + rel)


edit("FEXCore/include/FEXCore/Utils/WritePriorityMutex.h", [
    ("""  uint64_t IosStampAddress() const {
    return reinterpret_cast<uint64_t>(&Futex);
  }
""", """
  /* madeira-doge: the write owner says why it holds the lock across a call
   * out of FEX. Owner-only stores. */
  void IosNoteWhy(uint32_t Tag, uint64_t A, uint64_t B) {
    OwnerWhy = Tag;
    OwnerWhyA = A;
    OwnerWhyB = B;
  }
"""),
    ("""                      OwnerTeb, OwnerTid, OwnerDepth);
""", """    LogMan::Msg::EFmt("[fexlock] madeira-doge: owner path tag={} a={:x} b={:x} (1 = read-file into tracked pages; 0 = scoped)", OwnerWhy,
                      OwnerWhyA, OwnerWhyB);
"""),
    ("""  uint32_t OwnerDepth {};
""", """  uint32_t OwnerWhy {};
  uint64_t OwnerWhyA {};
  uint64_t OwnerWhyB {};
"""),
    ("""    OwnerDepth++;
""", """    OwnerWhy = 0;
"""),
])
edit("Source/Windows/ARM64EC/Module.cpp", [
    ("""    GetFrontendThreadData(ThreadState)->InLockedRWXRead = true;
    *InLockedRead = true;
""", """    CTX->GetCodeInvalidationMutex().IosNoteWhy(1, reinterpret_cast<uint64_t>(Address), static_cast<uint64_t>(Size));
"""),
])
