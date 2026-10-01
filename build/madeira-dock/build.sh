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
    echo "madeira-dock: the launch-arguments build failed; building the unmodified sources" >&2
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
