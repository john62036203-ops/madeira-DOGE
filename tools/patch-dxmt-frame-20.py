#!/usr/bin/env python3
"""Add a 20 FPS present-pacing mode (5) to DXMT's winemetal unix side.

dxmt/src/winemetal/unix/winemetal_unix.c paces every present (D3D11 through
DXMT, and D3D12 through the same winemetal call) by g_madeira_vsync_mode;
modes 1/3/4 hold the drawable with afterMinimumDuration (60/30/40). This adds

    5 = afterMinimumDuration(1/20)

and madeira_dxmt_has_20_cap() so the app offers it only when it is there
(IOSDisplayShim.m has a weak fallback returning 0). The drawable pool gives
back-pressure, so the game itself runs at 20: half the work of 40 a second,
for games a phone can only hold for two minutes before the CPU throttles
(Sekiro, 2026-10-14: 26-30 fps at 3.9 GHz, then 9-15 fps at 1.3 GHz).
Idempotent; fails by name if an anchor moved. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: 20 FPS pacing"

ANCHOR = """  } else if (mode == 2) {
    /* Frame-skip gating lives in _MetalLayer_nextDrawable (nil return);"""
ADDITION = """  } else if (mode == 5) {
    /* madeira-doge: 20 FPS pacing (tools/patch-dxmt-frame-20.py). */
    madeira_log_present_cadence("presentDrawable20", 0.0);
    [(id<MTLCommandBuffer>)params->handle presentDrawable:(id<MTLDrawable>)params->arg
                                     afterMinimumDuration:(1.0 / 20.0)];
"""
CAP_ANCHOR = "int madeira_dxmt_has_40_cap(void) { return 1; }\n"
CAP_ADDITION = "int madeira_dxmt_has_20_cap(void) { return 1; }   /* madeira-doge: vsync mode 5 */\n"
LOG_OLD = "3=locked30 4=locked40)\\n\""
LOG_NEW = "3=locked30 4=locked40 5=locked20)\\n\""


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: 20 FPS pacing already present")
        return 0
    for name, anchor in (("present-pacing", ANCHOR), ("40 FPS capability", CAP_ANCHOR)):
        if s.count(anchor) != 1:
            print(f"::error::{PATH}: {name} anchor not found once -- dxmt moved, review this patch")
            return 1
    s = s.replace(ANCHOR, ADDITION + ANCHOR)
    s = s.replace(CAP_ANCHOR, CAP_ANCHOR + CAP_ADDITION)
    if s.count(LOG_OLD) == 1:
        s = s.replace(LOG_OLD, LOG_NEW)
    PATH.write_text(s)
    print("winemetal_unix.c: 20 FPS pacing mode 5 added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
