#!/usr/bin/env python3
"""God of War dark characters: two tests on the GI volume lookup. Both OFF
unless set in the game file.

The deferred ambient compute shader (and the fog, luminance and a few forward
shaders) finds a GI brick through an RGBA8 3D indirection texture and decodes
its blue channel in floats: `frc(b * 63.75)` are the low two bits and
`b * 63.75 - frc` the brick's z. Where b is a multiple of 4 a conversion that
comes out one ulp low turns that into another brick (x + 4, z - 1).

  env.MADEIRA_GOW_GI_DECODE = 1  every 63.75 of a shader holding the
                                 (1020, 255, 63.75, 255) scale becomes 63.7501,
                                 so such a value stays on its own brick.
  env.MADEIRA_GOW_GI_OFF = 1     the ambient shader (the one that names
                                 ambientBuffer) takes its no-volume path: the
                                 `count > 0` test is made always false.

One 32-bit word per place changes in the bytecode airconv keeps; nothing
moves. Each switch has its own shader cache table (salts 128000, 256000).
`[gow-gi]` logs the switches and the first 16 patched shaders.

Needs tools/patch-airconv-gow-no-sparkle.py first. Native only; not in the
i386 farm key. Idempotent; fails by name if an anchor moves. Run from the
repository root.
"""
import pathlib
import sys

ROOT = pathlib.Path("dxmt/src")
MARKER = "madeira-doge: gow gi test"
NAME = "patch-airconv-gow-gi-test"

HELPER = r'''/* madeira-doge: gow gi test (tools/patch-airconv-gow-gi-test.py) --
 * MADEIRA_GOW_GI_DECODE=1 / MADEIRA_GOW_GI_OFF=1: God of War's GI volume
 * lookup, tolerant brick decode or no volumes at all (immediates only). */
static void madeira_gow_gi_test(std::vector<uint8_t> &bc) {
  static int dec = -1, off = -1;
  if (dec < 0) {
    const char *e = getenv("MADEIRA_GOW_GI_DECODE");
    dec = (e && e[0] == '1') ? 1 : 0;
    e = getenv("MADEIRA_GOW_GI_OFF");
    off = (e && e[0] == '1') ? 1 : 0;
    if (dec || off)
      fprintf(stderr, "[gow-gi] madeira-doge on: decode %d off %d (MADEIRA_GOW_GI_DECODE / MADEIRA_GOW_GI_OFF)\n",
              dec, off);
  }
  if ((!dec && !off) || bc.size() < 64 || bc.size() > (1u << 20) || (bc.size() & 3)) return;
  static const float scale[4] = {1020.0f, 255.0f, 63.75f, 255.0f};
  const uint8_t *sb = (const uint8_t *)scale;
  if (std::search(bc.begin(), bc.end(), sb, sb + sizeof scale) == bc.end()) return;
  auto rd = [&](size_t o) { uint32_t v; memcpy(&v, bc.data() + o, 4); return v; };
  unsigned ndec = 0, noff = 0;
  if (dec) {
    const uint32_t tol = 0x427f001au; /* 63.7501 */
    for (size_t o = 0; o + 4 <= bc.size(); o += 4)
      if (rd(o) == 0x427f0000u) { memcpy(bc.data() + o, &tol, 4); ndec++; }
  }
  static const char amb[] = "ambientBuffer";
  if (off && std::search(bc.begin(), bc.end(), amb, amb + sizeof amb - 1) != bc.end()) {
    /* ilt <dst>, l(0), cbN[0].x */
    const uint32_t never = 0x7fffffffu;
    for (size_t o = 0; o + 32 <= bc.size(); o += 4)
      if (rd(o) == 0x08000022u && rd(o + 12) == 0x00004001u && rd(o + 16) == 0u &&
          rd(o + 20) == 0x0020800au && rd(o + 28) == 0u) {
        memcpy(bc.data() + o + 16, &never, 4);
        noff++;
      }
  }
  static unsigned logged;
  if (logged++ < 16)
    fprintf(stderr, "[gow-gi] madeira-doge GI shader (%zu bytes): %u decode constant(s) widened, %u volume test(s) off\n",
            bc.size(), ndec, noff);
}

AIRCONV_API int SM50Initialize('''


def edit(rel, pairs, needs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: already patched")
        return
    if needs not in s:
        sys.exit(f"{NAME}: {rel} lacks '{needs}' -- run tools/patch-airconv-gow-no-sparkle.py first")
    for old, new, want in pairs:
        n = s.count(old)
        if n != want:
            sys.exit(f"{NAME}: anchor found {n} times (want {want}) in {rel}:\n{old}")
        s = s.replace(old, new)
    if MARKER not in s:
        sys.exit(f"{NAME}: marker missing after editing {rel}")
    path.write_text(s)
    print(f"{rel}: patched")


edit("airconv/dxbc_converter.cpp", [
    ("AIRCONV_API int SM50Initialize(", HELPER, 1),
    ("""  madeira_gow_no_sparkle(sm50_shader->bytecode);   /* madeira-doge: gow no sparkle */
""",
     """  madeira_gow_no_sparkle(sm50_shader->bytecode);   /* madeira-doge: gow no sparkle */
  madeira_gow_gi_test(sm50_shader->bytecode);   /* madeira-doge: gow gi test */
""", 1),
], needs="madeira-doge: gow no sparkle")

edit("winemetal/unix/cache.c", [
    ("""      if (v && v[0] == '1') salt += 32000; }
""",
     """      if (v && v[0] == '1') salt += 32000; }
    { const char *v = getenv("MADEIRA_GOW_GI_DECODE");   /* madeira-doge: gow gi test */
      if (v && v[0] == '1') salt += 128000; }
    { const char *v = getenv("MADEIRA_GOW_GI_OFF");   /* madeira-doge: gow gi test */
      if (v && v[0] == '1') salt += 256000; }
""", 1),
], needs="madeira-doge: gow no sparkle")
