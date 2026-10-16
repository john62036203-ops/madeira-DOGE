#!/usr/bin/env python3
"""DynamicBuffer::allocate walks only the part of its queue it needs (source-built d3d11 only).

Monster Hunter World (build 206, 2026-10-16) calls UpdateSubresource about
100,000 times a second; every call reaches DynamicBuffer::allocate, and that
function was the hottest ARM64EC code in the process. On each call it walks the
whole retained queue for the ml681 census (eligible/ineligible bytes, the
oldest and newest fence, an 8-entry duplicate check per entry) before the trim.
The trim itself only needs the number of entries the GPU has finished with,
and those are exactly the front run of the queue (entries are pushed in fence
order, which is what makes the trim safe).

Now the walk stops at the first entry still in use, so the trim sees the same
count, and the full census walk (with its statistics) runs on one call in 256
per thread. DXMT_DYN_FULL_WALK=1 walks the whole queue on every call again.

Applied by tools/build-d3d11-dll.sh to its COPY of the sources after
patch-dxmt-dyn-trim-switch.py, so only d3d11-src.dll (env.MADEIRA_D3D11_SRC = 1)
has it. Usage: patch-dxmt-dyn-front-walk.py <tree>/src/dxmt
Idempotent; fails by name if an anchor moves.
"""
import pathlib
import sys

path = pathlib.Path(sys.argv[1]) / "dxmt_dynamic.cpp"
s = path.read_text()
if "DXMT_DYN_FULL_WALK" in s:
    print("dxmt_dynamic.cpp: front walk already patched"); sys.exit(0)

A = "    const bool stats = census_id_ < DYN_CENSUS_SLOTS;\n"
B = """    /* madeira-doge (tools/patch-dxmt-dyn-front-walk.py): the full census walk on one call in 256 */
    static const bool mad_full_always = [] { return env::getEnvVar("DXMT_DYN_FULL_WALK") == "1"; }();
    static thread_local uint32_t mad_walk_tick;
    const bool mad_full = mad_full_always || (++mad_walk_tick & 255) == 0;
    const bool stats = mad_full && census_id_ < DYN_CENSUS_SLOTS;
"""
C = "    for (const auto &e : fifo) {\n      uint64_t bytes = e.allocation.ptr() ? e.allocation->census_bytes_ : 0;\n"
D = """    for (const auto &e : fifo) {
      if (!mad_full && e.will_free_at > coherent_seq_id) break;   /* madeira-doge: the eligible front run is all the trim needs */
      uint64_t bytes = e.allocation.ptr() ? e.allocation->census_bytes_ : 0;
"""
for old in (A, C):
    if s.count(old) != 1:
        sys.exit("patch-dxmt-dyn-front-walk: anchor not found exactly once in dxmt_dynamic.cpp")
s = s.replace(A, B).replace(C, D)
path.write_text(s)
print("dxmt_dynamic.cpp: front walk patched")
