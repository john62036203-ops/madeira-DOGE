#!/usr/bin/env python3
"""God of War darkening experiment: the luminance compute shader ignores the GI
volumes. OFF unless `env.MADEIRA_GOW_LUM_DEFAULT = 1` is in the game file.

The game's luminancePartAio compute shader returns, as the second of four
floats the CPU reads back, the GI ambient luminance at the camera: with GI
volumes loaded it samples their 3D textures, without any it uses the default
ambient from its constants. The picture goes black exactly while that value is
~100x smaller than usual ([rb-buf], 2026-11-18), and the dumped volume
textures do hold such cells. With the switch the shader's `count > 0` test
(`ilt r0.x, l(0), cb2[0].x`) is made always false in the bytecode airconv
keeps for compilation, so the value is always the default one -- the same
path the game itself takes where no volume is loaded. If the blackouts stop,
that value is what drives them.

Only a shader whose reflection names luminancePartAio and that holds the
instruction exactly once is touched; one 32-bit immediate changes, nothing
moves. The shader cache gets its own table for the switch (salt 16000).
`[gow-lum]` logs the switch and each patched shader (first 8).

Needs tools/patch-airconv-gow-experiments.py first, on a dxmt pin that keeps
`bytecode` per shader (db546ee). Native only; not in the i386 farm key.
Idempotent; fails by name if an anchor moves. Run from the repository root.
"""
import pathlib
import sys

ROOT = pathlib.Path("dxmt/src")
MARKER = "madeira-doge: gow lum default"
NAME = "patch-airconv-gow-lum-default"

HELPER = r'''/* madeira-doge: gow lum default (tools/patch-airconv-gow-lum-default.py) --
 * MADEIRA_GOW_LUM_DEFAULT=1: God of War's luminance compute shader takes its
 * no-GI-volume path always (one immediate of the kept bytecode changes). */
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
static void madeira_gow_lum_default(std::vector<uint8_t> &bc) {
  static int on = -1;
  if (on < 0) {
    const char *e = getenv("MADEIRA_GOW_LUM_DEFAULT");
    on = (e && e[0] == '1') ? 1 : 0;
    if (on)
      fprintf(stderr, "[gow-lum] madeira-doge on: the luminance compute shader ignores the GI volumes "
                      "(MADEIRA_GOW_LUM_DEFAULT)\n");
  }
  if (!on || bc.size() < 64 || bc.size() > (1u << 20)) return;
  static const char name[] = "luminancePartAio";
  if (std::search(bc.begin(), bc.end(), name, name + sizeof name - 1) == bc.end()) return;
  /* ilt r0.x, l(0), cb2[0].x */
  static const uint32_t pat[8] = {0x08000022u, 0x00100012u, 0u, 0x00004001u, 0u, 0x0020800au, 2u, 0u};
  unsigned hits = 0;
  size_t at = 0;
  for (size_t o = 0; o + sizeof pat <= bc.size(); o += 4)
    if (!memcmp(bc.data() + o, pat, sizeof pat)) { hits++; at = o; }
  static unsigned logged;
  if (hits != 1) {
    if (logged++ < 8)
      fprintf(stderr, "[gow-lum] madeira-doge luminance shader (%zu bytes) left alone: instruction found %u times\n",
              bc.size(), hits);
    return;
  }
  const uint32_t never = 0x7fffffffu;
  memcpy(bc.data() + at + 16, &never, 4);
  if (logged++ < 8)
    fprintf(stderr, "[gow-lum] madeira-doge patched a luminance shader (%zu bytes): default ambient, no GI volume lookup\n",
            bc.size());
}

AIRCONV_API int SM50Initialize('''


def edit(rel, pairs, needs):
    path = ROOT / rel
    s = path.read_text()
    if MARKER in s:
        print(f"{rel}: already patched")
        return
    if needs not in s:
        sys.exit(f"{NAME}: {rel} lacks '{needs}' -- run tools/patch-airconv-gow-experiments.py first")
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
    ("""  sm50_shader->bytecode.assign(
    (const uint8_t *)pBytecode, (const uint8_t *)pBytecode + BytecodeSize
  );
""",
     """  sm50_shader->bytecode.assign(
    (const uint8_t *)pBytecode, (const uint8_t *)pBytecode + BytecodeSize
  );
  madeira_gow_lum_default(sm50_shader->bytecode);   /* madeira-doge: gow lum default */
""", 1),
], needs="madeira-bcd: gow experiments")

edit("winemetal/unix/cache.c", [
    ("""        if (v && v[0] == '1') salt += 1000 << i;
      } }
""",
     """        if (v && v[0] == '1') salt += 1000 << i;
      } }
    { const char *v = getenv("MADEIRA_GOW_LUM_DEFAULT");   /* madeira-doge: gow lum default */
      if (v && v[0] == '1') salt += 16000; }
""", 1),
], needs="madeira-bcd: gow experiments")
