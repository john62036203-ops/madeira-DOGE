#!/usr/bin/env python3
"""A switch for the dynamic buffer pool's trim (source-built d3d11 only).

Sekiro, builds 140-142 (logs 2026-10-06/07): one to five minutes into play a
D3D11 worker thread writes through a buffer allocation whose Metal handle is
0, releases a Metal buffer that is already freed, and then reads through a
dead pointer inside d3d11. A destroyed BufferAllocation looks exactly like
that (its destructor clears the handle). DynamicBuffer::allocate's trim
(ml681/ml685) is the one place that destroys pooled allocations while the
buffer lives; upstream keeps them until the buffer dies. DXMT_DYN_TRIM=0 turns
the trim off, to learn whether it is involved. Unset, the trim runs as before.

Applied by tools/build-d3d11-dll.sh to its COPY of the sources, so only
d3d11-src.dll (env.MADEIRA_D3D11_SRC = 1) has the switch.
Usage: patch-dxmt-dyn-trim-switch.py <tree>/src/dxmt
Idempotent; fails by name if the anchor moves.
"""
import pathlib
import sys

path = pathlib.Path(sys.argv[1]) / "dxmt_dynamic.cpp"
s = path.read_text()
if "DXMT_DYN_TRIM" in s:
    print("dxmt_dynamic.cpp: already patched"); sys.exit(0)

old = "    if (en > DYN_KEEP_ELIGIBLE) {\n"
new = """    /* madeira-doge (tools/patch-dxmt-dyn-trim-switch.py): DXMT_DYN_TRIM=0 keeps every pooled allocation */
    static const bool mad_trim = [] {
      const bool on = env::getEnvVar("DXMT_DYN_TRIM") != "0";
      if (!on) ERR("[trim] madeira-doge: dynamic buffer pool trim OFF (DXMT_DYN_TRIM=0)");
      return on;
    }();
    if (mad_trim && en > DYN_KEEP_ELIGIBLE) {
"""
if s.count(old) != 1:
    sys.exit("patch-dxmt-dyn-trim-switch: anchor not found exactly once")
s = s.replace(old, new)
inc = '#include "dxmt_mem_census.hpp"\n'
if s.count(inc) != 1:
    sys.exit("patch-dxmt-dyn-trim-switch: include anchor not found exactly once")
s = s.replace(inc, inc + '#include "util_env.hpp"\n#include "log/log.hpp"\n', 1)
path.write_text(s)
print("dxmt_dynamic.cpp: patched")
