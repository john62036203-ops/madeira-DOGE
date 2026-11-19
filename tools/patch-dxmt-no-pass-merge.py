#!/usr/bin/env python3
"""Switch off DXMT's encoder optimiser (clear / render pass / resolve merging) for one game.

God of War's exposure metering reads a 240x135 texture that a draw writes just before; on some frames the metering sees
other content (builds 643-645). ArgumentEncodingContext::flushCommands merges clears and render passes across encoders it
finds no data dependency with, which moves work later in the command buffer. env.MADEIRA_NO_PASS_MERGE = 1 skips that
loop, so every encoder runs where the game issued it: an experiment that rules the optimiser in or out.

Applied by tools/build-d3d11-dll.sh to its copy of dxmt_context.cpp (argument: that dxmt directory); the object is linked
into d3d11-src.dll ahead of libdxmt.a, as dxmt_dynamic.cpp is. Source-built d3d11 only (env.MADEIRA_D3D11_SRC = 1).
Idempotent; fails by name if the anchor moved.
"""
import pathlib
import sys

PATH = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dxmt/src/dxmt") / "dxmt_context.cpp"
MARKER = "madeira-doge: pass merge switch"

OLD = """  if (encoder_count > 1) {
    unsigned j, i;
"""
NEW = """  /* madeira-doge: pass merge switch (tools/patch-dxmt-no-pass-merge.py) */
  static const bool madeira_no_pass_merge = env::getEnvVar("MADEIRA_NO_PASS_MERGE") == "1";
  if (encoder_count > 1 && !madeira_no_pass_merge) {
    unsigned j, i;
"""


def main():
    src = PATH.read_text()
    if MARKER in src:
        print("no-pass-merge: already applied")
        return 0
    if src.count(OLD) != 1:
        print(f"no-pass-merge: anchor found {src.count(OLD)} times in {PATH}", file=sys.stderr)
        return 1
    PATH.write_text(src.replace(OLD, NEW))
    print("no-pass-merge: applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
