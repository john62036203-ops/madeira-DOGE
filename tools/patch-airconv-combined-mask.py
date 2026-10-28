#!/usr/bin/env python3
"""ExtractFromCombinedMask: the component index inside the COMPACTED operand.

Two-destination instructions (udiv, umul/imul, uaddc, usubb, sincos, swapc)
load their sources once with the union of both destination masks and split
them with ExtractFromCombinedMask. LoadOperand returns that union COMPACTED:
for dst masks .x and .w the source is a <2 x i32> (x, w). The single-component
shortcut extracted element __builtin_ctz(Mask) -- 3 for .w -- out of that
2-element vector, which is poison in LLVM; the optimiser then folds every
value computed from it to poison.

Ninja's Dawn (Xenia's EDRAM dump kernel, build 539): `udiv r1.x, r0.w, r0.w,
r1.x` splits a tile index into row (r1.x) and column (r0.w). The column became
poison, so the texture coordinate did, so the whole `ld` was folded away and
every dumped EDRAM tile was written as 0 -- the title screen (and every other
resolved picture) came out black. Contiguous masks starting at .x (.x/.y,
.xy/.zw) were unaffected because ctz equals the compacted index there.

The index is the number of combined-mask components below the wanted one.
Idempotent; fails by name if the anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/airconv/nt/dxbc_converter_base.hpp")
MARKER = "madeira-doge: combined-mask index"

OLD = """      case 0b1000:
        return ir.CreateExtractElement(Value, __builtin_ctz(Mask));"""
NEW = """      case 0b1000:
        /* madeira-doge: combined-mask index -- Value holds only the CombinedMask
         * components, compacted (tools/patch-airconv-combined-mask.py) */
        return ir.CreateExtractElement(Value, (uint64_t)__builtin_popcount(CombinedMask & (Mask - 1)));"""

src = PATH.read_text()
if MARKER in src:
    print(f"{PATH}: already patched")
    sys.exit(0)
if src.count(OLD) != 1:
    sys.exit(f"patch-airconv-combined-mask: anchor found {src.count(OLD)} times (want 1) in {PATH}")
PATH.write_text(src.replace(OLD, NEW))
print(f"{PATH}: patched (ExtractFromCombinedMask indexes the compacted operand)")
