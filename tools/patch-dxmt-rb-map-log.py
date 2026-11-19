#!/usr/bin/env python3
"""Log what a game sees when it maps a small staging resource for reading.

God of War's exposure: the [rb-buf] probe (winemetal side) reads the PREVIOUS copy's destination at the next copy and is
throttled to two lines a second, so it cannot tell which resource a value came from, nor whether the game saw that value.
This logs, in the Direct3D 11 Map itself, the first 16 bytes the game is handed for every READ map of a staging resource of
at most 256 bytes: resource, length, the recording / finished / ready sequence numbers and four floats.

  [rb-map] #n res <id> len <bytes> seq <recording> done <finished> ready <readable after> v <f0> <f1> <f2> <f3>

Off unless env.MADEIRA_RB_MAP_LOG = 1 (source-built d3d11 only: env.MADEIRA_D3D11_SRC = 1). 12000 lines a session.
Applied by tools/build-d3d11-dll.sh to its copy of the sources (argument: that d3d11 directory).
Idempotent; fails by name if the anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/d3d11") / "d3d11_context_imm.cpp"
MARKER = "madeira-doge: small readback map log"

OLD = """          TRACE("staging map ready");
          pMappedResource->pData = staging->mappedImmediateMemory();
"""
NEW = """          TRACE("staging map ready");
          /* madeira-doge: small readback map log (tools/patch-dxmt-rb-map-log.py) */
          if ((MapType & D3D11_MAP_READ) && staging->length <= 256) {
            static const bool rb_map_log = env::getEnvVar("MADEIRA_RB_MAP_LOG") == "1";
            static uint32_t rb_map_n;
            if (rb_map_log && ++rb_map_n <= 12000) {
              float rb_v[4] = {0.0f, 0.0f, 0.0f, 0.0f};
              std::memcpy(rb_v, staging->mappedImmediateMemory(), staging->length < 16 ? staging->length : 16);
              ERR("[rb-map] #", rb_map_n, " res ", uint64_t(uintptr_t(pResource)) & 0xffffff, " len ",
                  uint64_t(staging->length), " seq ", current_seq_id, " done ", coherent_seq_id, " ready ",
                  uint64_t(staging->readableAfterSeq()), " v ", rb_v[0], " ", rb_v[1], " ", rb_v[2], " ", rb_v[3]);
            }
          }
          pMappedResource->pData = staging->mappedImmediateMemory();
"""
INC_OLD = '#include "dxmt_staging.hpp"\n'
INC_NEW = '#include "dxmt_staging.hpp"\n#include "util_env.hpp" /* madeira-doge: small readback map log */\n#include <cstring>\n#include <cstdint>\n'


def main():
    src = PATH.read_text()
    if MARKER in src:
        print("rb-map log: already applied")
        return 0
    for name, old in (("staging map ready", OLD), ("dxmt_staging include", INC_OLD)):
        if src.count(old) != 1:
            print(f"rb-map log: anchor '{name}' found {src.count(old)} times in {PATH}", file=sys.stderr)
            return 1
    src = src.replace(OLD, NEW).replace(INC_OLD, INC_NEW)
    PATH.write_text(src)
    print("rb-map log: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
