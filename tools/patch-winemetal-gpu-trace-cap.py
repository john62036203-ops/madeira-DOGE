#!/usr/bin/env python3
"""GPU trace on demand: the CAP button traces the next frame.

MADEIRA_GPU_TRACE only traces at fixed times (T, T+60, T+120 s), which rarely
land on the moment the owner sees the picture go wrong, and D3D11 has no frame
capture of its own. The app's CAP button now also creates
Documents/gpu-trace-now; while MADEIRA_GPU_TRACE is set, winemetal looks for
that file after each presented frame (at most ten times a second), removes it
and traces the next frame exactly like a timed one ([gpu-trace] F<n> ..., the
float-target values after it), up to 24 times a session. Set
`env.MADEIRA_GPU_TRACE = 99999` for CAP-only traces. `[gpu-trace] CAP ...`
marks each.

Needs tools/patch-winemetal-gpu-trace.py first. Native only; not in the i386
farm key. Idempotent; fails by name if an anchor moves. Run from the
repository root.
"""
import pathlib
import sys

PATH = pathlib.Path("dxmt/src/winemetal/unix/winemetal_unix.c")
MARKER = "madeira-doge: gpu trace on CAP"
NAME = "patch-winemetal-gpu-trace-cap"

HELPER = r'''/* madeira-doge: gpu trace on CAP (tools/patch-winemetal-gpu-trace-cap.py) --
 * the app's CAP button creates Documents/gpu-trace-now; 1 = trace the next frame. */
#include <unistd.h>
static int madeira_gt_cap_requested(double now) {
  static double next;
  static int left = 24;
  static char path[1000];
  if (left <= 0 || now < next) return 0;
  next = now + 0.1;
  if (!path[0]) {
    const char *docs = getenv("MADEIRA_DOCS_DIR"), *home = getenv("HOME");
    if (docs && *docs) snprintf(path, sizeof path, "%s/gpu-trace-now", docs);
    else if (home && *home) snprintf(path, sizeof path, "%s/Documents/gpu-trace-now", home);
    else { left = 0; return 0; }
  }
  if (access(path, F_OK) != 0) return 0;
  unlink(path);
  left--;
  fprintf(stderr, "[gpu-trace] CAP: tracing the next frame (%d more this session)\n", left);
  return 1;
}

static void madeira_gt_note_present(obj_handle_t cb) {
'''

PAIRS = [
    ("static void madeira_gt_note_present(obj_handle_t cb) {\n", HELPER, 1),
    ("""  if (madeira_gt_full_left > 0 && now >= madeira_gt_next_full) {
    madeira_gt_full_left--;
    madeira_gt_next_full = now + 60.0;
""",
     """  int mad_cap = madeira_gt_cap_requested(now);   /* madeira-doge: gpu trace on CAP */
  if (mad_cap || (madeira_gt_full_left > 0 && now >= madeira_gt_next_full)) {
    if (!mad_cap) {
      madeira_gt_full_left--;
      madeira_gt_next_full = now + 60.0;
    }
""", 1),
]


def main():
    s = PATH.read_text()
    if MARKER in s:
        print("winemetal_unix.c: already patched")
        return 0
    if "madeira-bcd: gpu trace" not in s:
        sys.exit(f"{NAME}: 'madeira-bcd: gpu trace' missing -- run tools/patch-winemetal-gpu-trace.py first")
    for old, new, want in PAIRS:
        n = s.count(old)
        if n != want:
            sys.exit(f"{NAME}: anchor found {n} times (want {want}) in {PATH}:\n{old}")
        s = s.replace(old, new)
    PATH.write_text(s)
    print("winemetal_unix.c: patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
