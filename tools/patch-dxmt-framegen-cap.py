#!/usr/bin/env python3
"""Keep the FPS limit while frame generation is on (opt-in).

dxmt/src/winemetal/unix/winemetal_unix.c: madeira_fg_present_inner presents
the generated frame at once and the real one half a game frame later, and the
caller returns before the pacing modes, so no FPS limit applies. With
MADEIRA_FRAMEGEN_CAP=1 (a game's config: env.MADEIRA_FRAMEGEN_CAP = 1) and a
locked pacing mode (1 = 60, 3 = 30, 4 = 40, 5 = 20) each of the two frames is
presented afterMinimumDuration(half the limit's frame time) instead: the
drawable pool gives back-pressure, so the game runs at the limit and the
panel shows twice that, evenly spaced (20 -> 40). Unset: as before.

Also MADEIRA_FRAMEGEN_MIN_FPS=N (5..60, default 15 as before): a game frame
longer than 1/N s counts as a stall, and no frame is generated across a stall.
At the default nothing is generated while the game runs under 15 fps.

Runs after tools/patch-dxmt-framegen.py. Idempotent; fails by name if the
anchor moved. Run from the repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: frame generation under the FPS limit"

ANCHOR = """  [cb presentDrawable:extra];
  [cb presentDrawable:drawable atTime:CACurrentMediaTime() + g_fg.dt * 0.5];
"""
STALL_ANCHOR = """    if (d > 1.0 / 15.0) { d = 1.0 / 15.0; g_fg.have_prev = 0; }   /* a stall: no stale history */
"""
STALL_REPLACEMENT = """    {
      /* madeira-doge: MADEIRA_FRAMEGEN_MIN_FPS moves the stall line (tools/patch-dxmt-framegen-cap.py). */
      static double stall;
      if (stall == 0.0) {
        const char *e = getenv("MADEIRA_FRAMEGEN_MIN_FPS");
        double f = (e && *e) ? atof(e) : 15.0;
        if (!(f >= 5.0)) f = 5.0;
        if (f > 60.0) f = 60.0;
        stall = 1.0 / f;
        if (e && *e)
          dprintf(STDERR_FILENO, "[framegen] MADEIRA_FRAMEGEN_MIN_FPS: frames are generated down to %.1f fps\\n", f);
      }
      if (d > stall) { d = stall; g_fg.have_prev = 0; }   /* a stall: no stale history */
    }
"""
REPLACEMENT = """  {
    /* madeira-doge: frame generation under the FPS limit (tools/patch-dxmt-framegen-cap.py). */
    static int capped = -1;
    int vmode = g_madeira_vsync_mode;
    double period = vmode == 1 ? 1.0 / 60.0 : vmode == 3 ? 1.0 / 30.0 : vmode == 4 ? 1.0 / 40.0 : vmode == 5 ? 1.0 / 20.0 : 0.0;
    if (capped < 0) {
      const char *e = getenv("MADEIRA_FRAMEGEN_CAP");
      capped = (e && *e == '1') ? 1 : 0;
      if (capped)
        dprintf(STDERR_FILENO, "[framegen] MADEIRA_FRAMEGEN_CAP: the FPS limit stays on (pacing mode %d, game frame at least %.1f ms)\\n",
                vmode, period * 1000.0);
    }
    if (capped && period > 0.0) {
      [cb presentDrawable:extra afterMinimumDuration:period * 0.5];
      [cb presentDrawable:drawable afterMinimumDuration:period * 0.5];
    } else {
      [cb presentDrawable:extra];
      [cb presentDrawable:drawable atTime:CACurrentMediaTime() + g_fg.dt * 0.5];
    }
  }
"""


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: frame generation under the FPS limit already present")
        return 0
    if s.count(ANCHOR) != 1:
        print(f"::error::{PATH}: frame generation present anchor not found once -- dxmt moved, review this patch")
        return 1
    if s.find("static volatile int g_madeira_vsync_mode") < 0 or s.find("static volatile int g_madeira_vsync_mode") > s.find(ANCHOR):
        print(f"::error::{PATH}: g_madeira_vsync_mode is not declared before the frame generation present")
        return 1
    if s.count(STALL_ANCHOR) != 1:
        print(f"::error::{PATH}: frame generation stall anchor not found once -- dxmt moved, review this patch")
        return 1
    s = s.replace(STALL_ANCHOR, STALL_REPLACEMENT)
    PATH.write_text(s.replace(ANCHOR, REPLACEMENT))
    print("winemetal_unix.c: MADEIRA_FRAMEGEN_CAP and MADEIRA_FRAMEGEN_MIN_FPS added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
