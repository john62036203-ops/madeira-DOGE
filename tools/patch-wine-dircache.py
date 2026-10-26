#!/usr/bin/env python3
"""Directory-listing cache for case-insensitive lookups (upstream PR #427).

willfaust/wine PR #57 (ae2a9e8, "ntdll iOS: answer case-insensitive lookups
from cached directory listings"): a name that does not stat in its exact case
is answered from an in-memory copy of its directory instead of a volume
query and a directory read per lookup (twice when the name is absent).
Source-engine games probe thousands of absent paths; TF2 went from ~10 min
to 55 s to a map upstream. MADEIRA_DIRCACHE=0 turns it off,
MADEIRA_DIRCACHE_TTL_MS (default 1000) is the trust window.

This fork pins wine at 257f271 and patches file.c at build time, so the PR's
file.c diff is kept as tools/patch-wine-dircache.diff and applied here with
patch(1). build/wineserver/fd_ios.c calls the weak madeira_dircache_changed()
on deletes, mkdirs, renames and links (PR #427's server half, applied in-tree).

Runs BEFORE the other file.c patch scripts (their anchors are untouched by the
diff; checked by tests/host/check-dircache-patch.py). Idempotent; exits
non-zero when the diff does not apply.
Usage: patch-wine-dircache.py [path/to/wine/dlls/ntdll/unix/file.c]
"""
import os
import subprocess
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "wine/dlls/ntdll/unix/file.c"
diff = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch-wine-dircache.diff")
src = open(path).read()
if "madeira_dircache_changed" in src:
    print("patch-wine-dircache: already patched")
    sys.exit(0)
r = subprocess.run(["patch", "-p3", "--no-backup-if-mismatch", "-F0", path],
                   stdin=open(diff), capture_output=True, text=True)
sys.stdout.write(r.stdout)
sys.stderr.write(r.stderr)
if r.returncode:
    print("patch-wine-dircache: FAILED to apply tools/patch-wine-dircache.diff", file=sys.stderr)
    sys.exit(1)
src = open(path).read()
for need in ("madeira_dircache_changed", "MADEIRA_DIRCACHE", "dircache_find"):
    if need not in src:
        print("patch-wine-dircache: %s missing after patch" % need, file=sys.stderr)
        sys.exit(1)
print("patch-wine-dircache: applied (MADEIRA_DIRCACHE=0 disables)")
