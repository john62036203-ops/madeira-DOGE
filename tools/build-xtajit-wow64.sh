#!/bin/bash
# Build FEX's aarch64 WOW64 module (libwow64fex.dll, shipped as
# app/Madeira/aarch64-windows/xtajit.dll -- the CPU backend wow64.dll loads for
# 32-bit x86 programs) and ship it over the committed copy.
#
# Taken from upstream madeira-bcd build 270 (tools/build-xtajit-wow64.sh) for
# the 221 tree. Differences from upstream:
#  - The 221 tree's FEX submodule (used for libFEXCore and the ARM64EC module,
#    xtajit64.dll) is OLDER than the commits that add the iOS WOW64 module, so
#    this script builds from a separate checkout of FEX at FEX_WOW64_REV
#    (default: the revision upstream build 270 pins), in $FEX_WOW64_SRC
#    (default FEX-wow64/). The submodule and everything 64-bit stay untouched.
#  - Run from the repo root. On any failure the committed module stays.
#
# Patches (both carried by upstream build 270):
#  - patch-fex-ios-cpuid-index.py: CPUID 0x80000002-4 indexed the per-CPU table
#    with the raw host CPU number; 32-bit Crysis died in strlen(0xfff68000)
#    inside Function_8000_0002h before its first frame. (FEX at the pinned
#    revision already bounds the index itself; the script then does nothing.)
#  - patch-fex-ios-teb-tsd.py: the WinAPI shims' GetCurrentTEB() read x18,
#    which is 0 on some iOS threads (a TlsGetValue shim reading TEB fields at
#    a near-NULL address). The TEB is taken from Wine's TSD slot instead.
set -eu
R="$(pwd)"
MINGW="${MINGW:-$R/toolchains/llvm-mingw-20260421-ucrt-macos-universal/bin}"
export PATH="$MINGW:$PATH"
REV="${FEX_WOW64_REV:-26859e184ad90f0e811d7f8bbd943a4b1573a2c3}"
F="${FEX_WOW64_SRC:-$R/FEX-wow64}"
B="${FEX_WOW64_BUILD:-$F/build-wow64}"
SHIP="$R/app/Madeira/aarch64-windows/xtajit.dll"
JOBS="$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
# FEX's submodules that the module build needs (not the test binaries).
SUBS="External/vixl Source/Common/cpp-optparse External/fmt External/drm-headers External/xxhash
      External/Catch2 External/Vulkan-Headers External/jemalloc_glibc External/tracy External/range-v3
      External/zydis External/unordered_dense External/rpmalloc"

[ -f "$SHIP" ] || { echo "::warning::no committed xtajit.dll to replace"; exit 1; }

# ------------------------------------------------------------- the checkout
if [ "$(git -C "$F" rev-parse HEAD 2>/dev/null)" != "$REV" ]; then
    if [ ! -d "$F/.git" ]; then
        rm -rf "$F.tmp"
        git clone -q --no-checkout "$R/FEX" "$F.tmp"
        # keep a build dir a cache restore may have put in place
        if [ -d "$F" ]; then mv "$F.tmp/.git" "$F/.git"; rm -rf "$F.tmp"; else mv "$F.tmp" "$F"; fi
    fi
    git -C "$F" remote set-url origin https://github.com/willfaust/FEX.git
    git -C "$F" fetch -q origin "$REV"
    git -C "$F" checkout -q -f --detach "$REV"
fi
# shellcheck disable=SC2086
git -C "$F" submodule update --init --recursive $SUBS > "$F.submodules.log" 2>&1 \
    || { tail -20 "$F.submodules.log"; exit 1; }

# --------------------------------------------------------------- the patches
CPUIDF="FEXCore/Source/Interface/Core/CPUID.cpp"
git -C "$F" diff --name-only | while read -r f; do git -C "$F" checkout -- "$f"; done
python3 "$R/tools/patch-fex-ios-cpuid-index.py" "$F/$CPUIDF"
python3 "$R/tools/patch-fex-ios-teb-tsd.py" "$F/Source/Windows/Common/Priv.h"
restore() { git -C "$F" checkout -- "$CPUIDF" Source/Windows/Common/Priv.h 2>/dev/null || true; }
trap restore EXIT

# ----------------------------------------------------------------- the build
cmake -S "$F" -B "$B" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$F/Data/CMake/toolchain_mingw.cmake" \
    -DMINGW_TRIPLE=aarch64-w64-mingw32 \
    -DFEX_IOS_HOST_BUILD=ON -DCMAKE_C_FLAGS=-DFEX_IOS_HOST \
    -DCMAKE_CXX_FLAGS=-DFEX_IOS_HOST -DCMAKE_ASM_FLAGS=-DFEX_IOS_HOST \
    -DENABLE_LTO=OFF -DENABLE_ASSERTIONS=OFF -DENABLE_JEMALLOC_GLIBC_ALLOC=OFF \
    -DBUILD_TESTING=OFF -DBUILD_FEXCONFIG=OFF -DENABLE_CCACHE=OFF -DBUILD_THUNKS=OFF \
    -DTUNE_ARCH=generic -DTUNE_CPU=none \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 > "$B.cfg.log" 2>&1 \
    || { tail -30 "$B.cfg.log"; exit 1; }
cmake --build "$B" --target wow64fex -j"$JOBS" > "$B.build.log" 2>&1 \
    || { grep -m 20 "error" "$B.build.log"; exit 1; }

# ------------------------------------------------- same exports, then ship
"$MINGW/llvm-readobj" --coff-exports "$B/Bin/libwow64fex.dll" | awk '$1 == "Name:" { print $2 }' | sort > "$B.new-exports"
"$MINGW/llvm-readobj" --coff-exports "$SHIP" | awk '$1 == "Name:" { print $2 }' | sort > "$B.old-exports"
if ! diff "$B.old-exports" "$B.new-exports"; then
    echo "::warning::the rebuilt WOW64 module exports differ from the committed xtajit.dll; keeping the committed one"
    exit 1
fi
cp "$B/Bin/libwow64fex.dll" "$SHIP"
echo "::notice::xtajit.dll (WOW64) built from FEX $(git -C "$F" rev-parse --short HEAD) with the CPUID index wrap and the TSD-slot TEB for the WinAPI shims, and shipped"
