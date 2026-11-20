#!/usr/bin/env python3
"""God of War: switch off the material "sparkle" glints. OFF unless
`env.MADEIRA_GOW_NO_SPARKLE = 1` is in the game file.

Under Madeira the characters are covered in white and blue dots that stick to
their surface (owner, 2026-11-19/20; not the reflection / occlusion settings,
not MADEIRA_PS_CLAMP, BOUNDS_EXTRA, PRECISE_MATH, SAMPLE_L_BIAS, the mip clamp
or MADEIRA_DXMT_UPSTREAM_FIXES). The game's layered material pixel shaders
(52 of the 583 dumped) have a procedural sparkle: per 1/225 UV cell a hashed
normal and an intensity `pow(sparkleMap * layerWeight, 32) * 2 *
sparkleIntensityScale`, the last one read as `add rN.w, cb3[38].w, cb3[38].w`.
Why it shows so strongly here is not known yet.

With the switch that one instruction becomes `xor rN.w, cb3[38].w, cb3[38].w`
(same length and operands, result 0.0) in the bytecode airconv keeps for
compilation, so the sparkle term is zero. Only a shader whose reflection names
sparkleIntensityScale is touched, and only an `add` whose two sources are both
cb3[38].w and that is followed by the `* 32` of the pow. The shader cache gets
its own table for the switch (salt 32000). `[gow-sparkle]` logs the switch and
each patched shader (first 8).

Needs tools/patch-airconv-gow-lum-default.py first. Native only; not in the
i386 farm key. Idempotent; fails by name if an anchor moves. Run from the
repository root.
"""
import pathlib
import sys

ROOT = pathlib.Path("dxmt/src")
MARKER = "madeira-doge: gow no sparkle"
NAME = "patch-airconv-gow-no-sparkle"

HELPER = r'''/* madeira-doge: gow no sparkle (tools/patch-airconv-gow-no-sparkle.py) --
 * MADEIRA_GOW_NO_SPARKLE=1: God of War's material sparkle intensity is zero
 * (`add rN.w, cb3[38].w, cb3[38].w` becomes `xor` in the kept bytecode). */
static void madeira_gow_no_sparkle(std::vector<uint8_t> &bc) {
  static int on = -1;
  if (on < 0) {
    const char *e = getenv("MADEIRA_GOW_NO_SPARKLE");
    on = (e && e[0] == '1') ? 1 : 0;
    if (on)
      fprintf(stderr, "[gow-sparkle] madeira-doge on: material sparkle intensity forced to zero "
                      "(MADEIRA_GOW_NO_SPARKLE)\n");
  }
  if (!on || bc.size() < 64 || bc.size() > (1u << 20) || (bc.size() & 3)) return;
  static const char name[] = "sparkleIntensityScale";
  if (std::search(bc.begin(), bc.end(), name, name + sizeof name - 1) == bc.end()) return;
  auto rd = [&](size_t o) { uint32_t v; memcpy(&v, bc.data() + o, 4); return v; };
  const uint32_t nchunks = rd(28);
  if (nchunks > 64 || 32 + 4ull * nchunks > bc.size()) return;
  unsigned patched = 0;
  for (uint32_t c = 0; c < nchunks; c++) {
    const size_t co = rd(32 + 4 * c);
    if (co + 8 > bc.size()) continue;
    const uint32_t tag = rd(co), len = rd(co + 4);
    if (tag != 0x58454853u /* SHEX */ && tag != 0x52444853u /* SHDR */) continue;
    if (co + 8 + (size_t)len > bc.size() || len < 8) continue;
    const size_t base = co + 8, ntok = len / 4;
    size_t i = 2;
    while (i < ntok) {
      const uint32_t t = rd(base + 4 * i);
      const uint32_t op = t & 0x7ffu;
      uint32_t l = (t >> 24) & 0x7fu;
      if (op == 0x35u) { if (i + 1 >= ntok) break; l = rd(base + 4 * (i + 1)); }
      if (!l || i + l > ntok) break;
      /* add <dst>, cb3[38].w, cb3[38].w : 9 tokens */
      if (op == 0u && l == 9 && rd(base + 4 * (i + 3)) == 0x0020803au && rd(base + 4 * (i + 4)) == 3u &&
          rd(base + 4 * (i + 5)) == 38u && rd(base + 4 * (i + 6)) == 0x0020803au &&
          rd(base + 4 * (i + 7)) == 3u && rd(base + 4 * (i + 8)) == 38u) {
        bool pow32 = false;
        for (size_t k = i + 9; k < ntok && k < i + 9 + 24; k++)
          if (rd(base + 4 * k) == 0x42000000u) pow32 = true;
        if (pow32) {
          const uint32_t x = (t & ~0x7ffu) | 0x57u; /* D3D10_SB_OPCODE_XOR */
          memcpy(bc.data() + base + 4 * i, &x, 4);
          patched++;
        }
      }
      i += l;
    }
  }
  static unsigned logged;
  if (logged++ < 8)
    fprintf(stderr, "[gow-sparkle] madeira-doge material shader (%zu bytes): %u sparkle term(s) zeroed\n",
            bc.size(), patched);
}

AIRCONV_API int SM50Initialize('''


def edit(rel, pairs, needs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: already patched")
        return
    if needs not in s:
        sys.exit(f"{NAME}: {rel} lacks '{needs}' -- run tools/patch-airconv-gow-lum-default.py first")
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
    ("""  madeira_gow_lum_default(sm50_shader->bytecode);   /* madeira-doge: gow lum default */
""",
     """  madeira_gow_lum_default(sm50_shader->bytecode);   /* madeira-doge: gow lum default */
  madeira_gow_no_sparkle(sm50_shader->bytecode);   /* madeira-doge: gow no sparkle */
""", 1),
], needs="madeira-doge: gow lum default")

edit("winemetal/unix/cache.c", [
    ("""      if (v && v[0] == '1') salt += 16000; }
""",
     """      if (v && v[0] == '1') salt += 16000; }
    { const char *v = getenv("MADEIRA_GOW_NO_SPARKLE");   /* madeira-doge: gow no sparkle */
      if (v && v[0] == '1') salt += 32000; }
""", 1),
], needs="madeira-doge: gow lum default")
