#!/usr/bin/env python3
"""DXBC `mad` as multiply + add instead of a fused multiply-add. OFF unless
`env.MADEIRA_DEFUSE_FMA = 1` is in the game file.

Port of upstream DXMT's d3d11.defuseFma (3Shain/dxmt 59bf42f, 2026-04-22, on by
default there for Shadow of the Tomb Raider; our pin predates it). airconv
turns every DXBC `mad` into a true fma. A game whose depth pre-pass and main
pass vertex shaders compute the same position, one compiled by FXC with `mad`
and the other with `mul` + `add`, then gets positions that differ in the last
bit, and the main pass's depth-EQUAL test fails on scattered pixels. D3D
drivers do not fuse `mad`, so on a PC both passes agree.

God of War (owner, 2026-11-20): white dots that stick to the characters; a
traced frame has a 469-draw depth-only pass followed by a 469-draw G-buffer
pass on the same depth target, and the dots have the colour of what is behind
the character. With the switch AIRBuilder::CreateFMA emits fmul + fadd (the
pre-raster stages already have contraction off, so it stays unfused there).

The shader cache gets its own table for the switch (salt 64000). Needs
tools/patch-airconv-gow-no-sparkle.py first (cache.c anchor). Native only; not
in the i386 farm key. Idempotent; fails by name if an anchor moves. Run from the
repository root.
"""
import pathlib
import sys

ROOT = pathlib.Path("dxmt/src")
MARKER = "madeira-doge: defuse fma"
NAME = "patch-airconv-defuse-fma"


def edit(rel, pairs, needs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: already patched")
        return
    if needs and needs not in s:
        sys.exit(f"{NAME}: {rel} lacks '{needs}' -- run the earlier airconv patches first")
    for old, new, want in pairs:
        n = s.count(old)
        if n != want:
            sys.exit(f"{NAME}: anchor found {n} times (want {want}) in {rel}:\n{old}")
        s = s.replace(old, new)
    if MARKER not in s:
        sys.exit(f"{NAME}: marker missing after editing {rel}")
    path.write_text(s)
    print(f"{rel}: patched")


edit("airconv/nt/air_builder.cpp", [
    ("""    debug << "invalid operation: fma has unmatched operand types.\\n";
    return nullptr; // TODO
  }
""",
     """    debug << "invalid operation: fma has unmatched operand types.\\n";
    return nullptr; // TODO
  }
  /* madeira-doge: defuse fma (tools/patch-airconv-defuse-fma.py) -- MADEIRA_DEFUSE_FMA=1:
   * DXBC mad as fmul + fadd, as upstream DXMT's d3d11.defuseFma (59bf42f). */
  {
    static const bool madeira_defuse_fma = [] {
      const char *e = getenv("MADEIRA_DEFUSE_FMA");
      const bool on = e && e[0] == '1';
      if (on)
        fprintf(stderr, "[defuse-fma] madeira-doge on: DXBC mad is compiled as multiply + add (MADEIRA_DEFUSE_FMA)\\n");
      return on;
    }();
    if (madeira_defuse_fma)
      return builder.CreateFAdd(builder.CreateFMul(X, Y), Z);
  }
""", 1),
    ("""#include "air_builder.hpp"
""",
     """#include "air_builder.hpp"
#include <cstdio>  /* madeira-doge: defuse fma */
#include <cstdlib>
""", 1),
], needs="")

edit("winemetal/unix/cache.c", [
    ("""      if (v && v[0] == '1') salt += 32000; }
""",
     """      if (v && v[0] == '1') salt += 32000; }
    { const char *v = getenv("MADEIRA_DEFUSE_FMA");   /* madeira-doge: defuse fma */
      if (v && v[0] == '1') salt += 64000; }
""", 1),
], needs="madeira-doge: gow no sparkle")
