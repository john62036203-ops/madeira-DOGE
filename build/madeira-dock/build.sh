#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 125hz
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
#
# Build Madeira Dock (research/madeira-dock) as a stripped x86-64 PE and stage
# it in the app bundle with its notices:
#   app/Madeira/arm64ec-windows/dockhost.exe
#   app/Madeira/arm64ec-windows/dock-notices.txt
# Both are build outputs (gitignored). The app starts dockhost.exe as
# C:\windows\system32\dockhost.exe; without it, Madeira Dock stays hidden.
#
# Usage: build/madeira-dock/build.sh [--check]
#   --check  also build and run Dock's own unit tests with the host compiler
#            (research/madeira-dock/tools/check.sh; needs cc with ASan/UBSan).
# LLVM_MINGW=<dir with x86_64-w64-mingw32-clang> overrides the toolchain.
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$DIR/../.." && pwd)"
SRC="$REPO_ROOT/research/madeira-dock"
MINGW="${LLVM_MINGW:-$REPO_ROOT/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin}"
CC="$MINGW/x86_64-w64-mingw32-clang"
OUT="$REPO_ROOT/app/Madeira/arm64ec-windows"

[ -f "$SRC/src/main.c" ] || { echo "research/madeira-dock is missing: git submodule update --init research/madeira-dock" >&2; exit 1; }
[ -x "$CC" ] || { echo "missing cross compiler: $CC (set LLVM_MINGW)" >&2; exit 1; }

if [ "${1:-}" = "--check" ]; then
    (cd "$SRC" && bash tools/check.sh)
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# madeira-doge: build from a copy of the sources with one addition -- the game's
# launch arguments (Steam page > Game settings > Launch arguments, exported as
# MADEIRA_DOCK_GAME_ARGS) go to Valve's LaunchApp as its user-arguments string,
# where Dock passed "" (the same place Steam's own "Launch Options" end up).
# Unset or empty keeps "" exactly as before.
mkdir -p "$TMP/src"
cp "$SRC"/src/*.c "$SRC"/src/*.h "$TMP/src/"
python3 - "$TMP/src/launch.c" <<'PY' || echo "madeira-dock: launch arguments not added (sources changed)" >&2
import sys
p = sys.argv[1]
s = open(p).read()
call = '(manager, &gameid, 0, 0, "")'
if s.count(call) != 2:
    sys.exit("madeira-dock build: LaunchApp call sites changed (%d found); launch arguments not added" % s.count(call))
s = s.replace(call, '(manager, &gameid, 0, 0, madeira_user_args())')
anchor = '#include <wchar.h>\n'
helper = anchor + """
/* madeira-doge: the game's launch arguments, as LaunchApp's user arguments. */
static const char *madeira_user_args(void)
{
    static char args[1024];
    static wchar_t wide[1024];
    DWORD n = GetEnvironmentVariableW(L"MADEIRA_DOCK_GAME_ARGS", wide, 1024);
    if (!n || n >= 1024) return "";
    if (!WideCharToMultiByte(CP_UTF8, 0, wide, -1, args, (int)sizeof(args), NULL, NULL)) return "";
    return args;
}
"""
if s.count(anchor) != 1:
    sys.exit("madeira-dock build: include anchor changed; launch arguments not added")
s = s.replace(anchor, helper, 1)
# madeira-doge: give Valve's client time after the game exits. Dock shut the
# client down 3 s after the game stopped running; the client uploads the Steam
# Cloud save and tells Steam's servers the game has ended only after that, on
# its own worker threads, so the save never reached the cloud and another
# machine was told the game was still running. Keep the client alive and its
# callbacks served for MADEIRA_DOCK_EXIT_SYNC_S seconds (default 30, 0 = off).
ended = """                o->event("launch-game-ended", 1);
"""
if s.count(ended) == 1:
    s = s.replace(ended, ended + """                {
                    wchar_t grace_text[8] = {0};
                    DWORD grace_len = GetEnvironmentVariableW(L"MADEIRA_DOCK_EXIT_SYNC_S", grace_text, 8);
                    unsigned long grace_s = grace_len && grace_len < 8 ? wcstoul(grace_text, NULL, 10) : 30;
                    uint64_t grace_begin = o->now_ms();
                    unsigned grace_logged = 0;
                    if (grace_s > 300) grace_s = 300;
                    o->event("launch-exit-sync-wait", (int32_t)grace_s);
                    while (!InterlockedCompareExchange(&interrupted, 0, 0) &&
                           o->now_ms() - grace_begin < (uint64_t)grace_s * 1000) {
                        for (unsigned grace_batch = 0; grace_batch < 64; ++grace_batch) {
                            struct sh_callback grace_cb = {0};
                            if (!api->get_callback(pipe, &grace_cb)) break;
                            if (grace_logged < 24) { o->event("launch-exit-callback-id", grace_cb.id); ++grace_logged; }
                            api->free_callback(pipe);
                        }
                        o->sleep_ms(50);
                    }
                    o->event("launch-exit-sync-done", (int32_t)((o->now_ms() - grace_begin) / 1000));
                }
""", 1)
    print("madeira-dock: exit grace period for Steam Cloud patched into launch.c")
else:
    print("madeira-dock: game-ended site changed; exit grace period not added", file=sys.stderr)
open(p, "w").write(s)
print("madeira-dock: launch arguments from MADEIRA_DOCK_GAME_ARGS patched into launch.c")
PY

# Same flags as Dock's own tools/build.sh: warnings are errors, the runtime is
# linked statically (its notices go into dock-notices.txt) and symbols are
# stripped. -Wl,--no-insert-timestamp keeps the output reproducible.
# If the patched copy does not build, the unmodified sources are built instead
# (no launch arguments, Dock itself unaffected).
if ! "$CC" -std=c11 -O2 -Wall -Wextra -Werror -Wno-cast-function-type \
    -static -Wl,--strip-all -Wl,--no-insert-timestamp \
    -I"$SRC/src" -o "$TMP/dockhost.exe" "$TMP"/src/*.c -ladvapi32; then
    echo "::warning::madeira-dock: the patched build failed; building the unmodified sources (no launch arguments, no exit grace period)" >&2
    "$CC" -std=c11 -O2 -Wall -Wextra -Werror -Wno-cast-function-type \
        -static -Wl,--strip-all -Wl,--no-insert-timestamp \
        -o "$TMP/dockhost.exe" "$SRC"/src/*.c -ladvapi32
fi

section() { printf '\n\n==== %s ====\n\n' "$1"; }
{
    cat "$SRC/LICENSE"
    printf '\nCorresponding source: https://github.com/125hz/madeira-dock (commit %s)\n' \
        "$(git -C "$SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
    section 'LICENSE-EXCEPTION.md (Madeira Converter Exception)'
    cat "$SRC/LICENSE-EXCEPTION.md"
    section 'COPYING (GNU General Public License, version 3)'
    cat "$SRC/COPYING"
    section 'MinGW-w64 runtime notice (statically linked runtime)'
    cat "$SRC/notices/MinGW-w64-runtime.txt"
    section 'LLVM runtime notice'
    cat "$SRC/notices/LLVM.txt"
} > "$TMP/dock-notices.txt"

mkdir -p "$OUT"
cp "$TMP/dockhost.exe" "$TMP/dock-notices.txt" "$OUT/"
if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$OUT/dockhost.exe"; else sha256sum "$OUT/dockhost.exe"; fi
ls -la "$OUT/dockhost.exe" "$OUT/dock-notices.txt"
