#!/usr/bin/env python3
"""God of War: hand the game its last good exposure metering result when a frame's result is the known bad one.

Builds 643-647: the game maps a 16-byte staging buffer every frame (ResultBufFinal of luminancePartAio: -(sum X / sum Z),
GI ambient, sum Y / sum Z * 1000). Under Madeira the same scene gives two results at random, a normal one (first value
about 3..20, third about 3900..6500) and a wrong one (first about -0.9, third about 1020..1090) that says the scene is
very bright, so the game lowers its exposure and the picture goes dark. Four logs (11000+ maps): wrong results have the
first value in -0.97..-0.08 and the third in 1017..1470; normal ones 2.3..19.9 and 2619..6500, nothing in between. The owner's CAP marks match: normal picture =
normal values, dark picture = wrong values. The cause upstream of the readback is not found yet (constants, the readback
path, groupshared sync and the encoder optimiser are ruled out).

This is a workaround, not the fix: with env.MADEIRA_GOW_EXPOSURE_FILTER = 1, a READ map of a 16-byte staging resource
whose values fall in the wrong result's window (first in -1.5..0.5 and third in 900..1800) gets the last values that
were outside that window written over it before the game reads them. [exp-filter] logs the counts every 600 maps.

Applied by tools/build-d3d11-dll.sh to its copy of the sources, AFTER tools/patch-dxmt-rb-map-log.py (argument: that d3d11
directory). Source-built d3d11 only (env.MADEIRA_D3D11_SRC = 1). Idempotent; fails by name if the anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11") / "d3d11_context_imm.cpp"
MARKER = "madeira-doge: gow exposure filter"

OLD = """          TRACE("staging map ready");
"""
NEW = OLD + """          /* madeira-doge: gow exposure filter (tools/patch-dxmt-gow-exposure-filter.py) */
          if ((MapType & D3D11_MAP_READ) && staging->length == 16) {
            static const bool exp_filter = env::getEnvVar("MADEIRA_GOW_EXPOSURE_FILTER") == "1";
            if (exp_filter) {
              static float exp_good[4];
              static bool exp_have;
              static uint32_t exp_maps, exp_replaced, exp_bad_no_good;
              float exp_v[4];
              std::memcpy(exp_v, staging->mappedImmediateMemory(), 16);
              const bool exp_bad =
                  exp_v[0] > -1.5f && exp_v[0] < 0.5f && exp_v[2] > 900.0f && exp_v[2] < 1800.0f;
              exp_maps++;
              if (exp_bad) {
                if (exp_have) {
                  std::memcpy(staging->mappedImmediateMemory(), exp_good, 16);
                  exp_replaced++;
                } else {
                  exp_bad_no_good++;
                }
              } else if (exp_v[0] == exp_v[0] && exp_v[2] == exp_v[2] && exp_v[2] != 0.0f) {
                std::memcpy(exp_good, exp_v, 16);
                exp_have = true;
              }
              if (exp_maps == 1 || (exp_maps % 600) == 0)
                ERR("[exp-filter] madeira-doge: maps ", exp_maps, " replaced ", exp_replaced,
                    " bad before any good ", exp_bad_no_good, " last good ", exp_good[0], " ", exp_good[1], " ",
                    exp_good[2]);
            }
          }
"""
INC_OLD = '#include "dxmt_staging.hpp"\n'
INC_NEW = '#include "dxmt_staging.hpp"\n#include "util_env.hpp" /* madeira-doge: gow exposure filter */\n#include <cstring>\n#include <cstdint>\n'


def main():
    src = PATH.read_text()
    if MARKER in src:
        print("gow exposure filter: already applied")
        return 0
    for name, old in (("staging map ready", OLD), ("dxmt_staging include", INC_OLD)):
        if src.count(old) != 1:
            print(f"gow exposure filter: anchor '{name}' found {src.count(old)} times in {PATH}", file=sys.stderr)
            return 1
    PATH.write_text(src.replace(OLD, NEW).replace(INC_OLD, INC_NEW))
    print("gow exposure filter: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
