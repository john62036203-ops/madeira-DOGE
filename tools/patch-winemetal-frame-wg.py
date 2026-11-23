#!/usr/bin/env python3
"""Tell the frame workgroup where a frame ends (MADEIRA_FRAME_WG, opt-in).

build/ntdll-unix/thread_ios.c puts every guest thread in one interval
workgroup when env.MADEIRA_FRAME_WG = <fps> is set, so that iOS's performance
controller is told a deadline for the game's frames (the notes there say
why). The interval has to be ended and restarted once a frame by a thread of
the workgroup: winemetal's two presentDrawable calls are that point, and they
run on the guest thread that presents. This adds one call to
madeira_frame_wg_tick() to each; with the switch unset the call returns at
its first test.

Native only (winemetal unix side), not in the i386 farm key. Idempotent;
fails by name if an anchor moves. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: frame workgroup"

PAIRS = [
    ("""extern void ios_frame_encode_present(int skipped);
""",
     """extern void ios_frame_encode_present(int skipped);
/* madeira-doge: frame workgroup (tools/patch-winemetal-frame-wg.py): ends one
 * interval and starts the next; nothing unless MADEIRA_FRAME_WG is set. */
extern void madeira_frame_wg_tick(void);
"""),
    ("""  /* ml1050: this call IS the frame boundary on the encode thread. */
""",
     """  madeira_frame_wg_tick();   /* madeira-doge: frame workgroup */
  /* ml1050: this call IS the frame boundary on the encode thread. */
"""),
    ("""  madeira_log_present_cadence("presentDrawableAfterMinDuration", params->arg1);
""",
     """  madeira_frame_wg_tick();   /* madeira-doge: frame workgroup */
  madeira_log_present_cadence("presentDrawableAfterMinDuration", params->arg1);
"""),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: frame workgroup already patched")
        return 0
    for old, new in PAIRS:
        if s.count(old) != 1:
            sys.exit(f"patch-winemetal-frame-wg: anchor found {s.count(old)} times (want 1) in {PATH}:\n{old}")
        s = s.replace(old, new)
    PATH.write_text(s)
    print("winemetal_unix.c: frame workgroup patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
