#!/usr/bin/env python3
"""Strong compare-exchange for texture atomics: retry a spurious weak failure.

Sekiro (logs 2026-10-15, builds 197-198): every one to three minutes the GPU
stops for ~10 s and iOS restarts it; every command buffer in flight is
"Discarded (victim of GPU error/recovery)". MetalFX off did not change it
(19:22 log). With encoder execution status on (19:02 log) the stuck buffer had
7 encoders completed and the next, the main scene pass, still running.

D3D's InterlockedCompareExchange (imm_atomic_cmp_exch) is a STRONG
compare-exchange. airconv lowers it on typed UAV textures to
air.atomic_compare_exchange_weak_explicit and returns the value it writes back
into `expected`. A weak exchange may fail spuriously: nothing is stored and
`expected` is left holding the current value -- which equals the comparand. The
shader then reads "original == compare", believes its store happened, and a
lock or work-queue built on it waits for an item that was never written until
the watchdog restarts the GPU. madeira_d3d12 hit exactly this in the Metal
Shader Converter's output (madeira-d3d12/src/unix/madeira_cas.cpp).

The texture path now loops while the exchange failed AND the value read back
equals the comparand (component x: typed UAV atomics are single-channel 32-bit),
which is the strong semantics D3D specifies. A real failure (the value differs)
leaves the loop at once. MADEIRA_CAS_RETRY=0 restores the single weak attempt.
The native shader cache gets its own table for each setting (salt +500), so
the first launch after this converts the shaders again.

Native only (airconv, winemetal); every DXMT game gets it. Run after the other
airconv/winemetal patches. Idempotent; fails by name if an anchor moves. Run
from the repository root.
"""
import pathlib
import sys

ROOT = pathlib.Path("dxmt/src")
MARKER = "madeira-doge: cas retry"


def edit(rel, pairs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: cas retry already patched")
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"patch-airconv-cas-retry: anchor found {s.count(old)} times (want 1) in {rel}:\n{old}")
        s = s.replace(old, new)
    if MARKER not in s:
        sys.exit(f"patch-airconv-cas-retry: marker missing after editing {rel}")
    path.write_text(s)
    print(f"{rel}: cas retry patched")


edit("airconv/nt/air_builder.cpp", [
    ('#include <format>\n',
     '#include <cstdlib>\n#include <format>\n'),
    ("""  AllocaInst *Alloca = builder.CreateAlloca(TyTexel, 0u);
  Value *Ptr = builder.CreateConstGEP1_64(TyTexel, Alloca, 0u);
  builder.CreateStore(CmpVec4, Ptr);

  Tys.push_back(TyTexel->getPointerTo());
  Ops.push_back(Alloca);
""",
     """  AllocaInst *Alloca = builder.CreateAlloca(TyTexel, 0u);
  Value *Ptr = builder.CreateConstGEP1_64(TyTexel, Alloca, 0u);

  /* madeira-doge: cas retry (tools/patch-airconv-cas-retry.py) -- D3D's
   * compare-exchange is strong; a spurious weak failure leaves `expected`
   * equal to the comparand, which reads as success. Retry exactly that case. */
  static const bool madeira_cas_retry = [] {
    const char *e = getenv("MADEIRA_CAS_RETRY");
    return !(e && e[0] == '0');
  }();
  BasicBlock *CasLoop = nullptr, *CasDone = nullptr;
  if (madeira_cas_retry) {
    auto *CasFn = builder.GetInsertBlock()->getParent();
    CasLoop = BasicBlock::Create(Context, "madeira_cas_retry", CasFn);
    CasDone = BasicBlock::Create(Context, "madeira_cas_done", CasFn);
    builder.CreateBr(CasLoop);
    builder.SetInsertPoint(CasLoop);
  }
  builder.CreateStore(CmpVec4, Ptr);

  Tys.push_back(TyTexel->getPointerTo());
  Ops.push_back(Alloca);
"""),
    ("""  auto Ret = builder.CreateCall(Fn, Ops);

  return {builder.CreateLoad(TyTexel, Ptr), Ret};
}
""",
     """  auto Ret = builder.CreateCall(Fn, Ops);

  if (madeira_cas_retry) {
    Value *Seen = builder.CreateLoad(TyTexel, Ptr);
    Value *SameX = builder.CreateICmpEQ(builder.CreateExtractElement(Seen, uint64_t(0)),
                                        builder.CreateExtractElement(CmpVec4, uint64_t(0)));
    Value *Spurious = builder.CreateAnd(builder.CreateNot(Ret), SameX);
    builder.CreateCondBr(Spurious, CasLoop, CasDone);
    builder.SetInsertPoint(CasDone);
  }

  return {builder.CreateLoad(TyTexel, Ptr), Ret};
}
"""),
])

edit("winemetal/unix/cache.c", [
    ("  return (uint64_t)salt * 1000000ull;\n",
     "  { /* madeira-doge: cas retry (tools/patch-airconv-cas-retry.py) -- own cache table */\n"
     "    const char *r = getenv(\"MADEIRA_CAS_RETRY\");\n"
     "    return (uint64_t)(salt + ((r && r[0] == '0') ? 0 : 500)) * 1000000ull; }\n"),
])
